"""Filtros de seguridad para los retos que publican las usuarias (issue 7.1).

Un reto no puede incluir en su título, descripción o habilidad:
  - 'contacto':  datos de contacto (teléfono, correo, redes sociales, enlaces). Todo pasa dentro de Crisálida.
  - 'direccion': direcciones exactas (calle y número, código postal, domicilio).
  - 'dinero':    pedir dinero por adelantado o pagos/depósitos fuera de la plataforma, inversiones, estafas típicas.
  - 'repetido':  texto repetido o sin sentido (spam).

Es una primera barrera automática y sencilla, hecha con expresiones regulares: no sustituye la revisión del
equipo (todos los retos pasan por revisión antes de verse). Si un reto legítimo se rechaza, se ajusta aquí.
El texto se normaliza (minúsculas, sin acentos) antes de revisarlo.
"""
import re
import unicodedata

MENSAJES = {
    "contacto": "datos de contacto (teléfono, correo, redes sociales o enlaces)",
    "direccion": "direcciones exactas",
    "dinero": "pedir dinero por adelantado o pagos fuera de Crisálida",
    "repetido": "texto repetido o sin sentido",
}


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos.lower()).strip()


_CALLES = r"(?:calle|avenida|av|blvd|boulevard|calzada|privada|andador|callejon|carretera|prolongacion|cerrada|periferico)"

_PATRONES = {
    "contacto": [
        r"[a-z0-9._%+-]+\s*(?:@|\(at\)|\[at\])\s*[a-z0-9-]+",             # correo
        r"\barroba\b",
        r"(?<![\w@])@[a-z0-9._]{3,}",                                      # @usuario
        r"https?://|www\.",                                                # enlaces
        r"\b[a-z0-9-]{2,}\.(?:com|mx|net|org|io|me|co|info|xyz|ly|link|app|shop|store|site|online)\b",
        r"(?:\d[\s().\-]*){8,}",                                           # 8 o más dígitos (teléfono)
        r"\b(?:whats\s?app|wasap|watsap|telegram|instagram|facebook|messenger|tiktok|snapchat|signal|discord)\b",
        r"\b(?:inbox|mensaje directo|llamame|marcame|contactame|escribeme)\b",
        r"\b(?:numero de|mi) (?:telefono|celular|cel|whats|correo|email)\b",
    ],
    "direccion": [
        rf"\b{_CALLES}\b\.?[^\d\n]{{0,40}}\d{{1,5}}",                      # calle/avenida + número
        r"\bc\.?\s?p\.?\s?\d{5}\b",                                        # código postal
        r"\bcodigo postal\b",
        r"\b(?:mi|nuestro|el)\s+(?:domicilio|direccion)\b",
        r"\b(?:manzana|mz|lote|depto|departamento|interior|int)\.?\s?\d+",
        r"\besquina con\b|\bentre calles?\b",
        r"\bgoogle maps\b|\bmaps\.app\b|\bubicacion (?:en vivo|exacta)\b",
    ],
    "dinero": [
        r"\bpor adelantado\b|\badelantado\b|\banticipo\b",
        r"\b(?:pago|deposito) (?:previo|inicial|anticipado)\b",
        r"\bpaga(?:me)? (?:primero|antes)\b|\bpagame (?:primero|antes)\b",
        r"\b(?:depositame|depositar|deposita|deposito|transfierem?e|transferencia|transferir)\b",
        r"\b(?:mandame|enviame|manda|envia) (?:dinero|lana|el pago|pago|\$)",
        r"\bclabe\b|\bnumero de cuenta\b|\bcuenta bancaria\b",
        r"\btarjeta (?:de )?(?:credito|debito|regalo)\b|\bgift ?card\b",
        r"\bpaypal\b|\bmercado ?pago\b|\boxxo\b|\bspei\b|\bbitcoin\b|\bcripto\w*",
        r"\bcuota de (?:inscripcion|registro|acceso|recuperacion)\b|\bmembresia\b",
        r"\binversion\b|\binvierte\b|\bdinero facil\b|\bganar dinero (?:rapido|facil)\b|\bsin invertir\b",
        r"\breembols\w+|\bkit de inicio\b|\bpaquete de inicio\b",
    ],
    "repetido": [
        r"(.)\1{5,}",                                                      # aaaaaa, !!!!!!
        r"\b(\w{2,})(?: \1){3,}\b",                                        # hola hola hola hola
    ],
}
_COMPILADOS = {k: [re.compile(p) for p in v] for k, v in _PATRONES.items()}


def motivos(texto: str | None) -> list[str]:
    """Devuelve los motivos por los que el texto no se puede publicar (lista vacía = está bien)."""
    if not texto:
        return []
    t = _normalizar(texto)
    return [motivo for motivo, patrones in _COMPILADOS.items() if any(p.search(t) for p in patrones)]


def explicar(problemas: dict[str, list[str]]) -> str:
    """Mensaje en palabras sencillas. `problemas` = {'título': ['contacto'], 'descripción': [...]}"""
    partes = []
    for campo, lista in problemas.items():
        if lista:
            partes.append(f"en el {campo} quita " + " y ".join(MENSAJES[m] for m in lista))
    return ("Tu reto no se pudo publicar: " + "; ".join(partes) +
            ". Por seguridad, la comunicación y los pagos se hacen dentro de Crisálida.")