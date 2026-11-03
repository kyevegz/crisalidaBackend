"""Publicar productos/servicios, portafolio personal y fotos."""
import os
import re
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator

import radar_logica as rl
from db import obtener_conexion
from dependencias import usuaria_modo_normal
from marketplace import formatear
from seguridad import cifrar_texto, descifrar_texto

router = APIRouter(tags=["Publicaciones"])

# C1-05: toda publicación nueva queda "en_revision" hasta que alguien la apruebe.
# Para la demo puedes poner AUTOAPROBAR_PUBLICACIONES=true en el .env (se aprueban al instante).
AUTOAPROBAR = os.getenv("AUTOAPROBAR_PUBLICACIONES", "false").lower() == "true"

MAX_FOTO_BYTES = 400 * 1024
MAX_FOTOS = 3


def _sin_contacto(valor: str | None, campo: str) -> str | None:
    """Por seguridad de las vendedoras, el texto público no puede traer teléfonos, correos ni ligas."""
    if valor is None:
        return None
    limpio = re.sub(r"\s+", " ", valor).strip()
    if rl.sanitizar_texto(limpio, 10_000) != limpio:
        raise ValueError(f"Por tu seguridad, no pongas teléfonos, correos ni ligas en «{campo}». "
                         "El contacto se hace dentro de la app")
    return limpio or None


class PublicacionIn(BaseModel):
    tipo: Literal["producto", "servicio"]
    categoria: str = Field(min_length=2, max_length=60)          # nombre, como lo muestra la app
    titulo: str = Field(min_length=3, max_length=120)
    descripcion: str = Field(default="", max_length=1000)
    precio: Decimal = Field(gt=0, le=100000, max_digits=10, decimal_places=2)
    nota_precio: str | None = Field(default=None, max_length=40)
    opcion_entrega: int | None = Field(default=None, ge=1, le=3)       # solo productos
    modalidad_servicio: int | None = Field(default=None, ge=1, le=2)   # solo servicios
    esquema_cobro: int | None = Field(default=None, ge=1, le=3)        # solo servicios
    costo_insumos: Decimal | None = Field(default=None, ge=0, le=100000, max_digits=10, decimal_places=2)
    horas_dedicacion: Decimal | None = Field(default=None, gt=0, le=999, max_digits=5, decimal_places=2)
    tiempo_elaboracion_horas: int | None = Field(default=None, ge=0, le=720)
    zona_publica: str | None = Field(default=None, max_length=80)      # lo único que verá el público
    punto_entrega: str | None = Field(default=None, max_length=200)   # dirección real: se guarda CIFRADA

    @field_validator("titulo", "descripcion", "nota_precio", "zona_publica")
    @classmethod
    def _texto_publico(cls, v, info):
        return _sin_contacto(v, info.field_name) if v is not None else v

    @model_validator(mode="after")
    def _segun_tipo(self):
        if self.tipo == "producto":
            if self.opcion_entrega is None:
                raise ValueError("Elige cómo entregarás tu producto")
            self.modalidad_servicio = None
            self.esquema_cobro = None
        else:
            if self.modalidad_servicio is None:
                raise ValueError("Elige dónde das tu servicio")
            if self.esquema_cobro is None:
                raise ValueError("Elige cómo cobras tu servicio")
            self.opcion_entrega = None
        return self


class EstadoIn(BaseModel):
    estado: Literal["activo", "pausado"]


@router.post("/publicaciones", status_code=status.HTTP_201_CREATED)
def publicar(datos: PublicacionIn, usuaria: dict = Depends(usuaria_modo_normal)):
    uid = usuaria["id"]
    estado = "activo" if AUTOAPROBAR else "en_revision"
    punto = cifrar_texto(datos.punto_entrega) if datos.punto_entrega and datos.punto_entrega.strip() else None
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM categorias WHERE ambito = %s AND nombre = %s", (datos.tipo, datos.categoria))
                cat = cur.fetchone()
                if cat is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Esa categoría no existe")
                cur.execute(
                    """INSERT INTO publicaciones
                         (usuaria_id, tipo, categoria_id, titulo, descripcion, precio, nota_precio,
                          opcion_entrega, modalidad_servicio, esquema_cobro, costo_insumos, horas_dedicacion,
                          tiempo_elaboracion_horas, zona_publica, punto_entrega_cifrado, estado)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING id, estado""",
                    (uid, datos.tipo, cat["id"], datos.titulo, datos.descripcion or None, datos.precio,
                     datos.nota_precio, datos.opcion_entrega, datos.modalidad_servicio, datos.esquema_cobro,
                     datos.costo_insumos, datos.horas_dedicacion, datos.tiempo_elaboracion_horas,
                     datos.zona_publica, punto, estado),
                )
                nueva = cur.fetchone()
                # Si se aprobó al instante, el trigger ya pudo dar flores (máx. 1 publicación al día)
                cur.execute("SELECT flores FROM eventos_progreso WHERE tipo = 'publicacion' AND referencia_id = %s",
                            (nueva["id"],))
                ev = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"id": str(nueva["id"]), "estado": nueva["estado"], "flores_ganadas": ev["flores"] if ev else 0}


