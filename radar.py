import json
import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.extras import Json
from pydantic import BaseModel, Field, field_validator

import radar_logica as rl
from db import obtener_conexion
from dependencias import sesion_radar, usuaria_modo_normal
from seguridad import cifrar_texto

router = APIRouter(prefix="/radar", tags=["Radar de talentos"])


# ============================================================ LÍMITE DE USO DE LA IA
# Protege tu cuota gratuita: si una usuaria abusa, se le sirve el banco de respaldo (sin error).
# La clave es el id de la usuaria o, durante el registro, su seudónimo.
_llamadas = defaultdict(deque)
MAX_LLAMADAS_IA = 8        # por usuaria
VENTANA_SEGUNDOS = 600     # cada 10 minutos


def _puede_usar_ia(clave: str) -> bool:
    if not rl.GEMINI_API_KEY:
        return False
    ahora = time.time()
    cola = _llamadas[clave]
    while cola and ahora - cola[0] > VENTANA_SEGUNDOS:
        cola.popleft()
    if len(cola) >= MAX_LLAMADAS_IA:
        return False
    cola.append(ahora)
    return True


# ============================================================ MODELOS DE ENTRADA

class Bloque1In(BaseModel):
    actividades: list[str] = Field(min_length=1, max_length=4)
    tiempo: str

    @field_validator("actividades")
    @classmethod
    def _actividades(cls, v: list[str]) -> list[str]:
        if any(a not in rl.ACTIVIDADES for a in v):
            raise ValueError("Elige actividades de la lista")
        return list(dict.fromkeys(v))  # sin repetidas, conservando el orden

    @field_validator("tiempo")
    @classmethod
    def _tiempo(cls, v: str) -> str:
        if v not in rl.TIEMPOS:
            raise ValueError("Elige una opción de tiempo libre")
        return v


class RespuestaDinamica(BaseModel):
    pregunta: str = Field(max_length=200)
    tipo: Literal["chips", "casillas", "texto"]
    seleccion: list[str] = Field(default_factory=list, max_length=8)
    texto: str = Field(default="", max_length=400)

    @field_validator("seleccion")
    @classmethod
    def _seleccion(cls, v: list[str]) -> list[str]:
        return [s.strip()[:60] for s in v if s.strip()]


class FinalizarIn(Bloque1In):
    respuestas: list[RespuestaDinamica] = Field(default_factory=list, max_length=3)


# --- Lo que la app manda al crear la cuenta: el radar completo + el perfil que se le mostró.
# El perfil viene del cliente, así que NO se confía en él: pasa otra vez por rl.validar_perfil.

class HabilidadIn(BaseModel):
    titulo: str = Field(max_length=100)
    descripcion: str = Field(default="", max_length=300)
    categoria: str = Field(default="", max_length=60)


class PerfilIn(BaseModel):
    mensaje_final: str = Field(default="", max_length=400)
    areas_fuertes: list[str] = Field(default_factory=list, max_length=10)
    areas_oportunidad: list[str] = Field(default_factory=list, max_length=10)
    habilidades: list[HabilidadIn] = Field(min_length=1, max_length=10)
    fuente: str = Field(default="", max_length=20)


class RadarCompletoIn(FinalizarIn):
    perfil: PerfilIn


# ============================================================ AYUDAS COMPARTIDAS
# (main.py las usa también al crear la cuenta)

def limpiar_respuestas(respuestas: list[RespuestaDinamica]) -> list[dict]:
    """Quita teléfonos, correos y ligas del texto libre antes de usarlo o guardarlo."""
    return [
        {"pregunta": r.pregunta, "tipo": r.tipo, "seleccion": r.seleccion,
         "texto": rl.sanitizar_texto(r.texto)}
        for r in respuestas
    ]


def perfil_desde_cliente(perfil: PerfilIn, actividades: list[str]) -> dict:
    """Revalida (y recorta) el perfil que mandó la app."""
    try:
        return rl.validar_perfil(perfil.model_dump(), rl.ACTIVIDADES[actividades[0]]["area"])
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El resultado del radar no es válido. Intenta de nuevo")


