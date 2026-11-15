-- 013: Reportes y bloqueos (issue 4.8)
--
-- * reportes: cada reporte de una publicación, un reto o una usuaria. Se guarda siempre (aunque el
--   correo al equipo no salga). Quien reportó NO se muestra a la persona reportada.
--     - tipo 'publicacion': reporta la oferta (guarda también a su dueña, para el equipo).
--     - tipo 'reto':        reporta un microrreto (lo publica una compradora; ver retos.publicado_por).
--     - tipo 'usuaria':     reporta a la persona (la app la identifica por una publicación suya).
--   Un mismo reporte no se puede repetir: una sola vez por persona y objetivo (índices únicos).
-- * bloqueos: una usuaria bloquea a otra; lo bloqueado deja de aparecerle (y a la inversa).
--   Tiene su propio id para que la app pueda desbloquear sin conocer ids de otras usuarias.
-- * retos.publicado_por: la cuenta (compradora) que publicó el reto. Sirve para reportarla y bloquearla desde
--   un reto y para ocultar sus retos a quien la bloqueó. Los retos de demo (contratistas ficticios, sin
--   cuenta) la dejan vacía; el issue de publicar retos la llenará.
-- Se puede correr varias veces sin problema.

BEGIN;

ALTER TABLE retos
    ADD COLUMN IF NOT EXISTS publicado_por UUID REFERENCES usuarias(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS retos_publicado_por_idx ON retos (publicado_por);

CREATE TABLE IF NOT EXISTS reportes (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reportante_id         UUID REFERENCES usuarias(id) ON DELETE SET NULL,
    tipo                  VARCHAR(12) NOT NULL CHECK (tipo IN ('publicacion', 'reto', 'usuaria')),
    publicacion_id        UUID REFERENCES publicaciones(id) ON DELETE SET NULL,
    reto_id               UUID REFERENCES retos(id) ON DELETE SET NULL,
    usuaria_reportada_id  UUID REFERENCES usuarias(id) ON DELETE SET NULL,
    objetivo_titulo       VARCHAR(200),          -- título/nombre al momento del reporte (por si luego se borra)
    motivo                VARCHAR(30) NOT NULL
                          CHECK (motivo IN ('acoso', 'entrega_insegura', 'cobro_indebido', 'otro', 'contacto_externo')),
    detalle               VARCHAR(500),
    prioridad             VARCHAR(8) NOT NULL DEFAULT 'normal' CHECK (prioridad IN ('normal', 'alta')),
    estado                VARCHAR(12) NOT NULL DEFAULT 'nuevo'
                          CHECK (estado IN ('nuevo', 'en_revision', 'resuelto', 'descartado')),
    bloqueo_solicitado    BOOLEAN NOT NULL DEFAULT FALSE,
    correo_enviado_en     TIMESTAMPTZ,           -- NULL = el correo al equipo aún no salió (se puede reenviar a mano)
    creado_en             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS reportes_publicacion_uq
    ON reportes (reportante_id, publicacion_id) WHERE tipo = 'publicacion';
CREATE UNIQUE INDEX IF NOT EXISTS reportes_reto_uq
    ON reportes (reportante_id, reto_id) WHERE tipo = 'reto';
CREATE UNIQUE INDEX IF NOT EXISTS reportes_usuaria_uq
    ON reportes (reportante_id, usuaria_reportada_id) WHERE tipo = 'usuaria';
CREATE INDEX IF NOT EXISTS reportes_estado_idx ON reportes (estado, prioridad, creado_en DESC);

CREATE TABLE IF NOT EXISTS bloqueos (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuaria_id    UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,   -- quien bloquea
    bloqueada_id  UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,   -- a quien bloquea
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usuaria_id, bloqueada_id),
    CHECK (usuaria_id <> bloqueada_id)
);
CREATE INDEX IF NOT EXISTS bloqueos_bloqueada_idx ON bloqueos (bloqueada_id);

COMMIT;

-- Para el equipo (revisar reportes pendientes, los de prioridad alta primero):
--   SELECT id, creado_en, tipo, motivo, prioridad, estado, objetivo_titulo, correo_enviado_en
--     FROM reportes WHERE estado IN ('nuevo', 'en_revision')
--    ORDER BY (prioridad = 'alta') DESC, creado_en;
-- Marcar como atendido:  UPDATE reportes SET estado = 'resuelto' WHERE id = 123;