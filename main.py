import os
import re

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, field_validator, model_validator

from db import obtener_conexion
from dependencias import sesion_registro, usuaria_actual, usuaria_modo_normal
from radar import (
    RadarCompletoIn,
    guardar_perfil,
    limpiar_respuestas,
    perfil_desde_cliente,
    router as radar_router,
)
from bienestar import router as bienestar_router
from cambio_rol import router as cambio_rol_router
from cuenta import router as cuenta_router
from datos_personales import router as datos_personales_router
from demo import MODO_DEMO, router as demo_router
from frases import router as frases_router
from marketplace import router as marketplace_router
from progreso import router as progreso_router
from publicaciones import router as publicaciones_router
from retos import router as retos_router
from retos_publicados import router as retos_publicados_router
from recuperacion import router as recuperacion_router
from reportes import router as reportes_router
from seguridad import (
    HASH_FALSO,
    MAX_INTENTOS,
    MINUTOS_BLOQUEO,
    crear_token,
    crear_token_registro,
    generar_codigo_recuperacion,
    hashear_codigo,
    hashear_pin,
    validar_pin,
    verificar_pin,
)

app = FastAPI(title="API Crisálida", version="0.1.0")
app.include_router(radar_router)   # /radar/...
app.include_router(progreso_router)        # /progreso/..., /perfil/avatar
app.include_router(marketplace_router)     # /categorias, /marketplace
app.include_router(retos_publicados_router)  # POST /retos (publicar un reto)
app.include_router(retos_router)           # /retos/...
app.include_router(publicaciones_router)   # /publicaciones/..., /imagenes/...
app.include_router(bienestar_router)       # /bienestar/...
app.include_router(frases_router)          # /frases-apoyo
app.include_router(datos_personales_router)  # /perfil/datos, /perfil/correo
app.include_router(recuperacion_router)    # /auth/recuperar/...
app.include_router(reportes_router)        # /reportes, /bloqueos
app.include_router(cuenta_router)          # /cuenta/estado, /cuenta/suspender, /cuenta/reactivar
app.include_router(cambio_rol_router)      # /cuenta/rol
if MODO_DEMO:                              # atajos para la presentación (apagados por defecto)
    app.include_router(demo_router)        # /demo/...

SEUDONIMO_RE = re.compile(r"^\w{3,30}$")   # letras, números y guion bajo
# Versión vigente del aviso de privacidad y términos. Al cambiarla (variable AVISO_VERSION), a todas
# las usuarias se les pide aceptar de nuevo en su siguiente login.
AVISO_VERSION = os.getenv("AVISO_VERSION", "1")
MENSAJE_CREDENCIALES = "Seudónimo o PIN incorrectos"


# ============================================================ MODELOS

class RegistroIn(BaseModel):
    seudonimo: str
    pin: str
    pin_camuflaje: str

    @field_validator("seudonimo")
    @classmethod
    def _seudonimo(cls, v: str) -> str:
        v = v.strip()
        if not SEUDONIMO_RE.match(v):
            raise ValueError("El seudónimo debe tener de 3 a 30 letras, números o guion bajo")
        return v

    @field_validator("pin", "pin_camuflaje")
    @classmethod
    def _pins(cls, v: str) -> str:
        return validar_pin(v)

    @model_validator(mode="after")
    def _pins_distintos(self):
        if self.pin == self.pin_camuflaje:
            raise ValueError("El PIN de camuflaje debe ser distinto al PIN principal")
        return self


class LoginIn(BaseModel):
    seudonimo: str
    pin: str


class SesionOut(BaseModel):
    usuaria_id: str
    seudonimo: str
    avatar: str
    modo: str      # "normal" o "camuflaje" (en camuflaje la app muestra la galería de mariposas)
    token: str
    rol: str = "vendedora"   # "vendedora" o "compradora"
    estado: str = "activa"   # "activa" o "suspendida" (en reposo: sus publicaciones no se ven; la app lo puede mostrar)
    aviso_version: str = AVISO_VERSION   # versión vigente del aviso
    aviso_pendiente: bool = False        # True: la app debe mostrar el aviso y llamar a /auth/aceptar-aviso


class RegistroOut(SesionOut):
    """Respuesta del registro: igual que un login, más el código de recuperación del PIN.
    Es la ÚNICA vez que el servidor lo entrega (después solo existe su hash): la app debe
    mostrarlo en ese momento y no puede volver a pedirlo."""
    codigo_recuperacion: str


ROLES = ("vendedora", "compradora")


