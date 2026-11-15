-- Revisión de retos publicados por usuarias (mientras no exista la ruta de aprobar/rechazar).
-- Se corre a mano en Neon. NO es una migración: se puede usar las veces que haga falta.

-- 1) Ver los retos que esperan revisión (los más viejos primero)
SELECT r.id, u.seudonimo AS publicado_por, c.nombre AS categoria, r.titulo, r.descripcion,
       r.compensacion, r.fecha_limite, r.creado_en
  FROM retos r
  JOIN usuarias u ON u.id = r.publicado_por
  JOIN categorias c ON c.id = r.categoria_id
 WHERE r.estado = 'en_revision'
 ORDER BY r.creado_en;

-- 2) Aprobar (cambia el id por el del reto): desde aquí aparece en el tablero
UPDATE retos SET estado = 'abierto', revisado_en = now(), motivo_rechazo = NULL
 WHERE id = '00000000-0000-0000-0000-000000000000' AND estado = 'en_revision';

-- 3) Rechazar, con el motivo que se le mostrará a la usuaria
UPDATE retos SET estado = 'rechazado', revisado_en = now(), motivo_rechazo = 'Escribe aquí el motivo'
 WHERE id = '00000000-0000-0000-0000-000000000000' AND estado = 'en_revision';