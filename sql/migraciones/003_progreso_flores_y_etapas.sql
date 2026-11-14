-- =====================================================================
--  Migración 02: flores, etapas de Lilu y progreso con UN solo contador
--  Se ejecuta UNA vez, DESPUÉS de los scripts anteriores (ya corridos).
--  Va dentro de una transacción: si algo falla, no queda nada a medias.
-- =====================================================================
BEGIN;

-- ---------------------------------------------------------------------
-- 1. "flores" en lugar de "semillas"
-- ---------------------------------------------------------------------
-- (si la columna ya se llama "flores", no hace nada)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'mascotas' AND column_name = 'semillas') THEN
        ALTER TABLE mascotas RENAME COLUMN semillas TO flores;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'eventos_progreso' AND column_name = 'semillas') THEN
        ALTER TABLE eventos_progreso RENAME COLUMN semillas TO flores;
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 2. eventos_progreso: nuevos tipos, subtipo y día
--    (tipo era VARCHAR(10): 'publicacion' mide 11 y no cabía)
-- ---------------------------------------------------------------------
ALTER TABLE eventos_progreso ALTER COLUMN tipo TYPE VARCHAR(20);

ALTER TABLE eventos_progreso DROP CONSTRAINT eventos_progreso_tipo_check;
ALTER TABLE eventos_progreso ADD CONSTRAINT eventos_progreso_tipo_check
    CHECK (tipo IN ('venta', 'reto', 'bienestar', 'publicacion', 'nivel'));

-- 'emocion' | 'monitoreo' | 'reflexion' | 'bitacora'  (solo para tipo = 'bienestar')
ALTER TABLE eventos_progreso ADD COLUMN subtipo VARCHAR(20);
-- Eventos de bienestar que ya existieran: se reparten en los 4 tipos para no chocar con el tope diario
UPDATE eventos_progreso e
   SET subtipo = (ARRAY['emocion', 'monitoreo', 'reflexion', 'bitacora'])[LEAST(r.n, 4)]
  FROM (SELECT id, row_number() OVER (
                 PARTITION BY usuaria_id, (creado_en AT TIME ZONE 'America/Mexico_City')::date ORDER BY id) AS n
          FROM eventos_progreso WHERE tipo = 'bienestar') r
 WHERE e.id = r.id;
ALTER TABLE eventos_progreso ADD CONSTRAINT eventos_bienestar_subtipo_ck
    CHECK (tipo <> 'bienestar' OR subtipo IN ('emocion', 'monitoreo', 'reflexion', 'bitacora'));

-- Día (hora de México) en que ocurrió el evento: sirve para los topes diarios
ALTER TABLE eventos_progreso ADD COLUMN dia DATE;
UPDATE eventos_progreso SET dia = (creado_en AT TIME ZONE 'America/Mexico_City')::date;
ALTER TABLE eventos_progreso ALTER COLUMN dia SET NOT NULL;
ALTER TABLE eventos_progreso ALTER COLUMN dia SET DEFAULT ((now() AT TIME ZONE 'America/Mexico_City')::date);

-- Topes anti-"cultivo de flores":
--   * cada bloque de bienestar da flores UNA vez por día
--   * publicar da flores UNA vez por día (y nunca dos veces por la misma publicación)
CREATE UNIQUE INDEX eventos_bienestar_dia_uq
    ON eventos_progreso (usuaria_id, subtipo, dia) WHERE tipo = 'bienestar';
CREATE UNIQUE INDEX eventos_publicacion_dia_uq
    ON eventos_progreso (usuaria_id, dia) WHERE tipo = 'publicacion';

-- ---------------------------------------------------------------------
-- 3. Cuántas flores da cada cosa (se cambian con un UPDATE, sin tocar código)
-- ---------------------------------------------------------------------
CREATE TABLE reglas_recompensa (
    clave        VARCHAR(30) PRIMARY KEY,
    flores       SMALLINT NOT NULL CHECK (flores > 0),
    descripcion  TEXT
);

INSERT INTO reglas_recompensa (clave, flores, descripcion) VALUES
    ('venta',               30, 'Venta completada'),
    ('reto',                30, 'Microrreto validado'),
    ('publicacion',         20, 'Publicación aprobada (máx. 1 por día)'),
    ('nivel',               25, 'Por cada nivel que sube la usuaria'),
    ('bienestar_emocion',    5, 'Registrar cómo se siente (1 vez al día)'),
    ('bienestar_monitoreo',  3, 'Monitoreo corporal y emocional (1 vez al día)'),
    ('bienestar_reflexion',  8, 'Preguntas de acompañamiento (1 vez al día)'),
    ('bienestar_bitacora',  12, 'Bitácora confidencial (1 vez al día)');

