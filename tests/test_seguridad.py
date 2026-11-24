"""Reglas de seguridad del backend (RF-01): PIN, código de recuperación, sesiones y cifrado."""
import time

import jwt
import pytest

import seguridad


# ---------------------------------------------------------------- reglas del PIN

@pytest.mark.parametrize("pin", ["483920", "907351", "260814"])
def test_pin_valido_se_acepta(pin):
    assert seguridad.validar_pin(pin) == pin


@pytest.mark.parametrize("pin", ["123456", "654321", "123123", "111111", "000000", "999999"])
def test_pin_facil_de_adivinar_se_rechaza(pin):
    with pytest.raises(ValueError, match="fácil de adivinar"):
        seguridad.validar_pin(pin)


@pytest.mark.parametrize("pin", ["", "12345", "1234567", "12345a", "abcdef", "48 392"])
def test_pin_con_formato_incorrecto_se_rechaza(pin):
    with pytest.raises(ValueError, match="6 dígitos"):
        seguridad.validar_pin(pin)


def test_bloqueo_tras_5_fallos_por_15_minutos():
    assert seguridad.MAX_INTENTOS == 5
    assert seguridad.MINUTOS_BLOQUEO == 15


# ---------------------------------------------------------------- hash del PIN

def test_el_hash_no_contiene_el_pin_y_verifica_el_correcto():
    h = seguridad.hashear_pin("483920")
    assert "483920" not in h
    assert seguridad.verificar_pin("483920", h) is True


def test_un_pin_incorrecto_no_verifica():
    h = seguridad.hashear_pin("483920")
    assert seguridad.verificar_pin("483921", h) is False


def test_dos_hashes_del_mismo_pin_son_distintos():
    assert seguridad.hashear_pin("483920") != seguridad.hashear_pin("483920")


def test_un_hash_invalido_no_rompe_la_verificacion():
    assert seguridad.verificar_pin("483920", "esto-no-es-un-hash") is False


# ---------------------------------------------------------------- código de recuperación

def test_codigo_de_recuperacion_tiene_formato_correcto():
    codigo = seguridad.generar_codigo_recuperacion()
    assert len(codigo) == seguridad.LONGITUD_CODIGO
    assert set(codigo) <= set(seguridad.ALFABETO_CODIGO)
    assert not set(codigo) & set("01OI")  # sin caracteres que se confunden


def test_codigo_se_normaliza_mayusculas_espacios_y_guiones():
    assert seguridad.normalizar_codigo("k7m-3qx") == "K7M3QX"
    assert seguridad.normalizar_codigo(" k7m 3qx ") == "K7M3QX"


def test_codigo_verifica_aunque_se_escriba_distinto():
    h = seguridad.hashear_codigo("K7M3QX")
    assert seguridad.verificar_codigo("k7m-3qx", h) is True
    assert seguridad.verificar_codigo("K7M3QY", h) is False


def test_un_codigo_no_se_puede_usar_como_pin():
    h = seguridad.hashear_codigo("483920")
    assert seguridad.verificar_pin("483920", h) is False


# ---------------------------------------------------------------- sesiones (JWT)

def test_token_normal_lleva_modo_rol_y_version():
    t = seguridad.crear_token("u-1", "normal", "compradora", 3)
    datos = seguridad.decodificar_token(t)
    assert datos["sub"] == "u-1"
    assert datos["modo"] == "normal"
    assert datos["rol"] == "compradora"
    assert datos["sv"] == 3


def test_token_de_camuflaje_se_distingue_del_normal():
    datos = seguridad.decodificar_token(seguridad.crear_token("u-1", "camuflaje"))
    assert datos["modo"] == "camuflaje"


def test_token_manipulado_se_rechaza():
    t = seguridad.crear_token("u-1", "normal")
    with pytest.raises(jwt.InvalidTokenError):
        seguridad.decodificar_token(t[:-3] + "abc")


def test_token_firmado_con_otra_llave_se_rechaza():
    falso = jwt.encode({"sub": "u-1", "modo": "normal"}, "otra-llave-distinta-de-32-caracteres-o-mas", algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        seguridad.decodificar_token(falso)


def test_token_vencido_se_rechaza():
    vencido = jwt.encode({"sub": "u-1", "exp": int(time.time()) - 10}, seguridad.JWT_SECRET, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        seguridad.decodificar_token(vencido)


def test_pase_de_registro_tiene_modo_registro():
    datos = seguridad.decodificar_token(seguridad.crear_token_registro("mariposa"))
    assert datos["modo"] == "registro"
    assert datos["sub"] == "mariposa"


# ---------------------------------------------------------------- cifrado AES-256-GCM

def test_cifrar_y_descifrar_devuelve_el_texto_original():
    texto = "Mi dirección privada: calle ñandú 5, ¡ojo! 🌸"
    cifrado = seguridad.cifrar_texto(texto)
    assert texto not in cifrado
    assert seguridad.descifrar_texto(cifrado) == texto


def test_cada_cifrado_usa_un_nonce_distinto():
    assert seguridad.cifrar_texto("hola") != seguridad.cifrar_texto("hola")


def test_un_texto_cifrado_alterado_no_se_descifra():
    cifrado = seguridad.cifrar_texto("hola")
    alterado = ("A" if cifrado[20] != "A" else "B").join([cifrado[:20], cifrado[21:]])
    with pytest.raises(Exception):
        seguridad.descifrar_texto(alterado)
