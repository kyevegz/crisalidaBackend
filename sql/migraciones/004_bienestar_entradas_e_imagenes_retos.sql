-- =====================================================================
--  Migración 05: bienestar con VARIOS registros al día + imágenes de retos
--  Se corre UNA vez, después de la 02. Va en una transacción.
-- =====================================================================
BEGIN;

-- ---------------------------------------------------------------------
-- 1. Cada registro de bienestar es una fila propia (se puede registrar a cualquier hora,
--    todas las veces que se quiera). Las FLORES siguen dándose una vez al día por bloque
--    (eso lo controla eventos_progreso, no esta tabla).
-- ---------------------------------------------------------------------
CREATE TABLE bienestar_entradas (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuaria_id     UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    subtipo        VARCHAR(20) NOT NULL CHECK (subtipo IN ('emocion', 'monitoreo', 'reflexion', 'bitacora')),
    emocion        VARCHAR(30),
    tension        SMALLINT CHECK (tension  BETWEEN 1 AND 5),
    claridad       SMALLINT CHECK (claridad BETWEEN 1 AND 5),
    energia        SMALLINT CHECK (energia  BETWEEN 1 AND 5),
    texto_cifrado  TEXT,        -- reflexiones (lista en JSON) o bitácora: siempre cifrado (AES-256-GCM)
    dia            DATE NOT NULL DEFAULT ((now() AT TIME ZONE 'America/Mexico_City')::date),
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
         (subtipo = 'emocion'   AND emocion IS NOT NULL)
      OR (subtipo = 'monitoreo' AND tension IS NOT NULL AND claridad IS NOT NULL AND energia IS NOT NULL)
      OR (subtipo IN ('reflexion', 'bitacora') AND texto_cifrado IS NOT NULL)
    )
);
CREATE INDEX bienestar_entradas_idx ON bienestar_entradas (usuaria_id, subtipo, creado_en DESC);

-- Lo que ya hubiera en la tabla anterior (registros_emocionales) se conserva como entradas
INSERT INTO bienestar_entradas (usuaria_id, subtipo, emocion, dia, creado_en)
    SELECT usuaria_id, 'emocion', emocion, dia, creado_en FROM registros_emocionales WHERE emocion IS NOT NULL;
INSERT INTO bienestar_entradas (usuaria_id, subtipo, tension, claridad, energia, dia, creado_en)
    SELECT usuaria_id, 'monitoreo', tension, claridad, energia, dia, creado_en FROM registros_emocionales
     WHERE tension IS NOT NULL AND claridad IS NOT NULL AND energia IS NOT NULL;
INSERT INTO bienestar_entradas (usuaria_id, subtipo, texto_cifrado, dia, creado_en)
    SELECT usuaria_id, 'reflexion', reflexiones_cifrado, dia, creado_en FROM registros_emocionales WHERE reflexiones_cifrado IS NOT NULL;
INSERT INTO bienestar_entradas (usuaria_id, subtipo, texto_cifrado, dia, creado_en)
    SELECT usuaria_id, 'bitacora', bitacora_cifrada, dia, creado_en FROM registros_emocionales WHERE bitacora_cifrada IS NOT NULL;

-- ---------------------------------------------------------------------
-- 2. Foto de cada microrreto (la sube el contratista; en la demo se cargan de prueba)
-- ---------------------------------------------------------------------
CREATE TABLE reto_imagenes (
    reto_id    UUID PRIMARY KEY REFERENCES retos(id) ON DELETE CASCADE,
    mime       VARCHAR(20) NOT NULL CHECK (mime IN ('image/jpeg', 'image/png', 'image/webp')),
    datos      BYTEA NOT NULL CHECK (octet_length(datos) BETWEEN 100 AND 409600),
    creada_en  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