-- ---------------------------------------------------------------------
-- 4. Etapas de Lilu (Huevo → Larva → Mariposa): dependen de las FLORES
--    El nivel de la usuaria (Semilla...Mujer Extraordinaria) depende de las ACTIVIDADES
-- ---------------------------------------------------------------------
CREATE TABLE etapas_lilu (
    etapa             SMALLINT PRIMARY KEY,
    nombre            VARCHAR(20) NOT NULL UNIQUE,
    flores_requeridas INTEGER NOT NULL UNIQUE CHECK (flores_requeridas >= 0)
);

INSERT INTO etapas_lilu (etapa, nombre, flores_requeridas) VALUES
    (1, 'Huevo',     0),
    (2, 'Larva',   150),
    (3, 'Mariposa', 500);

-- ---------------------------------------------------------------------
-- 5. UN solo lugar que cuenta: el trigger de eventos_progreso.
--    Todo lo demás solo INSERTA un evento; aquí se suman flores, actividades y nivel.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION actualizar_progreso_mascota()
RETURNS TRIGGER AS $$
DECLARE
    v_actividades INTEGER;
    v_nivel_ant   SMALLINT;
    v_nivel_nuevo SMALLINT;
    v_bono        SMALLINT;
BEGIN
    SELECT m.actividades_completadas, m.nivel
      INTO v_actividades, v_nivel_ant
      FROM mascotas m
     WHERE m.usuaria_id = NEW.usuaria_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RETURN NEW;
    END IF;

    v_nivel_nuevo := v_nivel_ant;

    -- Solo ventas y retos verificados cuentan para el nivel
    IF NEW.cuenta_para_nivel AND NEW.tipo IN ('venta', 'reto') THEN
        v_actividades := v_actividades + 1;
        SELECT n.nivel INTO v_nivel_nuevo
          FROM niveles n
         WHERE n.actividades_requeridas <= v_actividades
         ORDER BY n.actividades_requeridas DESC
         LIMIT 1;
    END IF;

    UPDATE mascotas
       SET flores                  = flores + NEW.flores,
           actividades_completadas = v_actividades,
           nivel                   = v_nivel_nuevo,
           ultima_actividad        = NEW.creado_en
     WHERE usuaria_id = NEW.usuaria_id;

    -- Bono por subir de nivel (25 flores por nivel). Es otro evento: vuelve a pasar
    -- por este trigger, pero como es tipo 'nivel' solo suma flores (no se cicla).
    IF v_nivel_nuevo > v_nivel_ant THEN
        SELECT flores INTO v_bono FROM reglas_recompensa WHERE clave = 'nivel';
        INSERT INTO eventos_progreso (usuaria_id, tipo, flores, cuenta_para_nivel)
        VALUES (NEW.usuaria_id, 'nivel', v_bono * (v_nivel_nuevo - v_nivel_ant), FALSE);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- (el trigger trg_actualizar_progreso_mascota ya existe y usa esta función)

-- ---------------------------------------------------------------------
-- 6. Quién inserta el evento: pedidos, retos y publicaciones (flores desde la tabla de reglas)
--    ON CONFLICT DO NOTHING (sin objetivo) cubre cualquier índice único: nada se paga doble.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION registrar_venta_completada()
RETURNS TRIGGER AS $$
DECLARE
    v_usuaria UUID;
    v_flores  SMALLINT;
BEGIN
    IF NEW.estado = 'completado' AND OLD.estado IS DISTINCT FROM 'completado' THEN
        SELECT usuaria_id INTO v_usuaria FROM publicaciones WHERE id = NEW.publicacion_id;
        SELECT flores INTO v_flores FROM reglas_recompensa WHERE clave = 'venta';

        INSERT INTO eventos_progreso (usuaria_id, tipo, referencia_id, flores, cuenta_para_nivel)
        VALUES (v_usuaria, 'venta', NEW.id, v_flores, TRUE)
        ON CONFLICT DO NOTHING;

        NEW.completado_en := COALESCE(NEW.completado_en, now());
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION registrar_reto_completado()
RETURNS TRIGGER AS $$
DECLARE
    v_flores SMALLINT;
BEGIN
    IF NEW.estado = 'validado' AND OLD.estado IS DISTINCT FROM 'validado' THEN
        SELECT flores INTO v_flores FROM reglas_recompensa WHERE clave = 'reto';

        INSERT INTO eventos_progreso (usuaria_id, tipo, referencia_id, flores, cuenta_para_nivel)
        VALUES (NEW.usuaria_id, 'reto', NEW.id, v_flores, TRUE)
        ON CONFLICT DO NOTHING;

        NEW.validado_en := COALESCE(NEW.validado_en, now());

        UPDATE retos SET estado = 'completado' WHERE id = NEW.reto_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION registrar_publicacion_activa()
RETURNS TRIGGER AS $$
DECLARE
    v_flores SMALLINT;
