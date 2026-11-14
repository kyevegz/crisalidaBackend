-- 009: Correo, municipio y localidad de la usuaria + códigos de verificación del correo (issue 4.2)
--
-- * El correo es opcional y PRIVADO (ningún endpoint de marketplace o retos lo devuelve).
-- * No se exige que sea único: así nadie puede averiguar si un correo ya tiene cuenta.
-- * Ubicación gruesa (municipio y localidad escritos por la usuaria), nunca GPS.
-- * Los códigos de verificación se guardan solo como hash y vencen (CORREO_CODIGO_MINUTOS).
-- Es compatible con la versión actual de la app y del backend. Se puede correr varias veces.

BEGIN;

ALTER TABLE usuarias
    ADD COLUMN IF NOT EXISTS correo            VARCHAR(254),
    ADD COLUMN IF NOT EXISTS correo_verificado BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS municipio         VARCHAR(80),
    ADD COLUMN IF NOT EXISTS localidad         VARCHAR(80);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usuarias_correo_verificado_ck') THEN
        ALTER TABLE usuarias
            ADD CONSTRAINT usuarias_correo_verificado_ck CHECK (NOT correo_verificado OR correo IS NOT NULL);
    END IF;
END $$;

-- Un código por solicitud (así se puede limitar cuántos se piden). Solo el hash, nunca el código.
CREATE TABLE IF NOT EXISTS verificaciones_correo (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuaria_id   UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    correo       VARCHAR(254) NOT NULL,
    codigo_hash  TEXT NOT NULL,
    intentos     SMALLINT NOT NULL DEFAULT 0,
    usado        BOOLEAN NOT NULL DEFAULT FALSE,
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_en    TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS verificaciones_correo_usuaria_idx
    ON verificaciones_correo (usuaria_id, creado_en DESC);

COMMIT;