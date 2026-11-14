-- 010: Código de recuperación del PIN (issue 4.4)
--
-- Al registrarse, el servidor genera un código aleatorio y lo muestra UNA sola vez en la respuesta
-- del registro. Aquí solo se guarda su hash (nunca el código), así que nadie puede consultarlo
-- después: ni la usuaria, ni el equipo, ni quien llegara a ver la base.
-- Las cuentas anteriores a esta migración quedan sin código (columnas en NULL).
-- Se puede correr varias veces sin problema.

BEGIN;

ALTER TABLE usuarias
    ADD COLUMN IF NOT EXISTS codigo_recuperacion_hash      TEXT,
    ADD COLUMN IF NOT EXISTS codigo_recuperacion_creado_en TIMESTAMPTZ;

COMMIT;

-- Para revisar (el hash no revela el código):
--   SELECT seudonimo, codigo_recuperacion_hash IS NOT NULL AS tiene_codigo, codigo_recuperacion_creado_en
--     FROM usuarias ORDER BY creado_en DESC LIMIT 5;