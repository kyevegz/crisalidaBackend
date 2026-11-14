-- 007: Rol de la usuaria (issue 2.1)
--
-- Una sola cuenta con un campo de rol: 'vendedora' o 'compradora'. El servidor decide qué
-- puede hacer cada una. Las cuentas que ya existen quedan como 'vendedora'.
-- Es compatible con la versión actual de la app y del backend: un INSERT que no menciona
-- `rol` sigue funcionando (queda 'vendedora'). Se puede correr varias veces sin problema.

BEGIN;

ALTER TABLE usuarias
    ADD COLUMN IF NOT EXISTS rol VARCHAR(12) NOT NULL DEFAULT 'vendedora';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usuarias_rol_ck') THEN
        ALTER TABLE usuarias
            ADD CONSTRAINT usuarias_rol_ck CHECK (rol IN ('vendedora', 'compradora'));
    END IF;
END $$;

COMMIT;

-- Para revisar:  SELECT rol, count(*) FROM usuarias GROUP BY rol;