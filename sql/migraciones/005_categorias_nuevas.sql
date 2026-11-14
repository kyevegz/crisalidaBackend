-- Categorías nuevas de productos y servicios (se puede correr varias veces sin problema)

INSERT INTO categorias (ambito, nombre) VALUES
    -- productos
    ('producto', 'Comida Preparada y Antojitos'),
    ('producto', 'Tortillas y Masa'),
    ('producto', 'Postres y Dulces Tradicionales'),
    ('producto', 'Bebidas y Aguas Frescas'),
    ('producto', 'Lácteos y Quesos'),
    ('producto', 'Frutas, Verduras y Hortalizas'),
    ('producto', 'Miel, Huevo y Productos de Granja'),
    ('producto', 'Ropa y Prendas de Vestir'),
    ('producto', 'Cerámica y Barro'),
    ('producto', 'Artículos de Piel y Calzado'),
    ('producto', 'Jabones y Productos de Limpieza'),
    ('producto', 'Herbolaria y Productos Naturales'),
    ('producto', 'Artículos para el Hogar'),
    ('producto', 'Otros Productos'),

    -- servicios
    ('servicio', 'Cocina por Encargo y Banquetes'),
    ('servicio', 'Belleza, Peinado y Uñas'),
    ('servicio', 'Oficios y Reparaciones del Hogar'),
    ('servicio', 'Jardinería y Cuidado de Huertos'),
    ('servicio', 'Apoyo Administrativo y Digital'),
    ('servicio', 'Mandados y Entregas'),
    ('servicio', 'Otros Servicios')
ON CONFLICT (ambito, nombre) DO NOTHING;
