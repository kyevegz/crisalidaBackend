# API Crisálida (servidor)

Servidor de la app **Crisálida**: acompañamiento y emprendimiento para mujeres en situación de
vulnerabilidad. Está hecho con **FastAPI** (Python) y guarda los datos en **PostgreSQL (Neon)**.
La app Android está en el repositorio [crisalida](https://github.com/kyevegz/crisalida).

## Qué necesitas

- Python 3.10 o superior (el proyecto se desarrolló con 3.14).
- Una base de datos PostgreSQL. Se usa [Neon](https://neon.tech) (plan gratuito).
- Una llave de [Google AI Studio](https://aistudio.google.com) para el radar de talentos con IA (opcional: sin ella se usa un banco de preguntas de respaldo).

## Cómo levantar el servidor en tu computadora

1. **Clona el repositorio** y entra a la carpeta:

   ```
   git clone https://github.com/kyevegz/crisalidaBackend.git
   cd crisalidaBackend
   ```

2. **Crea y activa un entorno virtual** (una carpeta aparte con las librerías del proyecto):

   ```
   python -m venv .venv
   ```

   Para activarlo:
   - Windows (PowerShell): `.venv\Scripts\Activate.ps1`
   - Windows (CMD): `.venv\Scripts\activate.bat`
   - macOS / Linux: `source .venv/bin/activate`

   Sabrás que está activo porque la terminal muestra `(.venv)` al inicio.

3. **Instala las dependencias:**

   ```
   pip install -r requirements.txt
   ```

4. **Prepara la base de datos.** Crea las tablas corriendo, en orden, los archivos de la carpeta
   [`sql/`](sql/README.md) (ahí se explica cuáles y en qué orden).

5. **Crea tu archivo `.env`.** Copia `env.example` como `.env` y llena los valores
   (explicados abajo):

   - Windows: `copy env.example .env`
   - macOS / Linux: `cp env.example .env`

   El archivo `.env` contiene secretos: **nunca se sube a GitHub** (ya está en `.gitignore`).

6. **Arranca el servidor:**

   ```
   uvicorn main:app --reload
   ```

   Queda en <http://127.0.0.1:8000>. La documentación interactiva de todos los endpoints está en
   <http://127.0.0.1:8000/docs>. El `--reload` reinicia el servidor solo cuando cambias el código.

Si falta una variable obligatoria, el servidor no arranca y dice cuál es
(por ejemplo: `Falta la variable JWT_SECRET en el archivo .env`).

## Variables del archivo `.env`

### Base de datos (obligatorias)

En Neon: **Connect** → copia los datos de conexión.

| Variable | Qué es |
|---|---|
| `DB_HOST` | Servidor de la base de datos (algo como `ep-xxxx.neon.tech`). |
| `DB_PORT` | Puerto. Normalmente `5432`. |
| `DB_USER` | Usuario de la base de datos. |
| `DB_PASSWORD` | Contraseña de ese usuario. |
| `DB_NAME` | Nombre de la base de datos. |

La conexión siempre va cifrada (TLS), que es lo que exige Neon.

### Secretos de la aplicación (obligatorios)

Cada uno se genera con el comando indicado y se pega en el `.env`. **Genera valores distintos para
cada entorno**.

| Variable | Para qué sirve | Cómo generarla |
|---|---|---|
| `CLAVE_AES` | Llave que cifra los textos privados de bienestar y los puntos de entrega (AES-256). Debe ser de 32 bytes en base64. **Si la pierdes o la cambias, no se podrán leer los textos ya guardados.** | `python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"` |
| `JWT_SECRET` | Llave con la que se firman los tokens de sesión. Si alguien la conoce, puede fabricar sesiones. | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `PIN_PEPPER` | Valor secreto extra que se mezcla con cada PIN antes de guardarlo. **Si la cambias, ninguna usuaria podrá iniciar sesión con su PIN.** | `python -c "import secrets;print(secrets.token_urlsafe(32))"` |

### Opcionales

| Variable | Valor por defecto | Qué hace |
|---|---|---|
| `JWT_HORAS` | `24` | Cuántas horas dura una sesión antes de pedir el PIN de nuevo. |
| `REGISTRO_MINUTOS` | `120` | Cuántos minutos tiene una usuaria para terminar su registro una vez iniciado. |
| `REPOSO_DIAS` | `7` | Días sin usar la app para que Lilu pase a `reposo` (el campo reposo de `GET /progreso/yo`).
| `AVISO_VERSION` | `1` | Versión vigente del aviso de privacidad y términos. Al cambiarla, a todas las usuarias se les pide aceptar de nuevo en su siguiente login. |
| `GEMINI_API_KEY` | vacío | Llave de Google AI Studio para el radar de talentos. Sin ella el radar usa un banco de preguntas de respaldo. |
| `GEMINI_MODEL` | `gemini-flash-latest` | Nombre exacto del modelo de Gemini (uno Flash o Flash-Lite marcado como gratuito en AI Studio). |
| `AUTOAPROBAR_PUBLICACIONES` | `false` | Con `true`, las publicaciones nuevas se aprueban solas (útil para demostraciones). Con `false` quedan "en revisión". |
| `MODO_DEMO` | `false` | Con `true` se activan los atajos `/demo/...` para simular ventas y validación de retos. **Apágalo en producción.** |

## Estructura del proyecto

| Archivo | Qué contiene |
|---|---|
| `main.py` | La aplicación, el registro y el inicio de sesión. |
| `seguridad.py` | PIN, tokens y cifrado. |
| `dependencias.py` | Quién puede entrar a cada endpoint (modo normal, camuflaje, registro). |
| `db.py` | Conexión a la base de datos. |
| `radar.py`, `radar_logica.py` | Radar de talentos y su IA. |
| `progreso.py` | Flores, niveles y mascota. |
| `bienestar.py` | Registros de bienestar emocional (cifrados). |
| `marketplace.py`, `publicaciones.py` | Productos y servicios. |
| `retos.py` | Retos y entregas. |
| `demo.py` | Atajos de demostración (solo con `MODO_DEMO=true`). |
| `sql/` | Scripts de la base de datos. |

## Publicarlo en Render

El servidor en producción corre en Render. Los comandos son:

- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

Las variables del `.env` se capturan en **Environment** del servicio en Render (no se suben al repo).
En el plan gratuito el servidor se duerme tras unos minutos sin uso, y la primera petición puede
tardar de 30 a 60 segundos.