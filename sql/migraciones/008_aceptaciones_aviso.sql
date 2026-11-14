-- 008: Aceptación del aviso de privacidad y términos (issue 3.9)
--
-- Cada vez que una usuaria acepta una versión del aviso se guarda una fila: así queda la
-- fecha y la versión de cada aceptación, incluso cuando el aviso cambia y vuelve a aceptarlo.
-- La versión vigente se define en la variable de entorno AVISO_VERSION del backend; para pedir
-- que todas acepten de nuevo basta con cambiar ese valor (no hace falta tocar esta tabla).
-- Las cuentas que ya existían no tienen fila: se les pedirá aceptar en su siguiente login.
-- Se puede correr varias veces sin problema.

BEGIN;

CREATE TABLE IF NOT EXISTS aceptaciones_aviso (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuaria_id   UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    version      VARCHAR(20) NOT NULL CHECK (length(btrim(version)) > 0),
    aceptado_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (usuaria_id, version)
);

COMMIT;

-- Para revisar:
--   SELECT u.seudonimo, a.version, a.aceptado_en
--     FROM aceptaciones_aviso a JOIN usuarias u ON u.id = a.usuaria_id ORDER BY a.aceptado_en DESC;