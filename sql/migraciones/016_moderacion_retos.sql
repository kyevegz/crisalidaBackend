-- 016 · Moderación de retos (issue "Revisión y moderación de retos")
-- Se puede correr más de una vez sin problema.
-- Índice para contar rápido los reportes de un reto (se usa para ocultarlo automáticamente cuando junta varios).
-- No hay columnas nuevas: el estado 'en_revision' ya existía (retos), y motivo_rechazo / revisado_en vienen de la 015.
BEGIN;
CREATE INDEX IF NOT EXISTS reportes_reto_fecha_idx ON reportes (reto_id, creado_en) WHERE tipo = 'reto';
COMMIT;