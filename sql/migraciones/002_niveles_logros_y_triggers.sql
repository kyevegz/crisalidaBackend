CREATE TABLE niveles (
    nivel SMALLINT PRIMARY KEY,
    nombre VARCHAR(40) NOT NULL UNIQUE,
    actividades_requeridas INTEGER NOT NULL UNIQUE,
    descripcion TEXT NOT NULL,
    creada_en TIMESTAMPTZ NOT NULL DEFAULT now(),

    CHECK (nivel BETWEEN 1 AND 10),
    CHECK (actividades_requeridas >= 0)
);

INSERT INTO niveles
    (nivel, nombre, actividades_requeridas, descripcion)
VALUES
    (1, 'Semilla', 0,
     'Comienza a descubrir sus talentos y habilidades.'),

    (2, 'Brote', 3,
     'Da sus primeros pasos en el comercio.'),

    (3, 'Crecimiento', 8,
     'Desarrolla confianza y experiencia.'),

    (4, 'Florecimiento', 15,
     'Comienza a destacar por sus habilidades.'),

    (5, 'Emprendedora', 25,
     'Convierte sus talentos en oportunidades de ingreso.'),

    (6, 'Independiente', 40,
     'Fortalece su autonomía económica.'),

    (7, 'Destacada', 60,
     'Demuestra compromiso y experiencia.'),

    (8, 'Inspiradora', 85,
     'Motiva a otras mujeres de la comunidad.'),

    (9, 'Líder', 115,
     'Construye una trayectoria sólida.'),

    (10, 'Mujer Extraordinaria', 150,
     'Alcanza el máximo nivel de desarrollo en la plataforma.');



ALTER TABLE mascotas
ADD COLUMN actividades_completadas INTEGER NOT NULL DEFAULT 0
CHECK (actividades_completadas >= 0);

-- Asegurar que los niveles existentes sean válidos.
UPDATE mascotas
SET nivel = 1
WHERE nivel IS NULL OR nivel < 1 OR nivel > 10;

-- Relacionar la mascota con el catálogo de niveles.
ALTER TABLE mascotas
ADD CONSTRAINT mascotas_nivel_fk
FOREIGN KEY (nivel)
REFERENCES niveles(nivel);



ALTER TABLE eventos_progreso
ADD COLUMN cuenta_para_nivel BOOLEAN NOT NULL DEFAULT TRUE;

-- Los registros de bienestar no cuentan para subir de nivel.
UPDATE eventos_progreso
SET cuenta_para_nivel = FALSE
WHERE tipo = 'bienestar';

-- Evitar que una misma venta o reto genere
-- más de un evento de progreso.
CREATE UNIQUE INDEX eventos_progreso_referencia_uq
ON eventos_progreso (tipo, referencia_id)
WHERE referencia_id IS NOT NULL;



CREATE OR REPLACE FUNCTION actualizar_progreso_mascota()
RETURNS TRIGGER AS $$
BEGIN
    -- Solo las actividades comerciales cuentan
    -- para subir de nivel.
    IF NEW.cuenta_para_nivel = TRUE
       AND NEW.tipo IN ('venta', 'reto') THEN

        INSERT INTO mascotas (
            usuaria_id,
            actividades_completadas,
            nivel,
            ultima_actividad
        )
        VALUES (
            NEW.usuaria_id,
            1,
            1,
            NEW.creado_en
        )
        ON CONFLICT (usuaria_id)
        DO UPDATE SET
            actividades_completadas =
                mascotas.actividades_completadas + 1,

            ultima_actividad = NEW.creado_en,

            nivel = (
                SELECT n.nivel
                FROM niveles n
                WHERE n.actividades_requeridas <=
                    mascotas.actividades_completadas + 1
                ORDER BY n.actividades_requeridas DESC
                LIMIT 1
            );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_actualizar_progreso_mascota
AFTER INSERT ON eventos_progreso
FOR EACH ROW
EXECUTE FUNCTION actualizar_progreso_mascota();



CREATE OR REPLACE FUNCTION registrar_venta_completada()
RETURNS TRIGGER AS $$
DECLARE
    v_usuaria UUID;
