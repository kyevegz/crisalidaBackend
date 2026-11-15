-- 018 · Rechazar una entrega de reto (issue "Validar o rechazar una entrega y pagar flores")
-- Cuando la dueña del reto rechaza una entrega, la aceptación vuelve a 'aceptado' (NO a 'rechazado': ese estado
-- soltaría el reto a otra persona por el índice reto_activo_uq). La usuaria puede volver a entregar o abandonar.
-- Aquí se guarda por qué se rechazó y cuántas veces. Se puede correr más de una vez sin problema.
BEGIN;

ALTER TABLE reto_aceptaciones ADD COLUMN IF NOT EXISTS motivo_rechazo VARCHAR(300);
ALTER TABLE reto_aceptaciones ADD COLUMN IF NOT EXISTS rechazado_en   TIMESTAMPTZ;
ALTER TABLE reto_aceptaciones ADD COLUMN IF NOT EXISTS rechazos       SMALLINT NOT NULL DEFAULT 0;

COMMIT;