BEGIN
    -- Solo cuando la publicación ya fue aprobada (C1-05). Publicar no cuenta para el nivel.
    IF NEW.estado = 'activo' THEN
        SELECT flores INTO v_flores FROM reglas_recompensa WHERE clave = 'publicacion';

        INSERT INTO eventos_progreso (usuaria_id, tipo, referencia_id, flores, cuenta_para_nivel)
        VALUES (NEW.usuaria_id, 'publicacion', NEW.id, v_flores, FALSE)
        ON CONFLICT DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_registrar_publicacion_activa
AFTER INSERT OR UPDATE OF estado ON publicaciones
FOR EACH ROW
EXECUTE FUNCTION registrar_publicacion_activa();

-- ---------------------------------------------------------------------
-- 7. El nivel ya NO es de la habilidad: solo existe el nivel general (por actividades)
-- ---------------------------------------------------------------------
ALTER TABLE perfilado DROP COLUMN nivel_inicial;

-- ---------------------------------------------------------------------
-- 8. Publicaciones: columnas que pide el formulario y zona pública
-- ---------------------------------------------------------------------
ALTER TABLE publicaciones ALTER COLUMN opcion_entrega DROP NOT NULL;   -- los servicios no usan entrega de producto

ALTER TABLE publicaciones
    ADD COLUMN modalidad_servicio SMALLINT CHECK (modalidad_servicio IN (1, 2)),  -- 1 en casa de la vendedora · 2 a domicilio de la compradora
    ADD COLUMN esquema_cobro      SMALLINT CHECK (esquema_cobro IN (1, 2, 3)),    -- 1 por hora · 2 servicio fijo · 3 por diseño/trabajo
    ADD COLUMN costo_insumos      NUMERIC(10,2) CHECK (costo_insumos >= 0),
    ADD COLUMN horas_dedicacion   NUMERIC(5,2)  CHECK (horas_dedicacion > 0),
    ADD COLUMN zona_publica       VARCHAR(80);      -- lo ÚNICO que ve el público ("Centro de Irapuato"); la dirección real sigue cifrada

-- Publicaciones que ya existieran (de pruebas): se acomodan a las reglas nuevas antes de exigirlas
UPDATE publicaciones SET modalidad_servicio = 1, esquema_cobro = COALESCE(esquema_cobro, 2), opcion_entrega = NULL
 WHERE tipo = 'servicio';
UPDATE publicaciones SET modalidad_servicio = NULL, esquema_cobro = NULL, opcion_entrega = COALESCE(opcion_entrega, 1)
 WHERE tipo = 'producto';

-- Producto => entrega 1-3 ; servicio => modalidad 1-2 (y nunca mezcladas)
ALTER TABLE publicaciones ADD CONSTRAINT publicaciones_tipo_campos_ck CHECK (
       (tipo = 'producto' AND opcion_entrega IS NOT NULL AND modalidad_servicio IS NULL)
    OR (tipo = 'servicio' AND modalidad_servicio IS NOT NULL AND opcion_entrega IS NULL)
);

-- ---------------------------------------------------------------------
-- 9. Fotos (hasta 3 por publicación). Neon es solo Postgres: para el MVP se guardan
--    en la base (ya comprimidas por la app, máx. 400 KB cada una).
--    Si algún día hay mucho tráfico, se mueve a un bucket y solo cambia este módulo.
-- ---------------------------------------------------------------------
CREATE TABLE publicacion_imagenes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publicacion_id  UUID NOT NULL REFERENCES publicaciones(id) ON DELETE CASCADE,
    orden           SMALLINT NOT NULL CHECK (orden BETWEEN 1 AND 3),
    mime            VARCHAR(20) NOT NULL CHECK (mime IN ('image/jpeg', 'image/png', 'image/webp')),
    datos           BYTEA NOT NULL CHECK (octet_length(datos) BETWEEN 100 AND 409600),
    creada_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (publicacion_id, orden)
);

-- ---------------------------------------------------------------------
-- 10. Bienestar: UN registro por día y usuaria; cada bloque lo va completando
--     (emoción, monitoreo, reflexiones y bitácora). La bitácora queda en el servidor,
--     cifrada, y la usuaria puede volver a verla.
-- ---------------------------------------------------------------------
ALTER TABLE registros_emocionales ALTER COLUMN emocion DROP NOT NULL;
ALTER TABLE registros_emocionales
    ADD COLUMN dia DATE NOT NULL DEFAULT ((now() AT TIME ZONE 'America/Mexico_City')::date),
    ADD COLUMN actualizado_en TIMESTAMPTZ NOT NULL DEFAULT now();
UPDATE registros_emocionales SET dia = (creado_en AT TIME ZONE 'America/Mexico_City')::date;
CREATE UNIQUE INDEX registros_usuaria_dia_uq ON registros_emocionales (usuaria_id, dia);

COMMIT;
