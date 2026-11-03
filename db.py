import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor   # los resultados llegan como diccionarios
from dbutils.pooled_db import PooledDB       # pool de conexiones reutilizables
from dotenv import load_dotenv

load_dotenv()  # lee el archivo .env

pool = PooledDB(
    creator=psycopg2,
    maxconnections=10,
    mincached=1,
    maxcached=5,
    blocking=True,
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT", "5432"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    sslmode="require",            # Neon exige conexión cifrada (TLS)
    cursor_factory=RealDictCursor,
)


@contextmanager
def obtener_conexion():
    """Presta una conexión del pool y la devuelve siempre al terminar."""
    conn = pool.connection()
    try:
        yield conn
    finally:
        conn.close()