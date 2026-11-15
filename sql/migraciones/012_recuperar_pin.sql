-- 012: Recuperar el PIN (issue 4.6)
--
-- * version_sesion: cada vez que se cambia el PIN por recuperación sube en 1. Los tokens de sesión
--   llevan la versión con la que se emitieron; si no coincide con la de la usuaria, ya no valen
--   (así un PIN nuevo cierra las sesiones anteriores). Las cuentas y tokens existentes quedan en 0.
-- * recuperacion_intentos / recuperacion_bloqueada_hasta: límite de intentos de la recuperación
--   (5 fallos = 15 minutos de bloqueo), independiente del login.
-- * recuperaciones_pin: códigos que se envían por correo. Solo se guarda el hash; vencen.
--
-- IMPORTANTE: correr ANTES de desplegar el backend nuevo (el login y la validación de sesión leen
-- version_sesion). Es compatible con el backend anterior y se puede correr varias veces.

BEGIN;

ALTER TABLE usuarias
    ADD COLUMN IF NOT EXISTS version_sesion               INTEGER     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS recuperacion_intentos        SMALLINT    NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS recuperacion_bloqueada_hasta TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS recuperaciones_pin (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuaria_id   UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    codigo_hash  TEXT NOT NULL,
    intentos     SMALLINT NOT NULL DEFAULT 0,
    usado        BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en    TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS recuperaciones_pin_usuaria_idx
    ON recuperaciones_pin (usuaria_id, creado_en DESC);

COMMIT;