class RegistroCompletoIn(RegistroIn):
    """Credenciales + rol. La vendedora manda además el radar completo (la cuenta se crea hasta
    terminarlo); la compradora no pasa por el radar. El rol es obligatorio: no se asume ninguno."""
    rol: str | None = None
    radar: RadarCompletoIn | None = None
    acepta_aviso: bool = False          # casilla "He leído y acepto el Aviso de Privacidad y los Términos"
    es_mayor_de_edad: bool = False      # casilla "Confirmo que soy mayor de 18 años"
    version_aviso: str | None = None    # versión del aviso que la usuaria leyó

    @model_validator(mode="after")
    def _rol_y_radar(self):
        if self.rol not in ROLES:
            raise ValueError("Indica con qué rol te registras: 'vendedora' o 'compradora'")
        if self.rol == "vendedora" and self.radar is None:
            raise ValueError("La vendedora debe completar el radar para terminar su registro")
        if self.rol == "compradora" and self.radar is not None:
            raise ValueError("La compradora no completa el radar")
        return self

    @model_validator(mode="after")
    def _aviso(self):
        if not self.acepta_aviso:
            raise ValueError("Debes aceptar el aviso de privacidad y los términos para crear tu cuenta")
        if not self.es_mayor_de_edad:
            raise ValueError("Debes confirmar que eres mayor de 18 años para crear tu cuenta")
        if self.version_aviso != AVISO_VERSION:
            raise ValueError("El aviso de privacidad cambió. Actualiza la app e inténtalo de nuevo")
        return self


class AceptarAvisoIn(BaseModel):
    version: str
    es_mayor_de_edad: bool = False   # se confirma junto con cada aceptación, incluidas las cuentas anteriores al aviso

    @model_validator(mode="after")
    def _mayor_de_edad(self):
        if not self.es_mayor_de_edad:
            raise ValueError("Debes confirmar que eres mayor de 18 años para continuar")
        return self


class TokenRegistroOut(BaseModel):
    token_registro: str   # pase temporal: solo sirve para el radar y para /auth/registro-completo


# ============================================================ ENDPOINTS

@app.get("/")
def estado():
    return {"ok": True, "servicio": "API Crisálida"}


@app.get("/auth/seudonimo-disponible")
def seudonimo_disponible(seudonimo: str = Query(..., min_length=1, max_length=60)):
    """Para validar el seudónimo mientras la usuaria lo escribe en el registro."""
    seudonimo = seudonimo.strip()
    if not SEUDONIMO_RE.match(seudonimo):
        return {"disponible": False, "motivo": "Usa de 3 a 30 letras, números o guion bajo"}
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM usuarias WHERE lower(seudonimo) = lower(%s)", (seudonimo,))
            existe = cur.fetchone() is not None
    return {"disponible": not existe, "motivo": "Ese seudónimo ya está en uso" if existe else None}


@app.post("/auth/validar-registro", response_model=TokenRegistroOut)
def validar_registro(datos: RegistroIn):
    """Paso 1 del registro (botón "Siguiente"): valida seudónimo y PINs SIN crear la cuenta.
    Devuelve un pase temporal para poder usar el radar mientras todavía no existe la usuaria."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM usuarias WHERE lower(seudonimo) = lower(%s)", (datos.seudonimo,))
            if cur.fetchone() is not None:
                raise HTTPException(status.HTTP_409_CONFLICT, "Ese seudónimo ya está en uso")
    return TokenRegistroOut(token_registro=crear_token_registro(datos.seudonimo))


@app.post("/auth/registro-completo", response_model=RegistroOut, status_code=status.HTTP_201_CREATED)
def registrar_completo(datos: RegistroCompletoIn, response: Response, sesion: dict = Depends(sesion_registro)):
    """Paso final: crea usuaria + mascota (+ perfil del radar, solo la vendedora) en UNA transacción.
    Si algo falla no queda nada a medias. Devuelve también el código de recuperación del PIN,
    que se muestra una sola vez (en la base solo se guarda su hash)."""
    # El pase se emitió para un seudónimo concreto: no se puede usar para registrar otro
    if sesion["id"].lower() != datos.seudonimo.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sesión de registro inválida")

    # Todo lo pesado (hash de PIN) y la validación van ANTES de pedir la conexión
    pin_hash = hashear_pin(datos.pin)
    camuflaje_hash = hashear_pin(datos.pin_camuflaje)
    codigo = generar_codigo_recuperacion()
    codigo_hash = hashear_codigo(codigo)
    radar = datos.radar   # None si es compradora (el modelo ya lo validó)
    if radar is not None:
        respuestas = limpiar_respuestas(radar.respuestas)
        perfil = perfil_desde_cliente(radar.perfil, radar.actividades)

    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO usuarias (seudonimo, pin_hash, pin_camuflaje_hash, rol,
                                          codigo_recuperacion_hash, codigo_recuperacion_creado_en)
                    VALUES (%s, %s, %s, %s, %s, now())
                    RETURNING id, seudonimo, avatar, rol
                    """,
                    (datos.seudonimo, pin_hash, camuflaje_hash, datos.rol, codigo_hash),
                )
                usuaria = cur.fetchone()
                # C1-01: cada usuaria nace con su mascota (relación 1:1)...
                cur.execute("INSERT INTO mascotas (usuaria_id) VALUES (%s)", (usuaria["id"],))
                cur.execute(
                    "INSERT INTO aceptaciones_aviso (usuaria_id, version) VALUES (%s, %s)",
                    (usuaria["id"], datos.version_aviso),
                )
                # ...y la vendedora con su perfil inicial del radar (RF-03), todo en la misma transacción
                if radar is not None:
                    guardar_perfil(cur, usuaria["id"], radar.actividades, radar.tiempo, respuestas, perfil)
            conn.commit()
        except pg_errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Ese seudónimo ya está en uso")
        except Exception:
            conn.rollback()
            raise

    uid = str(usuaria["id"])
    # Esta respuesta lleva el código en claro: que ningún proxy ni navegador la guarde
    response.headers["Cache-Control"] = "no-store"
    return RegistroOut(
        usuaria_id=uid,
        seudonimo=usuaria["seudonimo"],
        avatar=usuaria["avatar"],
        modo="normal",
        token=crear_token(uid, "normal", usuaria["rol"]),
        rol=usuaria["rol"],
        codigo_recuperacion=codigo,
    )


