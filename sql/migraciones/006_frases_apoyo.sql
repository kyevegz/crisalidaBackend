-- 006: Frases de apoyo de la pantalla "Respira con Lilu" (issue 1.6)
--
-- Cada frase tiene un estado: 'normal' (Lilu activa) o 'reposo' (la usuaria llevaba días sin entrar).
-- Para agregar, quitar o desactivar una frase basta con tocar esta tabla; no hace falta una
-- versión nueva de la app. Se puede correr varias veces sin duplicar frases.

BEGIN;

CREATE TABLE IF NOT EXISTS frases_apoyo (
    id         SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    texto      TEXT NOT NULL CHECK (length(btrim(texto)) > 0),
    estado     VARCHAR(10) NOT NULL CHECK (estado IN ('normal', 'reposo')),
    activa     BOOLEAN NOT NULL DEFAULT TRUE,
    creada_en  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (estado, texto)
);

-- El endpoint siempre filtra por estado y por activa
CREATE INDEX IF NOT EXISTS frases_apoyo_estado_activa_idx ON frases_apoyo (estado) WHERE activa;

-- ---------- Frases normales (las 4 primeras son las que ya traía la app) ----------
INSERT INTO frases_apoyo (estado, texto) VALUES
    ('normal', 'No eres lo que te ha tocado vivir, eres lo que eres capaz de superar.'),
    ('normal', 'Tu fuerza no se mide por lo que aguantas en silencio, sino por tu valentía para buscar paz y libertad.'),
    ('normal', 'Tienes derecho a que todos los minutos de tu vida sean de libertad, de felicidad y de paz.'),
    ('normal', 'Permítete no tener todas las respuestas resueltas ahora. La independencia se construye también en los días donde simplemente eliges cuidarte y respirar.'),
    ('normal', 'Respirar profundo es un pequeño acto de cuidado hacia ti.'),
    ('normal', 'Lo que sientes es válido, incluso cuando no sabes ponerle nombre.'),
    ('normal', 'Mereces un trato digno, siempre y en todos los lugares.'),
    ('normal', 'Cada paso pequeño cuenta, aunque hoy no lo parezca.'),
    ('normal', 'Pedir ayuda no es debilidad. Es una forma de cuidarte.'),
    ('normal', 'No tienes que poder con todo tú sola.'),
    ('normal', 'Tu tiempo y tu energía valen. Está bien proteger los dos.'),
    ('normal', 'Hoy puedes elegir una cosa pequeña que te haga bien.'),
    ('normal', 'Tus sueños y tus ideas importan, aunque aún estén empezando.'),
    ('normal', 'Mereces descansar sin tener que explicarle a nadie por qué.'),
    ('normal', 'Eres más que tus preocupaciones de hoy.')
ON CONFLICT (estado, texto) DO NOTHING;

-- ---------- Frases de reposo (sin ausencia, sin culpa, sin promesas) ----------
INSERT INTO frases_apoyo (estado, texto) VALUES
    ('reposo', 'Qué bueno verte. Aquí estoy, sin prisas.'),
    ('reposo', 'Descansar también es cuidarte.'),
    ('reposo', 'Este es un espacio tranquilo. No hay nada que tengas que hacer ahora.'),
    ('reposo', 'Puedes ir a tu ritmo. Lilu va contigo.'),
    ('reposo', 'Respira, y si quieres, quédate un rato aquí.'),
    ('reposo', 'Hoy solo basta con estar. Eso ya es suficiente.'),
    ('reposo', 'Lilu está tranquila y contenta de acompañarte.'),
    ('reposo', 'Tómate el tiempo que necesites para ti.'),
    ('reposo', 'Aquí no se te exige nada. Solo hay un lugar para respirar.'),
    ('reposo', 'Mereces un momento de calma, hoy y cuando quieras.')
ON CONFLICT (estado, texto) DO NOTHING;

COMMIT;

-- Ejemplos para administrar frases (quita los -- para usarlos):
--   Agregar:      INSERT INTO frases_apoyo (estado, texto) VALUES ('normal', 'Tu frase aquí.');
--   Desactivar:   UPDATE frases_apoyo SET activa = FALSE WHERE id = 5;
--   Reactivar:    UPDATE frases_apoyo SET activa = TRUE  WHERE id = 5;
--   Ver todas:    SELECT id, estado, activa, texto FROM frases_apoyo ORDER BY estado, id;