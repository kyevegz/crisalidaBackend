-- 014: Estado de la cuenta: activa o suspendida (issue 6.1)
--
-- Una cuenta suspendida está «en reposo»: sus productos, servicios y retos dejan de verse en el
-- marketplace y en el tablero, pero ella puede seguir entrando y usando la mascota y el bienestar.
-- Se reactiva con POST /cuenta/reactivar y todo vuelve a verse. No se borra nada al suspender.
-- Todas las cuentas existentes quedan 'activa'. Se puede correr varias veces sin problema.

BEGIN;

ALTER TABLE usuarias
    ADD COLUMN IF NOT EXISTS estado        VARCHAR(12) NOT NULL DEFAULT 'activa',
    ADD COLUMN IF NOT EXISTS suspendida_en TIMESTAMPTZ;      -- desde cuándo está suspendida (NULL si está activa)

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usuarias_estado_ck') THEN
        ALTER TABLE usuarias ADD CONSTRAINT usuarias_estado_ck CHECK (estado IN ('activa', 'suspendida'));
    END IF;
END $$;

COMMIT;

-- Para revisar:
--   SELECT seudonimo, estado, suspendida_en FROM usuarias WHERE estado = 'suspendida';