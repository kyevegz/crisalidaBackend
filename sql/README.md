# Carpeta `sql/`

Aquí viven todos los scripts de la base de datos (Neon, PostgreSQL). Antes solo existían en
la computadora de quien los escribió; ahora quedan versionados con el código.

## Estructura

| Carpeta | Para qué sirve | ¿Se corre en producción? |
|---|---|---|
| `migraciones/` | Crean y cambian la estructura de la BD. Van en orden numérico. | Sí, **una sola vez cada una** |
| `demo/` | Datos de mentira para probar y para la demostración. | Solo en pruebas / demo |
| `pruebas/` | Pruebas automáticas del progreso (flores, niveles). | **No** en la BD real; solo en una copia local |
| `consultas/` | Consultas de solo lectura para revisar cómo está la BD. | Sí, no cambian nada |

## Orden de las migraciones

Córrelas en este orden, completas, en el editor SQL de Neon (o con `psql`):

| # | Archivo | Qué hace |
|---|---|---|
| 001 | `001_base.sql` | Tablas base: usuarias, publicaciones, pedidos, retos, mascotas, bienestar, etc. |
| 002 | `002_niveles_logros_y_triggers.sql` | Niveles, logros, historial y los primeros triggers de progreso |
| 003 | `003_progreso_flores_y_etapas.sql` | Flores, etapas de Lilu, reglas de recompensa y triggers actualizados |
| 004 | `004_bienestar_entradas_e_imagenes_retos.sql` | Varios registros de bienestar al día e imágenes de retos |
| 005 | `005_categorias_nuevas.sql` | Categorías nuevas de productos y servicios (se puede repetir sin problema) |
| 006 | `006_frases_apoyo.sql` |	Tabla de frases de apoyo (Respira con Lilu) con las 25 frases iniciales (se puede repetir sin duplicar) |
| 007 | `007_rol_usuarias.sql` | Columna `rol` de usuarias (`vendedora` o `compradora`); las cuentas existentes quedan como `vendedora` (se puede repetir sin problema)
| 008 | `008_aceptaciones_aviso.sql` | Tabla `aceptaciones_aviso`: fecha y versión del aviso de privacidad que acepta cada usuaria (se puede repetir sin problema) |
| 009 | `009_correo_y_ubicacion.sql` | Columnas correo, correo verificado, municipio y localidad de usuarias, y la tabla `verificaciones_correo` (se puede repetir sin problema) |
| 010 | `010_codigo_recuperacion.sql` | Columnas `codigo_recuperacion_hash` y `codigo_recuperacion_creado_en` de usuarias: solo se guarda el hash del código de recuperación (se puede repetir sin problema) |
| 011 | `011_idempotencia.sql` | Tabla `operaciones_idempotentes`: guarda el identificador único que manda la app y la respuesta, para no duplicar si reenvía (se puede repetir sin problema) |
| 012 | `012_recuperar_pin.sql` | Recuperar el PIN: versión de sesión (un PIN nuevo cierra las sesiones anteriores), contador de intentos de la recuperación y tabla `recuperaciones_pin` con los códigos enviados por correo. **Correr antes de desplegar** (se puede repetir sin problema) |

Notas:
- `002` **no** va dentro de una transacción (no tiene `BEGIN/COMMIT`). Si falla a la mitad, revisa qué alcanzó a crear antes de repetirla.
- Las demás migraciones sí usan transacción: si algo falla, no queda nada a medias.
- Las migraciones nuevas del mantenimiento (rol, correo, frases, etc.) se agregan aquí con el siguiente número: `006_...sql`, `007_...sql`.

## Datos de demo

Correr después de las migraciones 001 a 004, en este orden:

1. `demo/01_datos_demo.sql`: vendedoras ficticias, publicaciones, ventas y retos. Se puede repetir sin duplicar.
2. `demo/02_imagenes_demo.sql`: imágenes de ejemplo (pesa unos 70 KB porque lleva las fotos dentro). Se puede repetir.
3. `demo/comandos_manuales.sql`: comandos **comentados** para simular aprobaciones, ventas y entregas. Cambia `TU_SEUDONIMO` y quita los `--` de lo que quieras usar.

Las vendedoras demo no pueden iniciar sesión. Los datos demo **no se cargan** en una BD con usuarias reales.

## Pruebas

`pruebas/prueba_progreso.sql` crea usuarias de prueba y verifica el trigger de flores y niveles.
Córrelo solo en una base de datos local o de pruebas, **nunca en la de producción**.

## Cómo revisar la BD real

`consultas/estructura_bd.sql` muestra tablas, columnas, triggers y restricciones. Compáralo con
las migraciones para confirmar que lo documentado aquí es lo que realmente hay en Neon.

## Estado en Neon (revisado el 14 de noviembre de 2026)

Se comparó la BD real con las migraciones usando `consultas/estructura_bd.sql`:

- [x] 001 aplicada
- [x] 002 aplicada
- [x] 003 aplicada
- [x] 004 aplicada
- [x] 005 aplicada
- [x] Tablas, columnas, triggers (5) y funciones (5) coinciden con las migraciones. No hay cambios hechos a mano sin documentar.
- Catálogos: `niveles` 10, `reglas_recompensa` 8, `etapas_lilu` 3 y `categorias` 51 (producto 24, reto 10, servicio 17). Las 51 categorías de Neon coinciden con las de los archivos.

Notas:
- `registros_emocionales` es una tabla antigua: el backend ya solo usa `bienestar_entradas`. No se borra todavía; decidirlo en una migración futura.
- `mascotas.ultima_actividad` ya existe, pero solo se actualiza cuando se gana una recompensa (por el trigger), no al iniciar sesión.