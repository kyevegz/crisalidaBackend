-- =====================================================================
--  Comandos para la DEMO (córrelos a mano en el editor SQL de Neon).
--  Como los compradores y contratistas aún no tienen login,
--  estas líneas hacen lo que ellos harían. Cambia 'TU_SEUDONIMO'.
-- =====================================================================

-- 1) Aprobar tu publicación en revisión (da 20 flores, máx. 1 por día):
-- UPDATE publicaciones SET estado = 'activo'
--  WHERE usuaria_id = (SELECT id FROM usuarias WHERE lower(seudonimo) = lower('TU_SEUDONIMO'))
--    AND estado = 'en_revision';

-- 2) Simular que alguien compró y recibió una de tus publicaciones (da 30 flores y +1 actividad):
-- INSERT INTO pedidos (publicacion_id, comprador_id, monto, estado, calificacion, comentario)
-- SELECT p.id, (SELECT id FROM externos WHERE nombre_publico = 'Mariana R.'), p.precio, 'completado', 5, 'Todo excelente'
--   FROM publicaciones p
--  WHERE p.usuaria_id = (SELECT id FROM usuarias WHERE lower(seudonimo) = lower('TU_SEUDONIMO'))
--    AND p.estado = 'activo'
--  ORDER BY p.creada_en DESC LIMIT 1;

-- 3) Simular que el contratista validó tu reto entregado (da 30 flores y +1 actividad):
-- UPDATE reto_aceptaciones SET estado = 'validado'
--  WHERE usuaria_id = (SELECT id FROM usuarias WHERE lower(seudonimo) = lower('TU_SEUDONIMO'))
--    AND estado = 'entregado';

-- 4) Ver cómo va tu progreso:
-- SELECT u.seudonimo, m.nivel, m.actividades_completadas, m.flores
--   FROM mascotas m JOIN usuarias u ON u.id = m.usuaria_id
--  WHERE lower(u.seudonimo) = lower('TU_SEUDONIMO');

-- 5) Renovar la fecha límite de los retos de prueba (por si ya vencieron):
-- UPDATE retos SET fecha_limite = now() + interval '90 days' WHERE estado = 'abierto';