BEGIN
    IF NEW.estado = 'completado'
       AND OLD.estado IS DISTINCT FROM 'completado' THEN

        SELECT usuaria_id
        INTO v_usuaria
        FROM publicaciones
        WHERE id = NEW.publicacion_id;

        INSERT INTO eventos_progreso (
            usuaria_id,
            tipo,
            referencia_id,
            semillas,
            cuenta_para_nivel
        )
        VALUES (
            v_usuaria,
            'venta',
            NEW.id,
            1,
            TRUE
        )
        ON CONFLICT (tipo, referencia_id)
        WHERE referencia_id IS NOT NULL
        DO NOTHING;

        NEW.completado_en = COALESCE(
            NEW.completado_en,
            now()
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_registrar_venta_completada
BEFORE UPDATE OF estado ON pedidos
FOR EACH ROW
EXECUTE FUNCTION registrar_venta_completada();



CREATE OR REPLACE FUNCTION registrar_reto_completado()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.estado = 'validado'
       AND OLD.estado IS DISTINCT FROM 'validado' THEN

        INSERT INTO eventos_progreso (
            usuaria_id,
            tipo,
            referencia_id,
            semillas,
            cuenta_para_nivel
        )
        VALUES (
            NEW.usuaria_id,
            'reto',
            NEW.id,
            1,
            TRUE
        )
        ON CONFLICT (tipo, referencia_id)
        WHERE referencia_id IS NOT NULL
        DO NOTHING;

        NEW.validado_en = COALESCE(
            NEW.validado_en,
            now()
        );

        UPDATE retos
        SET estado = 'completado'
        WHERE id = NEW.reto_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_registrar_reto_completado
BEFORE UPDATE OF estado ON reto_aceptaciones
FOR EACH ROW
EXECUTE FUNCTION registrar_reto_completado();



CREATE TABLE logros (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    nombre VARCHAR(80) NOT NULL UNIQUE,
    descripcion TEXT NOT NULL,
    icono VARCHAR(120),
    tipo VARCHAR(15) NOT NULL
        CHECK (tipo IN (
            'venta',
            'reto',
            'nivel',
            'constancia',
            'especial'
        )),

    requisito INTEGER NOT NULL DEFAULT 1
        CHECK (requisito > 0),

    creado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);



CREATE TABLE usuaria_logros (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    usuaria_id UUID NOT NULL
        REFERENCES usuarias(id) ON DELETE CASCADE,

    logro_id UUID NOT NULL
        REFERENCES logros(id) ON DELETE CASCADE,

    desbloqueado_en TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (usuaria_id, logro_id)
);

CREATE INDEX usuaria_logros_idx
ON usuaria_logros (usuaria_id);



INSERT INTO logros (nombre, descripcion, tipo, requisito)
VALUES
('Primeros pasos', 'Completó su primera venta.', 'venta', 1),

('Vendedora constante', 'Completó 5 ventas.', 'venta', 5),

('Primera oportunidad', 'Completó su primer reto.', 'reto', 1),

('Experta en retos', 'Completó 10 retos.', 'reto', 10),

('Emprendedora', 'Alcanzó el nivel 5.', 'nivel', 5),

('Mujer extraordinaria', 'Alcanzó el nivel 10.', 'nivel', 10),

('Gran trayectoria', 'Completó 50 actividades.', 'constancia', 50);



CREATE TABLE habilidades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    nombre VARCHAR(80) NOT NULL UNIQUE,
    descripcion TEXT,
    categoria VARCHAR(40),

    creada_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Relacionar las habilidades detectadas con el catálogo.
ALTER TABLE habilidades_usuaria
ADD COLUMN habilidad_id UUID
REFERENCES habilidades(id) ON DELETE SET NULL;

CREATE INDEX habilidades_usuaria_idx
ON habilidades_usuaria (usuaria_id);



CREATE TABLE historial_niveles (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    usuaria_id UUID NOT NULL
        REFERENCES usuarias(id) ON DELETE CASCADE,

    nivel_anterior SMALLINT REFERENCES niveles(nivel),
    nivel_nuevo SMALLINT NOT NULL REFERENCES niveles(nivel),

    cambiado_en TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX historial_niveles_usuaria_idx
ON historial_niveles (usuaria_id, cambiado_en DESC);



CREATE OR REPLACE FUNCTION registrar_cambio_nivel()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.nivel IS DISTINCT FROM NEW.nivel THEN

        INSERT INTO historial_niveles (
            usuaria_id,
            nivel_anterior,
            nivel_nuevo
        )
        VALUES (
            NEW.usuaria_id,
            OLD.nivel,
            NEW.nivel
        );

    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_historial_niveles
AFTER UPDATE OF nivel ON mascotas
FOR EACH ROW
EXECUTE FUNCTION registrar_cambio_nivel();



-- Publicaciones con categorías incorrectas.
SELECT p.id, p.tipo, c.ambito
FROM publicaciones p
JOIN categorias c ON c.id = p.categoria_id
WHERE p.tipo <> c.ambito;

-- Retos con categorías incorrectas.
SELECT r.id, c.ambito
FROM retos r
JOIN categorias c ON c.id = r.categoria_id
WHERE c.ambito <> 'reto';



ALTER TABLE categorias
ADD CONSTRAINT categorias_id_ambito_uq
UNIQUE (id, ambito);

ALTER TABLE publicaciones
ADD CONSTRAINT publicaciones_categoria_tipo_fk
FOREIGN KEY (categoria_id, tipo)
REFERENCES categorias (id, ambito);

ALTER TABLE retos
ADD COLUMN ambito_categoria VARCHAR(10)
GENERATED ALWAYS AS ('reto'::VARCHAR(10)) STORED;

ALTER TABLE retos
ADD CONSTRAINT retos_categoria_ambito_fk
FOREIGN KEY (categoria_id, ambito_categoria)
REFERENCES categorias (id, ambito);