@router.get("/publicaciones/mias")
def mi_portafolio(usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.tipo, p.titulo, p.descripcion, p.precio, p.nota_precio, p.estado,
                          p.opcion_entrega, p.modalidad_servicio, p.esquema_cobro, p.tiempo_elaboracion_horas,
                          p.zona_publica, p.punto_entrega_cifrado, p.creada_en, p.costo_insumos, p.horas_dedicacion,
                          c.id AS categoria_id, c.nombre AS categoria,
                          (SELECT count(*) FROM pedidos pe WHERE pe.publicacion_id = p.id AND pe.estado = 'completado') AS vendidos,
                          (SELECT count(*) FROM pedidos pe WHERE pe.publicacion_id = p.id
                              AND pe.estado IN ('pendiente', 'en_custodia', 'entregado')) AS pedidos_pendientes,
                          (SELECT round(avg(pe.calificacion)::numeric, 1) FROM pedidos pe
                            WHERE pe.publicacion_id = p.id AND pe.estado = 'completado') AS calificacion,
                          (SELECT json_agg(i.id ORDER BY i.orden) FROM publicacion_imagenes i WHERE i.publicacion_id = p.id) AS imagenes
                     FROM publicaciones p JOIN categorias c ON c.id = p.categoria_id
                    WHERE p.usuaria_id = %s
                    ORDER BY p.creada_en DESC""",
                (usuaria["id"],),
            )
            filas = cur.fetchall()
    salida = []
    for r in filas:
        d = formatear({**r, "es_mia": True, "vendedora": None, "vendedora_avatar": None})
        d["pedidos_pendientes"] = int(r["pedidos_pendientes"])
        d["estado"] = r["estado"]
        d["costo_insumos"] = float(r["costo_insumos"]) if r["costo_insumos"] is not None else None
        d["horas_dedicacion"] = float(r["horas_dedicacion"]) if r["horas_dedicacion"] is not None else None
        try:
            d["punto_entrega"] = descifrar_texto(r["punto_entrega_cifrado"]) if r["punto_entrega_cifrado"] else None
        except Exception:
            d["punto_entrega"] = None
        salida.append(d)
    return {"publicaciones": salida}


@router.put("/publicaciones/{publicacion_id}")
def editar(publicacion_id: str, datos: PublicacionIn, usuaria: dict = Depends(usuaria_modo_normal)):
    """Edita los detalles de una publicación propia. El tipo (producto/servicio) no se puede cambiar.
    Si estaba activa y no es modo demo, vuelve a revisión porque el contenido cambió."""
    punto = cifrar_texto(datos.punto_entrega) if datos.punto_entrega and datos.punto_entrega.strip() else None
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, tipo, estado FROM publicaciones WHERE id::text = %s AND usuaria_id = %s FOR UPDATE",
                            (publicacion_id, usuaria["id"]))
                actual = cur.fetchone()
                if actual is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Publicación no encontrada")
                if actual["tipo"] != datos.tipo:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        "No se puede cambiar de producto a servicio. Crea una publicación nueva")
                cur.execute("SELECT id FROM categorias WHERE ambito = %s AND nombre = %s", (datos.tipo, datos.categoria))
                cat = cur.fetchone()
                if cat is None:
                    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Esa categoría no existe")
                nuevo_estado = actual["estado"]
                if nuevo_estado == "activo" and not AUTOAPROBAR:
                    nuevo_estado = "en_revision"
                cur.execute(
                    """UPDATE publicaciones SET categoria_id=%s, titulo=%s, descripcion=%s, precio=%s, nota_precio=%s,
                              opcion_entrega=%s, modalidad_servicio=%s, esquema_cobro=%s, costo_insumos=%s,
                              horas_dedicacion=%s, tiempo_elaboracion_horas=%s, zona_publica=%s,
                              punto_entrega_cifrado=%s, estado=%s
                        WHERE id = %s RETURNING id, estado""",
                    (cat["id"], datos.titulo, datos.descripcion or None, datos.precio, datos.nota_precio,
                     datos.opcion_entrega, datos.modalidad_servicio, datos.esquema_cobro, datos.costo_insumos,
                     datos.horas_dedicacion, datos.tiempo_elaboracion_horas, datos.zona_publica, punto,
                     nuevo_estado, actual["id"]),
                )
                r = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"id": str(r["id"]), "estado": r["estado"], "reenviada_a_revision": r["estado"] != actual["estado"]}


@router.delete("/publicaciones/{publicacion_id}/imagenes/{imagen_id}")
def borrar_imagen(publicacion_id: str, imagen_id: str, usuaria: dict = Depends(usuaria_modo_normal)):
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM publicacion_imagenes i USING publicaciones p
                        WHERE i.id::text = %s AND i.publicacion_id::text = %s
                          AND p.id = i.publicacion_id AND p.usuaria_id = %s RETURNING i.id""",
                    (imagen_id, publicacion_id, usuaria["id"]))
                ok = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if ok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Foto no encontrada")
    return {"borrada": True}