def guardar_perfil(cur, uid, actividades: list[str], tiempo: str, respuestas: list[dict], perfil: dict) -> None:
    """Guarda el perfilado + habilidades de una usuaria que YA existe.
    Usa el cursor que le pasen para que quien la llame decida la transacción
    (en el registro va junto con la usuaria y la mascota: todo o nada)."""
    # Las respuestas (incluido el texto libre) se guardan cifradas con AES-256-GCM
    paquete = {"actividades": actividades, "tiempo": tiempo, "respuestas": respuestas}
    respuestas_cifradas = {"v": 1, "cifrado": cifrar_texto(json.dumps(paquete, ensure_ascii=False))}

    cur.execute(
        """
        INSERT INTO perfilado (usuaria_id, respuestas, areas_fuertes, areas_oportunidad)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (usuaria_id) DO UPDATE SET
            respuestas        = EXCLUDED.respuestas,
            areas_fuertes     = EXCLUDED.areas_fuertes,
            areas_oportunidad = EXCLUDED.areas_oportunidad,
            creado_en         = now()
        """,
        (uid, Json(respuestas_cifradas), Json(perfil["areas_fuertes"]),
         Json(perfil["areas_oportunidad"])),
    )
    cur.execute("DELETE FROM habilidades_usuaria WHERE usuaria_id = %s", (uid,))
    for h in perfil["habilidades"]:
        cur.execute(
            "INSERT INTO habilidades_usuaria (usuaria_id, titulo, descripcion, categoria) "
            "VALUES (%s, %s, %s, %s)",
            (uid, h["titulo"], h["descripcion"], h["categoria"]),
        )


# ============================================================ ENDPOINTS
# bloque1 / analizar / finalizar los puede usar quien está registrándose (pase 'registro')
# o una usuaria con sesión normal. /resultado solo una usuaria ya registrada.

@router.get("/bloque1")
def obtener_bloque1(sesion: dict = Depends(sesion_radar)):
    """Las 2 preguntas fijas del Bloque I."""
    return {"preguntas": rl.preguntas_bloque1()}


@router.post("/analizar")
def analizar(datos: Bloque1In, sesion: dict = Depends(sesion_radar)):
    """Recibe el Bloque I y devuelve el mensaje personalizado + las 3 preguntas del Bloque II."""
    fuente = "respaldo"
    resultado = None
    if _puede_usar_ia(sesion["id"]):
        try:
            resultado = rl.generar_bloque2_ia(datos.actividades, datos.tiempo)
            fuente = "ia"
        except rl.ErrorIA as e:
            print(f"[radar] IA no disponible, uso respaldo: {e}")
    if resultado is None:
        resultado = rl.bloque2_respaldo(datos.actividades, datos.tiempo)
    return {**resultado, "fuente": fuente}


@router.post("/finalizar")
def finalizar(datos: FinalizarIn, sesion: dict = Depends(sesion_radar)):
    """Recibe todo y determina las habilidades (RF-03).

    - Durante el registro (pase 'registro') solo CALCULA: la cuenta aún no existe y el perfil
      se guarda cuando la app llama a /auth/registro-completo.
    - Con una usuaria ya registrada (sesión normal) además lo guarda (por si repite el radar).
    """
    respuestas = limpiar_respuestas(datos.respuestas)

    fuente = "respaldo"
    perfil = None
    if _puede_usar_ia(sesion["id"]):
        try:
            perfil = rl.generar_perfil_ia(datos.actividades, datos.tiempo, respuestas)
            fuente = "ia"
        except rl.ErrorIA as e:
            print(f"[radar] IA no disponible, uso respaldo: {e}")
    if perfil is None:
        perfil = rl.perfil_respaldo(datos.actividades, datos.tiempo, respuestas)

    if sesion["modo"] == "normal":
        with obtener_conexion() as conn:
            try:
                with conn.cursor() as cur:
                    guardar_perfil(cur, sesion["id"], datos.actividades, datos.tiempo, respuestas, perfil)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    return {**perfil, "fuente": fuente}


@router.get("/resultado")
def obtener_resultado(usuaria: dict = Depends(usuaria_modo_normal)):
    """El perfil ya calculado (para mostrarlo en la pantalla de Perfil, RF-03)."""
    uid = usuaria["id"]
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT areas_fuertes, areas_oportunidad FROM perfilado WHERE usuaria_id = %s",
                (uid,),
            )
            perfil = cur.fetchone()
            if perfil is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Aún no has completado el radar de talentos")
            cur.execute(
                "SELECT titulo, descripcion, categoria FROM habilidades_usuaria WHERE usuaria_id = %s ORDER BY creada_en",
                (uid,),
            )
            habilidades = cur.fetchall()
    return {
        "areas_fuertes": perfil["areas_fuertes"] or [],
        "areas_oportunidad": perfil["areas_oportunidad"] or [],
        "habilidades": [dict(h) for h in habilidades],
    }
