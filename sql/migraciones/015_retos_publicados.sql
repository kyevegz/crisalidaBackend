-- 015 · Retos publicados por usuarias (issue "Retos publicados por usuarias")
-- Se puede correr más de una vez sin problema.
--
-- * retos.contratista_id pasa a ser OPCIONAL: los retos de demo siguen teniendo contratista ficticio, pero los
--   que publica una usuaria (compradora) guardan quién los publicó en retos.publicado_por (columna de la 013).
-- * retos.motivo_rechazo y retos.revisado_en: el equipo revisa cada reto antes de que se vea (estado
--   'en_revision' -> 'abierto' o 'rechazado'). La ruta para aprobar/rechazar llega en un issue posterior;
--   mientras tanto se hace a mano con SQL (ver sql/consultas).
-- * Índice para contar rápido cuántos retos publicó una usuaria en el último día (límite diario).
BEGIN;

ALTER TABLE retos ALTER COLUMN contratista_id DROP NOT NULL;

ALTER TABLE retos ADD COLUMN IF NOT EXISTS motivo_rechazo VARCHAR(300);
ALTER TABLE retos ADD COLUMN IF NOT EXISTS revisado_en    TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS retos_publicado_por_fecha_idx ON retos (publicado_por, creado_en DESC);

COMMIT;