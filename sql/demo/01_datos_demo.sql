-- =====================================================================
--  Datos de prueba (DEMO). Se puede correr varias veces: no duplica nada.
--  Crea: contratistas/compradores, 3 vendedoras de mentira, publicaciones
--  activas (productos y servicios), algunas ventas con calificación y retos abiertos.
--  Las vendedoras demo NO pueden iniciar sesión (su PIN no corresponde a nada).
-- =====================================================================
BEGIN;

-- Externos
INSERT INTO externos (nombre_publico, tipo)
SELECT v.n, v.t FROM (VALUES
    ('Papelería La Plumita',     'contratista'),
    ('Pastelería Doña Chela',    'contratista'),
    ('Centro Comunitario Esperanza', 'contratista'),
    ('Mariana R.',               'comprador'),
    ('Tienda Raíces',            'ambos')
) AS v(n, t)
WHERE NOT EXISTS (SELECT 1 FROM externos e WHERE e.nombre_publico = v.n);

-- Vendedoras demo (hash con formato bcrypt válido pero sin PIN posible)
INSERT INTO usuarias (seudonimo, pin_hash, pin_camuflaje_hash, avatar)
SELECT v.s, '$2b$12$DEMODEMODEMODEMODEMODEuXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', '$2b$12$DEMODEMODEMODEMODEMODEuXXXXXXXXXXXXXXXXXXXXXXXXXXXXX', v.a
FROM (VALUES ('Flor de Maguey','🦋'), ('Luz Serena','🌻'), ('Arroyo Claro','🐢')) AS v(s, a)
WHERE NOT EXISTS (SELECT 1 FROM usuarias u WHERE lower(u.seudonimo) = lower(v.s));

INSERT INTO mascotas (usuaria_id)
SELECT u.id FROM usuarias u
WHERE u.seudonimo IN ('Flor de Maguey','Luz Serena','Arroyo Claro')
  AND NOT EXISTS (SELECT 1 FROM mascotas m WHERE m.usuaria_id = u.id);

-- Publicaciones (todas 'activo' para que salgan en el catálogo)
INSERT INTO publicaciones
    (usuaria_id, tipo, categoria_id, titulo, descripcion, precio, nota_precio,
     opcion_entrega, modalidad_servicio, esquema_cobro, costo_insumos, horas_dedicacion,
     tiempo_elaboracion_horas, zona_publica, estado)
SELECT u.id, v.tipo, c.id, v.titulo, v.descr, v.precio, v.nota,
       v.entrega, v.modalidad, v.cobro, v.insumos, v.horas, v.elab, v.zona, 'activo'
FROM (VALUES
  ('Flor de Maguey','producto','Conservas y Salsas','Mermelada artesanal de higo','Frasco de 250 g, sin conservadores. Receta de la abuela.',85.00,'c/frasco',2,NULL::int,NULL::int,30.00,1.5,24,'Centro de Guanajuato'),
  ('Flor de Maguey','producto','Panadería y Galletas','Galletas de avena y nuez','Caja con 12 piezas, horneadas por encargo.',120.00,'c/caja',3,NULL,NULL,45.00,2.0,48,'Centro de Guanajuato'),
  ('Flor de Maguey','servicio','Clases y Tutorías','Tutoría de primaria (matemáticas y lectura)','Clases personalizadas para niñas y niños de primaria.',150.00,'Por hora',NULL,2,1,0.00,1.0,NULL,'Zona Centro, Irapuato'),
  ('Luz Serena','producto','Velas y Aromaterapia','Vela de soya con lavanda','Vela aromática de 180 g, cera de soya y aceite esencial.',95.00,'c/pieza',1,NULL,NULL,35.00,1.0,24,'Col. Las Palmas, Silao'),
  ('Luz Serena','producto','Bordados y Tejidos','Servilletas bordadas a mano','Set de 4 servilletas de manta con bordado floral.',260.00,'c/set',3,NULL,NULL,70.00,5.0,48,'Col. Las Palmas, Silao'),
  ('Luz Serena','servicio','Corte y Confección','Arreglos de ropa y dobladillos','Ajustes, dobladillos y cambio de cierres.',60.00,'Por prenda',NULL,1,2,5.00,0.5,NULL,'Col. Las Palmas, Silao'),
  ('Arroyo Claro','producto','Jardinería y Plantas','Suculentas en maceta de barro','Maceta de 8 cm con suculenta de temporada.',55.00,'c/maceta',2,NULL,NULL,18.00,0.5,24,'Salamanca, Gto.'),
  ('Arroyo Claro','servicio','Cuidado de Mascotas','Paseo y cuidado de perros','Paseos de 45 minutos en tu zona.',90.00,'Por paseo',NULL,2,2,0.00,0.75,NULL,'Salamanca, Gto.'),
  ('Arroyo Claro','producto','Belleza y Cosmética Natural','Jabón de avena y miel','Jabón artesanal en barra, 90 g.',48.00,'c/barra',2,NULL,NULL,14.00,0.5,24,'Salamanca, Gto.')
) AS v(vend,tipo,cat,titulo,descr,precio,nota,entrega,modalidad,cobro,insumos,horas,elab,zona)
JOIN usuarias u ON u.seudonimo = v.vend
JOIN categorias c ON c.nombre = v.cat AND c.ambito = v.tipo
WHERE NOT EXISTS (SELECT 1 FROM publicaciones p WHERE p.usuaria_id = u.id AND p.titulo = v.titulo);