@app.post("/auth/login", response_model=SesionOut)
def iniciar_sesion(datos: LoginIn):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, seudonimo, avatar, rol, estado, version_sesion, pin_hash, pin_camuflaje_hash,
                       bloqueada_hasta, (bloqueada_hasta IS NOT NULL AND bloqueada_hasta > now()) AS bloqueada
                FROM usuarias
                WHERE lower(seudonimo) = lower(%s)
                """,
                (datos.seudonimo.strip(),),
            )
            u = cur.fetchone()

            if u is None:
                verificar_pin(datos.pin, HASH_FALSO)  # mismo tiempo de respuesta que un fallo real
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, MENSAJE_CREDENCIALES)

            if u["bloqueada"]:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Demasiados intentos. Intenta de nuevo en unos minutos",
                )

            if verificar_pin(datos.pin, u["pin_hash"]):
                modo = "normal"
            elif verificar_pin(datos.pin, u["pin_camuflaje_hash"]):
                modo = "camuflaje"
            else:
                # Fallo: se suma el intento y, al llegar al máximo, se bloquea (todo en un solo UPDATE)
                cur.execute(
                    f"""
                    UPDATE usuarias
                    SET intentos_fallidos = CASE WHEN intentos_fallidos + 1 >= %s THEN 0
                                                 ELSE intentos_fallidos + 1 END,
                        bloqueada_hasta   = CASE WHEN intentos_fallidos + 1 >= %s
                                                 THEN now() + interval '{MINUTOS_BLOQUEO} minutes'
                                                 ELSE bloqueada_hasta END
                    WHERE id = %s
                    """,
                    (MAX_INTENTOS, MAX_INTENTOS, u["id"]),
                )
                conn.commit()
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, MENSAJE_CREDENCIALES)

            cur.execute(
                "UPDATE usuarias SET intentos_fallidos = 0, bloqueada_hasta = NULL WHERE id = %s",
                (u["id"],),
            )
            # Solo en modo normal (el camuflaje no muestra nada): ¿ya aceptó la versión vigente del aviso?
            aviso_pendiente = False
            if modo == "normal":
                cur.execute(
                    """SELECT NOT EXISTS (SELECT 1 FROM aceptaciones_aviso
                                           WHERE usuaria_id = %s AND version = %s) AS pendiente""",
                    (u["id"], AVISO_VERSION),
                )
                aviso_pendiente = cur.fetchone()["pendiente"]
        conn.commit()

    uid = str(u["id"])
    return SesionOut(
        usuaria_id=uid,
        seudonimo=u["seudonimo"],
        avatar=u["avatar"],
        modo=modo,
        token=crear_token(uid, modo, u["rol"], u["version_sesion"]),
        rol=u["rol"],
        estado=u["estado"],
        aviso_pendiente=aviso_pendiente,
    )


@app.post("/auth/aceptar-aviso")
def aceptar_aviso(datos: AceptarAvisoIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """La usuaria acepta la versión vigente del aviso (la app lo llama cuando el login dijo
    aviso_pendiente = true) y confirma que es mayor de 18 años. Si manda otra versión se rechaza,
    para no guardar una aceptación vieja. Cada fila de aceptaciones_aviso significa: aceptó esa
    versión Y confirmó ser mayor de edad (el servidor no guarda la fila si falta alguna de las dos)."""
    if datos.version != AVISO_VERSION:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "El aviso de privacidad cambió. Actualiza la app e inténtalo de nuevo")
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO aceptaciones_aviso (usuaria_id, version) VALUES (%s, %s)
                       ON CONFLICT (usuaria_id, version) DO NOTHING""",
                    (usuaria["id"], datos.version),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"aviso_version": AVISO_VERSION, "aceptado": True}


@app.get("/auth/yo")
def mi_sesion(usuaria: dict = Depends(usuaria_actual)):
    """Valida que el token siga vigente (la app lo puede llamar al abrirse)."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT seudonimo, avatar, rol, estado FROM usuarias WHERE id = %s", (usuaria["id"],))
            u = cur.fetchone()
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida o expirada")
    return {"usuaria_id": usuaria["id"], "seudonimo": u["seudonimo"], "avatar": u["avatar"],
            "modo": usuaria["modo"], "rol": u["rol"], "estado": u["estado"]}