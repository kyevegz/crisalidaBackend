# Cómo colaborar

Este proyecto es de mantenimiento: todo cambio parte de un issue del proyecto de GitHub.

## Flujo de trabajo
1. Toma un issue de la columna "Por hacer" y pásalo a "En curso".
2. Crea una rama desde `main` con el nombre del issue.
3. Haz commits pequeños siguiendo las reglas de abajo.
4. Abre un Pull Request con `Closes #n` en la descripción.
5. La otra persona del equipo lo revisa y lo aprueba (mínimo 1 aprobación).
6. Se hace merge a `main`; el issue pasa solo a "Listo".

Nadie hace push directo a `main`.

## Ramas
Formato: `tipo/numero-descripcion-corta`, todo en minúsculas y con guiones.

| Tipo | Cuándo se usa | Ejemplo |
|---|---|---|
| `feat` | Función o pantalla nueva | `feat/14-rol-usuaria` |
| `fix` | Corrección de un error | `fix/3-responsivo-login` |
| `chore` | Limpieza, configuración, dependencias | `chore/1-limpiar-repo` |
| `docs` | Solo documentación | `docs/6-contributing` |
| `refactor` | Reorganizar código sin cambiar su comportamiento | `refactor/8-colores-tema` |
| `test` | Agregar o corregir pruebas | `test/2-pruebas-etapa-2` |

## Commits
Formato: `tipo(alcance): mensaje corto en presente`

- Los tipos son los mismos que en las ramas.
- El alcance es la parte tocada: `auth`, `retos`, `bienestar`, `seguridad`...
- El mensaje va en minúsculas, sin punto final y de unos 70 caracteres como máximo.

Ejemplos:
- `feat(auth): agrega campo rol al registro`
- `fix(login): corrige texto cortado en pantallas chicas`
- `chore(repo): quita Lib y Scripts del control de versiones`
- `docs(readme): actualiza instrucciones de instalación`

## Pull Requests
- El título sigue el formato del commit principal.
- Debe incluir `Closes #n` para cerrar el issue al hacer merge.
- Llena la lista de comprobación de la plantilla.
- Un PR resuelve un solo issue.

## Tipos de mantenimiento
Cada issue lleva en el proyecto el campo **Tipo**:
- **Correctivo:** arregla errores.
- **Preventivo:** evita problemas futuros (limpieza, seguridad, pruebas).
- **Adaptativo:** responde a cambios externos (leyes, versiones, entorno).
- **Perfectivo:** agrega o mejora funciones.

## Seguridad
- Nunca subas `.env`, claves, tokens ni contraseñas.
- Las variables nuevas se documentan en `env.example` sin valores reales.
