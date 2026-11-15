-- 017 · Una usuaria no puede aceptar su propio reto (issue "Mis retos y entregas")
-- El backend ya lo revisa (403); esta regla en la BD es la segunda barrera, por si algún día otra ruta lo olvida.
-- Se puede correr más de una vez sin problema.
BEGIN;

CREATE OR REPLACE FUNCTION no_aceptar_reto_propio() RETURNS trigger AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM retos r WHERE r.id = NEW.reto_id AND r.publicado_por = NEW.usuaria_id) THEN
        RAISE EXCEPTION 'Una usuaria no puede aceptar su propio reto' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_no_aceptar_reto_propio ON reto_aceptaciones;
CREATE TRIGGER trg_no_aceptar_reto_propio
BEFORE INSERT ON reto_aceptaciones
FOR EACH ROW EXECUTE FUNCTION no_aceptar_reto_propio();

COMMIT;