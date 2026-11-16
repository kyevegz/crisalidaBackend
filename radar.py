import json
import re
import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.extras import Json
from pydantic import BaseModel, Field, ValidationInfo, field_validator

import radar_logica as rl
from db import obtener_conexion
from dependencias import sesion_radar, usuaria_vendedora
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
    # Las 2 preguntas abiertas fijas (8.1): obligatorias, ni vacías ni demasiado largas
    gusta: str   # ¿Qué te gusta hacer?
    sabe: str    # ¿Qué sabes hacer?

    @field_validator("gusta", "sabe")
    @classmethod
    def _abiertas(cls, v: str, info: ValidationInfo) -> str:
        pregunta = "¿Qué te gusta hacer?" if info.field_name == "gusta" else "¿Qué sabes hacer?"
        v = re.sub(r"\s+", " ", v or "").strip()
        if len(v) < rl.MIN_ABIERTA:
            raise ValueError(f"Cuéntanos tu respuesta a «{pregunta}»: escribe al menos {rl.MIN_ABIERTA} letras")
        if len(v) > rl.MAX_ABIERTA:
            raise ValueError(f"Tu respuesta a «{pregunta}» es muy larga: máximo {rl.MAX_ABIERTA} caracteres")
        return v

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
    respuestas: list[RespuestaDinamica] = Field(default_factory=list, max_length=rl.MAX_DINAMICAS)   # hasta 6 (8.2)


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


def limpiar_abiertas(datos: Bloque1In) -> dict:
    """Las 2 respuestas abiertas, sin teléfonos, correos ni ligas, antes de mandarlas a la IA o guardarlas."""
    return {
        "gusta": rl.sanitizar_texto(datos.gusta, rl.MAX_ABIERTA),
        "sabe": rl.sanitizar_texto(datos.sabe, rl.MAX_ABIERTA),
    }


def perfil_desde_cliente(perfil: PerfilIn, actividades: list[str]) -> dict:
    """Revalida (y recorta) el perfil que mandó la app. La usuaria pudo EDITARLO (8.3): todo texto libre pasa por
    el mismo filtro de teléfonos, correos y ligas antes de guardarse."""
    datos = perfil.model_dump()
    datos["mensaje_final"] = rl.sanitizar_texto(datos.get("mensaje_final", ""), 300)
    datos["areas_fuertes"] = [rl.sanitizar_texto(x, 60) for x in datos.get("areas_fuertes", [])]
    datos["areas_oportunidad"] = [rl.sanitizar_texto(x, 60) for x in datos.get("areas_oportunidad", [])]
    datos["habilidades"] = [
        {"titulo": rl.sanitizar_texto(h["titulo"], 60),
         "descripcion": rl.sanitizar_texto(h.get("descripcion", ""), 160),
         "categoria": h.get("categoria", "")}
        for h in datos.get("habilidades", [])
    ]
    try:
        return rl.validar_perfil(datos, rl.ACTIVIDADES[actividades[0]]["area"])
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El resultado del radar no es válido. Intenta de nuevo")


def guardar_perfil(cur, uid, actividades: list[str], tiempo: str, respuestas: list[dict], perfil: dict,
                   abiertas: dict | None = None) -> None:
    """Guarda el perfilado + habilidades de una usuaria que YA existe.
    Usa el cursor que le pasen para que quien la llame decida la transacción
    (en el registro va junto con la usuaria y la mascota: todo o nada)."""
    # Las respuestas (incluido el texto libre) se guardan cifradas con AES-256-GCM
    paquete = {"actividades": actividades, "tiempo": tiempo, "respuestas": respuestas}
    if abiertas:
        paquete["abiertas"] = abiertas   # lo que contestó a «¿Qué te gusta hacer?» y «¿Qué sabes hacer?» (8.1)
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
    """Las preguntas fijas del Bloque I: actividades, tiempo y las 2 abiertas (¿Qué te gusta hacer? / ¿Qué sabes hacer?)."""
    return {"preguntas": rl.preguntas_bloque1()}


@router.post("/analizar")
def analizar(datos: Bloque1In, sesion: dict = Depends(sesion_radar)):
    """Recibe el Bloque I y devuelve el mensaje personalizado + hasta 6 preguntas dinámicas del Bloque II (IA o respaldo, mismo formato)."""
    abiertas = limpiar_abiertas(datos)
    fuente = "respaldo"
    resultado = None
    if _puede_usar_ia(sesion["id"]):
        try:
            resultado = rl.generar_bloque2_ia(datos.actividades, datos.tiempo, abiertas)
            fuente = "ia"
        except rl.ErrorIA as e:
            print(f"[radar] IA no disponible, uso respaldo: {e}")
    if resultado is None:
        resultado = rl.bloque2_respaldo(datos.actividades, datos.tiempo)
    return {**resultado, "fuente": fuente}


@router.post("/finalizar")
def finalizar(datos: FinalizarIn, sesion: dict = Depends(sesion_radar)):
    """Calcula la PROPUESTA de resultado (RF-03). NO guarda nada (8.3): la usuaria puede editarla y solo se
    guarda cuando la acepta (en el registro, con /auth/registro-completo; con una cuenta que ya existe, con
    /radar/aceptar). Si abandona el radar no queda nada en la base."""
    respuestas = limpiar_respuestas(datos.respuestas)
    abiertas = limpiar_abiertas(datos)

    fuente = "respaldo"
    perfil = None
    if _puede_usar_ia(sesion["id"]):
        try:
            perfil = rl.generar_perfil_ia(datos.actividades, datos.tiempo, respuestas, abiertas)
            fuente = "ia"
        except rl.ErrorIA as e:
            print(f"[radar] IA no disponible, uso respaldo: {e}")
    if perfil is None:
        perfil = rl.perfil_respaldo(datos.actividades, datos.tiempo, respuestas)

    return {**perfil, "fuente": fuente}


@router.post("/aceptar")
def aceptar(datos: RadarCompletoIn, sesion: dict = Depends(sesion_radar)):
    """La usuaria (ya registrada) ACEPTA su resultado, tal cual o editado (8.3): aquí es donde por fin se guarda.
    Reemplaza su perfil anterior, si lo había. Durante el registro no se usa: ahí se guarda al crear la cuenta."""
    if sesion["modo"] != "normal":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu resultado se guarda al terminar tu registro")
    respuestas = limpiar_respuestas(datos.respuestas)
    abiertas = limpiar_abiertas(datos)
    perfil = perfil_desde_cliente(datos.perfil, datos.actividades)

    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                guardar_perfil(cur, sesion["id"], datos.actividades, datos.tiempo, respuestas, perfil, abiertas)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    fuente = datos.perfil.fuente if datos.perfil.fuente in ("ia", "respaldo") else "respaldo"
    return {**perfil, "fuente": fuente}


@router.get("/resultado")
def obtener_resultado(usuaria: dict = Depends(usuaria_vendedora)):
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