@router.patch("/publicaciones/{publicacion_id}/estado")
def pausar_o_reactivar(publicacion_id: str, datos: EstadoIn, usuaria: dict = Depends(usuaria_modo_normal)):
    origen = "pausado" if datos.estado == "activo" else "activo"
    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE publicaciones SET estado = %s WHERE id::text = %s AND usuaria_id = %s AND estado = %s RETURNING id",
                    (datos.estado, publicacion_id, usuaria["id"], origen),
                )
                ok = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if ok is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No se pudo cambiar el estado de esa publicación")
    return {"estado": datos.estado}


# ------------------------------------------------------------------ FOTOS

def _tipo_imagen(b: bytes) -> str | None:
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/publicaciones/{publicacion_id}/imagenes", status_code=status.HTTP_201_CREATED)
async def subir_imagen(publicacion_id: str, request: Request, usuaria: dict = Depends(usuaria_modo_normal)):
    """El cuerpo de la petición ES la imagen (JPEG/PNG/WebP, máx. 400 KB; la app la comprime antes)."""
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > MAX_FOTO_BYTES:
        raise HTTPException(413, "La foto pesa demasiado (máx. 400 KB)")
    datos = await request.body()
    if len(datos) > MAX_FOTO_BYTES:
        raise HTTPException(413, "La foto pesa demasiado (máx. 400 KB)")
    mime = _tipo_imagen(datos)
    if mime is None or len(datos) < 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Sube una foto JPEG, PNG o WebP")

    with obtener_conexion() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM publicaciones WHERE id::text = %s AND usuaria_id = %s FOR UPDATE",
                            (publicacion_id, usuaria["id"]))
                pub = cur.fetchone()
                if pub is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Publicación no encontrada")
                cur.execute("SELECT orden FROM publicacion_imagenes WHERE publicacion_id = %s", (pub["id"],))
                usados = {r["orden"] for r in cur.fetchall()}
                libre = next((o for o in range(1, MAX_FOTOS + 1) if o not in usados), None)
                if libre is None:
                    raise HTTPException(status.HTTP_409_CONFLICT, f"Máximo {MAX_FOTOS} fotos por publicación")
                cur.execute(
                    "INSERT INTO publicacion_imagenes (publicacion_id, orden, mime, datos) VALUES (%s, %s, %s, %s) RETURNING id",
                    (pub["id"], libre, mime, datos),
                )
                img = cur.fetchone()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"id": str(img["id"]), "orden": libre, "url": f"/imagenes/{img['id']}"}


@router.get("/imagenes/{imagen_id}")
def ver_imagen(imagen_id: str):
    """Pública a propósito: el id es un UUID imposible de adivinar y así la app puede cargarla
    con un cargador de imágenes normal (sin encabezados). Las fotos de productos no son datos sensibles."""
    with obtener_conexion() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT mime, datos FROM publicacion_imagenes WHERE id::text = %s", (imagen_id,))
            r = cur.fetchone()
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Imagen no encontrada")
    return Response(content=bytes(r["datos"]), media_type=r["mime"],
                    headers={"Cache-Control": "public, max-age=86400"})
