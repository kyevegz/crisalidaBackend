-- =====================================================================
--  Consultas de SOLO LECTURA para ver cómo está la BD real (no cambian nada).
--  Córrelas una por una en el editor SQL de Neon y compara con migraciones/.
-- =====================================================================

-- 1) Tablas y sus columnas (una fila por tabla)
SELECT table_name,
       string_agg(column_name || ' ' || data_type, ', ' ORDER BY ordinal_position) AS columnas
  FROM information_schema.columns
 WHERE table_schema = 'public'
 GROUP BY table_name
 ORDER BY table_name;

-- 2) Triggers
SELECT c.relname AS tabla, t.tgname AS trigger
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
 WHERE NOT t.tgisinternal
 ORDER BY 1, 2;

-- 3) Funciones propias
SELECT p.proname AS funcion
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
 ORDER BY 1;

-- 4) Restricciones CHECK y UNIQUE
SELECT conrelid::regclass AS tabla, conname, pg_get_constraintdef(oid) AS definicion
  FROM pg_constraint
 WHERE connamespace = 'public'::regnamespace AND contype IN ('c', 'u')
 ORDER BY 1, 2;

-- 5) Cuántas filas tienen las tablas de catálogo
SELECT 'categorias' AS tabla, count(*) FROM categorias
UNION ALL SELECT 'niveles', count(*) FROM niveles
UNION ALL SELECT 'reglas_recompensa', count(*) FROM reglas_recompensa
UNION ALL SELECT 'etapas_lilu', count(*) FROM etapas_lilu;
