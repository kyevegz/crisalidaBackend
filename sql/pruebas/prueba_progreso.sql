\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on
CREATE TEMP TABLE t(paso text, ok boolean, detalle text);
CREATE OR REPLACE FUNCTION pg_temp.chk(p text, cond boolean, d text) RETURNS void AS $$
BEGIN INSERT INTO t VALUES (p, cond, d); END $$ LANGUAGE plpgsql;

INSERT INTO usuarias(seudonimo,pin_hash,pin_camuflaje_hash) VALUES ('ana','x','y'),('vendedora_dummy','x','y');
INSERT INTO mascotas(usuaria_id) SELECT id FROM usuarias;
INSERT INTO externos(nombre_publico,tipo) VALUES ('Cafe Rosa','ambos');

-- 1) publicar: 'en_revision' no da flores; al aprobarse da 20; 2da publicación el mismo día no da más y NO falla
INSERT INTO publicaciones(usuaria_id,tipo,categoria_id,titulo,precio,opcion_entrega)
  SELECT u.id,'producto',(SELECT id FROM categorias WHERE ambito='producto' LIMIT 1),'Mermelada',50,1 FROM usuarias u WHERE seudonimo='ana';
SELECT pg_temp.chk('1a en_revision no da flores', (SELECT flores FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana')=0, '');
UPDATE publicaciones SET estado='activo';
SELECT pg_temp.chk('1b aprobada = +20', (SELECT flores FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana')=20, '');
INSERT INTO publicaciones(usuaria_id,tipo,categoria_id,titulo,precio,opcion_entrega,estado)
  SELECT u.id,'producto',(SELECT id FROM categorias WHERE ambito='producto' LIMIT 1),'Galletas',30,1,'activo' FROM usuarias u WHERE seudonimo='ana';
SELECT pg_temp.chk('1c segunda el mismo dia: sin error y sin flores extra', (SELECT flores FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana')=20, '');
UPDATE publicaciones SET estado='pausado'; UPDATE publicaciones SET estado='activo';
SELECT pg_temp.chk('1d pausar/reactivar no paga doble', (SELECT flores FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana')=20, '');

-- 2) ventas: cada una +30 y 1 actividad; la tercera sube a Brote (+25)
INSERT INTO pedidos(publicacion_id,comprador_id,monto,estado,calificacion)
  SELECT p.id,(SELECT id FROM externos LIMIT 1),50,'entregado',5 FROM publicaciones p, generate_series(1,3) WHERE p.titulo='Mermelada';
-- completar la 1ª venta
UPDATE pedidos SET estado='completado' WHERE id=(SELECT id FROM pedidos ORDER BY id LIMIT 1);
SELECT pg_temp.chk('2a 1 venta: 1 actividad y +30 flores (20+30=50)',
  (SELECT actividades_completadas=1 AND flores=50 AND nivel=1 FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana'), '');
UPDATE pedidos SET estado='completado', monto=51 WHERE estado='completado';   -- re-tocar no debe pagar doble
SELECT pg_temp.chk('2b repetir el update no duplica',
  (SELECT actividades_completadas=1 AND flores=50 FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana'), '');
UPDATE pedidos SET estado='completado' WHERE estado='entregado';               -- 2 ventas más -> 3 actividades
SELECT pg_temp.chk('2c 3 actividades -> nivel 2 (Brote) y bono 25: 20+90+25=135',
  (SELECT actividades_completadas=3 AND nivel=2 AND flores=135 FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana'), '');
SELECT pg_temp.chk('2d historial_niveles registra 1->2',
  (SELECT count(*)=1 FROM historial_niveles h JOIN usuarias u ON u.id=h.usuaria_id WHERE seudonimo='ana' AND nivel_anterior=1 AND nivel_nuevo=2), '');

-- 3) reto: validar = +30 y 1 actividad
INSERT INTO retos(contratista_id,categoria_id,titulo,descripcion,compensacion,duracion_min,dificultad,fecha_limite,estado)
  VALUES ((SELECT id FROM externos LIMIT 1),(SELECT id FROM categorias WHERE ambito='reto' LIMIT 1),'Excel','x',100,30,'facil',now()+interval '3 days','abierto');
INSERT INTO reto_aceptaciones(reto_id,usuaria_id) SELECT r.id,u.id FROM retos r, usuarias u WHERE u.seudonimo='ana';
UPDATE reto_aceptaciones SET estado='validado';
SELECT pg_temp.chk('3a reto: 4 actividades, 135+30=165 flores, reto completado',
  (SELECT actividades_completadas=4 AND flores=165 FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana')
  AND (SELECT estado='completado' FROM retos), '');

-- 4) bienestar: se inserta como lo hará Python; el 2º del mismo bloque y día se ignora (sin error)
INSERT INTO eventos_progreso(usuaria_id,tipo,subtipo,flores,cuenta_para_nivel)
  SELECT id,'bienestar','emocion',5,FALSE FROM usuarias WHERE seudonimo='ana' ON CONFLICT DO NOTHING;
INSERT INTO eventos_progreso(usuaria_id,tipo,subtipo,flores,cuenta_para_nivel)
  SELECT id,'bienestar','emocion',5,FALSE FROM usuarias WHERE seudonimo='ana' ON CONFLICT DO NOTHING;
SELECT pg_temp.chk('4a bienestar: +5 una sola vez, sin contar para el nivel',
  (SELECT flores=170 AND actividades_completadas=4 FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana'), '');

-- 5) la tabla de eventos cuadra con la mascota (la suma de eventos = flores)
SELECT pg_temp.chk('5 suma de eventos = flores de la mascota',
  (SELECT sum(flores) FROM eventos_progreso e JOIN usuarias u ON u.id=e.usuaria_id WHERE seudonimo='ana')
  = (SELECT flores FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='ana'), '');

-- 6) otra usuaria no se ve afectada
SELECT pg_temp.chk('6 la otra usuaria sigue en 0',
  (SELECT flores=0 AND actividades_completadas=0 FROM mascotas m JOIN usuarias u ON u.id=m.usuaria_id WHERE seudonimo='vendedora_dummy'), '');

SELECT CASE WHEN ok THEN 'OK   ' ELSE 'FALLA' END || ' ' || paso FROM t;