-- Algunas ventas ya completadas con calificación (así hay "vendidos" y estrellas).
-- Al completarse, el trigger les da flores y actividades a las vendedoras demo.
INSERT INTO pedidos (publicacion_id, comprador_id, monto, estado, calificacion, comentario)
SELECT p.id, e.id, p.precio, 'pendiente', v.cal, v.com
FROM (VALUES
  ('Mermelada artesanal de higo', 5, 'Deliciosa, llegó muy bien empacada.'),
  ('Mermelada artesanal de higo', 5, 'Muy rica, repetiré.'),
  ('Vela de soya con lavanda',    5, 'Huele increíble.'),
  ('Vela de soya con lavanda',    4, 'Muy bonita.'),
  ('Servilletas bordadas a mano', 5, 'Un trabajo precioso.'),
  ('Jabón de avena y miel',       5, 'Suave y huele a gloria.')
) AS v(titulo, cal, com)
JOIN publicaciones p ON p.titulo = v.titulo
JOIN externos e ON e.nombre_publico = 'Mariana R.'
WHERE NOT EXISTS (SELECT 1 FROM pedidos x WHERE x.publicacion_id = p.id AND x.comentario = v.com);

-- (se insertan 'pendiente' y luego se completan: el trigger solo reacciona al CAMBIO de estado)
UPDATE pedidos SET estado = 'completado'
 WHERE estado = 'pendiente'
   AND comprador_id = (SELECT id FROM externos WHERE nombre_publico = 'Mariana R.')
   AND comentario IN ('Deliciosa, llegó muy bien empacada.','Muy rica, repetiré.','Huele increíble.',
                      'Muy bonita.','Un trabajo precioso.','Suave y huele a gloria.');

-- Microrretos abiertos
INSERT INTO retos
    (contratista_id, categoria_id, titulo, descripcion, compensacion, duracion_min,
     dificultad, habilidad_requerida, etiqueta, fecha_limite, estado)
SELECT e.id, c.id, v.titulo, v.descr, v.comp, v.dur, v.dif, v.hab, v.etq,
       now() + interval '90 days', 'abierto'
FROM (VALUES
  ('Papelería La Plumita','Organización y datos','Captura de 40 productos en una hoja de cálculo','Pasar a una hoja de cálculo el nombre, precio y existencia de 40 productos desde fotos de un cuaderno.',180.00,60,'facil','Captura de datos','Datos'),
  ('Papelería La Plumita','Redacción y textos','Redacta 5 descripciones para productos','Escribe descripciones cortas y atractivas (3 líneas) para 5 artículos de papelería.',150.00,45,'media','Redacción','Redacción'),
  ('Pastelería Doña Chela','Cocina y repostería','Prepara 2 docenas de galletas decoradas','Galletas de mantequilla con decoración sencilla para un evento pequeño.',350.00,180,'media','Repostería','Cocina'),
  ('Pastelería Doña Chela','Eventos y banquetes','Arma 20 cajas de regalo para un evento','Armar y etiquetar 20 cajas con dulces que te entregamos ya preparados.',280.00,90,'facil','Organización','Eventos'),
  ('Centro Comunitario Esperanza','Educación y asesorías','Taller de lectura para niñas y niños','Una sesión de 1 hora con actividades de lectura para un grupo pequeño.',300.00,60,'media','Enseñanza','Educación'),
  ('Tienda Raíces','Costura y confección','Cose 10 bolsas de tela con logotipo','Se entrega la tela cortada. Solo falta coser y rematar.',400.00,150,'media','Costura','Costura'),
  ('Tienda Raíces','Digitalización y apoyo administrativo','Digitaliza 25 recibos en PDF','Escanear o fotografiar 25 recibos y ordenarlos por fecha en carpetas.',160.00,50,'facil','Orden y atención al detalle','TICS'),
  ('Centro Comunitario Esperanza','Cuidado personal y cosmética natural','Prepara 15 jabones artesanales','Jabones de avena en barra para un taller. Se pagan los insumos.',320.00,120,'dificil','Cosmética natural','Cosmética')
) AS v(contr, cat, titulo, descr, comp, dur, dif, hab, etq)
JOIN externos e ON e.nombre_publico = v.contr
JOIN categorias c ON c.nombre = v.cat AND c.ambito = 'reto'
WHERE NOT EXISTS (SELECT 1 FROM retos r WHERE r.titulo = v.titulo);

COMMIT;
