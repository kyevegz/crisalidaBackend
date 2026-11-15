-- 011: Idempotencia (issue 5.1)
--
-- Cuando la app reenvía algo que SÍ llegó pero cuya respuesta se perdió, el servidor no debe
-- duplicarlo. El cliente manda un identificador único (encabezado Idempotency-Key). Aquí se guarda
-- ese identificador junto con la respuesta que se dio, en la MISMA transacción que el dato creado.
-- Si llega otra vez, no se vuelve a crear nada (ni flores) y se devuelve la respuesta guardada.
-- Se puede correr varias veces sin problema.

BEGIN;

CREATE TABLE IF NOT EXISTS operaciones_idempotentes (
    usuaria_id  UUID        NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    clave       UUID        NOT NULL,           -- el identificador que genera el cliente
    operacion   VARCHAR(80) NOT NULL,           -- p. ej. 'bienestar_bitacora', 'publicar', 'entregar:<id>'
    respuesta   JSONB,                          -- lo que se le respondió la primera vez
    creada_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (usuaria_id, clave)
);
CREATE INDEX IF NOT EXISTS operaciones_idempotentes_creada_idx ON operaciones_idempotentes (creada_en);

COMMIT;

-- Limpieza opcional (las claves viejas ya no hacen falta; la app reintenta en minutos u horas):
-- DELETE FROM operaciones_idempotentes WHERE creada_en < now() - interval '30 days';