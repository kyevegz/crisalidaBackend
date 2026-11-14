"""Envío de correos con la API HTTP de Brevo.

Se usa la API (HTTPS) y no SMTP porque Render, en el plan gratis, bloquea los puertos SMTP.
Todo se configura con variables de entorno (ver env.example): BREVO_API_KEY, CORREO_REMITENTE
y CORREO_NOMBRE_REMITENTE. Si no están, la app funciona igual pero no se envía ningún correo.

Uso desde otro módulo:
    from correo import enviar_correo
    if not enviar_correo(destino, "Tu código", f"Tu código es {codigo}"):
        ...  # el correo no salió: la app sigue funcionando, el error ya quedó en el registro

Para probar que Brevo funciona, desde la raíz del backend y con el .env lleno:
    python correo.py tu_correo@ejemplo.com
"""
import logging
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("crisalida.correo")

URL_BREVO = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SEGUNDOS = 10
CORREO_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ocultar(correo: str) -> str:
    """'ana@gmail.com' -> 'a***@gmail.com': el registro no guarda correos completos."""
    usuario, _, dominio = correo.partition("@")
    return f"{usuario[:1]}***@{dominio}" if dominio else "***"


def enviar_correo(destinatario: str, asunto: str, texto: str, html: str | None = None) -> bool:
    """Envía un correo y devuelve True si Brevo lo aceptó, False si no.

    NUNCA lanza excepciones: si algo falla (sin configurar, sin internet, Brevo rechaza el
    correo) lo anota en el registro y devuelve False, para no romper la petición de la usuaria.
    Si se manda `html`, ese es el cuerpo; si no, se manda `texto` (Brevo acepta solo uno).
    El contenido del correo y la llave nunca se escriben en el registro."""
    api_key = os.getenv("BREVO_API_KEY")
    remitente = os.getenv("CORREO_REMITENTE")
    if not api_key or not remitente:
        log.warning("Correo no enviado: falta BREVO_API_KEY o CORREO_REMITENTE")
        return False
    if not CORREO_RE.match(destinatario or ""):
        log.error("Correo no enviado: el destinatario no es una dirección válida")
        return False

    cuerpo = {
        "sender": {"name": os.getenv("CORREO_NOMBRE_REMITENTE", "Crisálida"), "email": remitente},
        "to": [{"email": destinatario}],
        "subject": asunto,
    }
    if html:
        cuerpo["htmlContent"] = html
    else:
        cuerpo["textContent"] = texto

    try:
        respuesta = requests.post(
            URL_BREVO,
            json=cuerpo,
            headers={"api-key": api_key, "accept": "application/json"},
            timeout=TIMEOUT_SEGUNDOS,
        )
    except requests.RequestException as error:
        log.error("No se pudo conectar con Brevo (destino %s): %s", _ocultar(destinatario), type(error).__name__)
        return False

    if respuesta.status_code == 201:
        log.info("Correo enviado a %s", _ocultar(destinatario))
        return True

    log.error("Brevo rechazó el correo a %s: HTTP %s %s",
              _ocultar(destinatario), respuesta.status_code, respuesta.text[:300])
    return False


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) != 2:
        sys.exit("Uso: python correo.py tu_correo@ejemplo.com")
    ok = enviar_correo(sys.argv[1], "Prueba de Crisálida", "Si lees esto, el envío de correos funciona.")
    print("Enviado: revisa tu bandeja (y la carpeta de spam)." if ok else "No se pudo enviar: revisa el mensaje de arriba.")