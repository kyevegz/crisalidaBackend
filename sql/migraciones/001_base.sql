BEGIN;

-- ---------- CUENTAS ----------------------------------------

CREATE TABLE usuarias (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seudonimo           VARCHAR(30) NOT NULL,
    pin_hash            TEXT NOT NULL,            -- NUNCA el PIN en claro: bcrypt/argon2
    pin_camuflaje_hash  TEXT NOT NULL,            -- PIN alterno (galería de mariposas)
    avatar              VARCHAR(8) NOT NULL DEFAULT '🐱',
    intentos_fallidos   SMALLINT NOT NULL DEFAULT 0,   -- un PIN de 6 dígitos se adivina
    bloqueada_hasta     TIMESTAMPTZ,                   -- fácil sin bloqueo temporal
    creada_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX usuarias_seudonimo_uq ON usuarias (lower(seudonimo));

-- Contratistas y compradores ("usuarios externos"). Sin login por ahora.
CREATE TABLE externos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre_publico  VARCHAR(60) NOT NULL,
    tipo            VARCHAR(12) NOT NULL CHECK (tipo IN ('contratista', 'comprador', 'ambos')),
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- CATEGORÍAS (filtros de Marketplace y Retos) ------

CREATE TABLE categorias (
    id      SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ambito  VARCHAR(10) NOT NULL CHECK (ambito IN ('producto', 'servicio', 'reto')),
    nombre  VARCHAR(60) NOT NULL,
    UNIQUE (ambito, nombre)
);

-- ---------- MARKETPLACE ------------------------------------
-- Productos y servicios en UNA sola tabla (columna "tipo").
-- El portafolio de cada usuaria es simplemente: publicaciones WHERE usuaria_id = ...

CREATE TABLE publicaciones (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuaria_id                UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    tipo                      VARCHAR(10) NOT NULL CHECK (tipo IN ('producto', 'servicio')),
    categoria_id              SMALLINT NOT NULL REFERENCES categorias(id),
    titulo                    VARCHAR(120) NOT NULL,
    descripcion               TEXT,
    precio                    NUMERIC(10,2) NOT NULL CHECK (precio >= 0),
    nota_precio               VARCHAR(40),        -- 'Por sesión', 'c/litro', ...
    opcion_entrega            SMALLINT NOT NULL CHECK (opcion_entrega IN (1, 2, 3)),
                                                  -- 1 domicilio · 2 guía ciega · 3 encargo previo
    punto_entrega_cifrado     TEXT,               -- ubicación = dato sensible
    tiempo_elaboracion_horas  SMALLINT,
    imagen_url                TEXT,               -- archivo en el bucket S3 de Neon
    estado                    VARCHAR(12) NOT NULL DEFAULT 'en_revision'
                              CHECK (estado IN ('en_revision', 'activo', 'pausado', 'rechazado')),
                                                  -- en_revision: regla C1-05
    creada_en                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX publicaciones_catalogo_idx ON publicaciones (categoria_id) WHERE estado = 'activo';
CREATE INDEX publicaciones_usuaria_idx  ON publicaciones (usuaria_id);

CREATE TABLE pedidos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publicacion_id  UUID NOT NULL REFERENCES publicaciones(id),
    comprador_id    UUID NOT NULL REFERENCES externos(id),
    monto           NUMERIC(10,2) NOT NULL CHECK (monto >= 0),
    estado          VARCHAR(12) NOT NULL DEFAULT 'pendiente'
                    CHECK (estado IN ('pendiente', 'en_custodia', 'entregado', 'completado', 'cancelado')),
    calificacion    SMALLINT CHECK (calificacion BETWEEN 1 AND 5),
    comentario      TEXT,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completado_en   TIMESTAMPTZ
);
CREATE INDEX pedidos_publicacion_idx ON pedidos (publicacion_id);

-- ---------- MICRORRETOS ------------------------------------

CREATE TABLE retos (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contratista_id       UUID NOT NULL REFERENCES externos(id),
    categoria_id         SMALLINT NOT NULL REFERENCES categorias(id),
    titulo               VARCHAR(120) NOT NULL,
    descripcion          TEXT NOT NULL,
    compensacion         NUMERIC(10,2) NOT NULL CHECK (compensacion >= 0),
    duracion_min         SMALLINT NOT NULL CHECK (duracion_min > 0),
    dificultad           VARCHAR(8) NOT NULL CHECK (dificultad IN ('facil', 'media', 'dificil')),
    habilidad_requerida  VARCHAR(80),
    etiqueta             VARCHAR(30),             -- 'TICS', 'Redacción', 'Cocina'
    imagen_url           TEXT,
    fecha_limite         TIMESTAMPTZ NOT NULL,    -- RF-06: tiempo límite
    estado               VARCHAR(12) NOT NULL DEFAULT 'en_revision'
                         CHECK (estado IN ('en_revision', 'abierto', 'asignado', 'completado', 'cancelado', 'rechazado')),
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX retos_tablero_idx ON retos (categoria_id) WHERE estado = 'abierto';

-- Una usuaria acepta un reto; el reto se completa cuando el contratista valida (C1-02)
CREATE TABLE reto_aceptaciones (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reto_id       UUID NOT NULL REFERENCES retos(id),
    usuaria_id    UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    estado        VARCHAR(12) NOT NULL DEFAULT 'aceptado'
                  CHECK (estado IN ('aceptado', 'entregado', 'validado', 'rechazado', 'abandonado')),
    aceptado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    entregado_en  TIMESTAMPTZ,
    validado_en   TIMESTAMPTZ
);
-- Un reto solo puede estar "tomado" por una usuaria a la vez
CREATE UNIQUE INDEX reto_activo_uq ON reto_aceptaciones (reto_id)
    WHERE estado IN ('aceptado', 'entregado', 'validado');

-- ---------- BIENESTAR EMOCIONAL ----------------------------

CREATE TABLE registros_emocionales (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuaria_id           UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    emocion              VARCHAR(30) NOT NULL,
    tension              SMALLINT CHECK (tension  BETWEEN 1 AND 5),
    claridad             SMALLINT CHECK (claridad BETWEEN 1 AND 5),
    energia              SMALLINT CHECK (energia  BETWEEN 1 AND 5),
    reflexiones_cifrado  TEXT,                    -- respuestas a las 4 preguntas
    bitacora_cifrada     TEXT,                    -- nota privada (dato sensible)
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX registros_usuaria_idx ON registros_emocionales (usuaria_id, creado_en DESC);

-- ---------- MASCOTA, NIVELES Y LOGROS ----------------------

CREATE TABLE mascotas (                           -- relación 1:1 con la usuaria
    usuaria_id        UUID PRIMARY KEY REFERENCES usuarias(id) ON DELETE CASCADE,
    nombre            VARCHAR(30) NOT NULL DEFAULT 'Lilu',
    semillas          INTEGER NOT NULL DEFAULT 0 CHECK (semillas >= 0),  -- RN-01: nunca baja
    nivel             SMALLINT NOT NULL DEFAULT 1,
    ultima_actividad  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Historial: cada venta, reto o registro emocional que alimenta a Lilu (RF-08, RF-09)
CREATE TABLE eventos_progreso (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    usuaria_id     UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    tipo           VARCHAR(10) NOT NULL CHECK (tipo IN ('venta', 'reto', 'bienestar')),
    referencia_id  UUID,                          -- pedido, reto_aceptacion o registro
    semillas       SMALLINT NOT NULL CHECK (semillas > 0),
    creado_en      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX eventos_usuaria_idx ON eventos_progreso (usuaria_id, creado_en DESC);

-- ---------- PERFILADO (cuestionario + IA) ------------------

CREATE TABLE perfilado (
    usuaria_id          UUID PRIMARY KEY REFERENCES usuarias(id) ON DELETE CASCADE,
    respuestas          JSONB NOT NULL,
    areas_fuertes       JSONB,
    areas_oportunidad   JSONB,
    nivel_inicial       SMALLINT NOT NULL DEFAULT 1,   -- C1-01: automático
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE habilidades_usuaria (                -- las "insignias" del perfil
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    usuaria_id  UUID NOT NULL REFERENCES usuarias(id) ON DELETE CASCADE,
    titulo      VARCHAR(80) NOT NULL,
    descripcion TEXT,
    categoria   VARCHAR(40),
    creada_en   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- DATOS INICIALES: categorías ---------------------

INSERT INTO categorias (ambito, nombre) VALUES
    ('producto', 'Manualidades y Regalos'),
    ('producto', 'Bisutería y Accesorios'),
    ('producto', 'Belleza y Cosmética Natural'),
    ('producto', 'Jardinería y Plantas'),
    ('producto', 'Papelería y Cuadernos Artesanales'),
    ('producto', 'Juguetes y Muñecos Hechos a Mano'),
    ('producto', 'Velas y Aromaterapia'),
    ('producto', 'Panadería y Galletas'),
    ('producto', 'Conservas y Salsas'),
    ('producto', 'Bordados y Tejidos'),

    ('servicio', 'Cuidado de Mascotas'),
    ('servicio', 'Organización de Eventos'),
    ('servicio', 'Cuidado Infantil'),
    ('servicio', 'Cuidado de Adultos Mayores'),
    ('servicio', 'Fotografía y Edición'),
    ('servicio', 'Diseño Gráfico Básico'),
    ('servicio', 'Corte y Confección'),
    ('servicio', 'Limpieza y Mantenimiento'),
    ('servicio', 'Clases y Tutorías'),
    ('servicio', 'Traducción y Transcripción'),

    ('reto', 'Organización y datos'),
    ('reto', 'Redacción y textos'),
    ('reto', 'Cocina y repostería'),
    ('reto', 'Costura y confección'),
    ('reto', 'Cuidado personal y cosmética natural'),
    ('reto', 'Digitalización y apoyo administrativo'),
    ('reto', 'Oficios y reparaciones del hogar'),
    ('reto', 'Educación y asesorías'),
    ('reto', 'Cuidado y asistencia'),
    ('reto', 'Eventos y banquetes');

COMMIT;
