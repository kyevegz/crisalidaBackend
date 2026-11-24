"""Filtros de seguridad de los retos (RN-02): rechazan datos de contacto, direcciones, pagos fuera de la app y texto basura."""
import pytest

from filtros_retos import explicar, motivos


@pytest.mark.parametrize("texto", [
    "Escríbeme a ana.lopez@gmail.com para los detalles",
    "Mi whatsapp es 4621234567",
    "Llámame al 462 123 45 67",
    "Entra a https://mitienda.com/pedido",
    "Búscame en instagram como @ana_artesana",
    "Mándame mensaje por privado",
])
def test_rechaza_datos_de_contacto(texto):
    assert "contacto" in motivos(texto)


@pytest.mark.parametrize("texto", [
    "Entrega en Calle Hidalgo 123",
    "Mi domicilio está cerca del mercado",
    "C.P. 36900",
])
def test_rechaza_direcciones_exactas(texto):
    assert "direccion" in motivos(texto)


@pytest.mark.parametrize("texto", [
    "Págame por adelantado y te mando el material",
    "Depositame en mi cuenta bancaria",
    "Hay una cuota de inscripción de 200 pesos",
])
def test_rechaza_pagos_fuera_de_la_app(texto):
    assert "dinero" in motivos(texto)


@pytest.mark.parametrize("texto", [
    "aaaaaaaaaa",
    "hola hola hola hola hola",
])
def test_rechaza_texto_repetido(texto):
    assert "repetido" in motivos(texto)


@pytest.mark.parametrize("texto", [
    "Captura de 40 productos en una hoja de cálculo",
    "Pasar a una hoja de cálculo el nombre, precio y existencia de 40 productos",
    "Diseñar un cartel para la feria del barrio",
    "Redactar tres descripciones cortas para un catálogo de bordados",
])
def test_acepta_retos_normales(texto):
    assert motivos(texto) == []


def test_texto_vacio_o_nulo_no_tiene_problemas():
    assert motivos(None) == []
    assert motivos("") == []


def test_ignora_acentos_y_mayusculas():
    assert "contacto" in motivos("MI WHATSAPP ES 4621234567")
    assert "dinero" in motivos("PAGAME POR ADELANTADO")


def test_el_mensaje_explica_que_quitar():
    mensaje = explicar({"título": ["contacto"], "descripción": []})
    assert "en el título quita datos de contacto" in mensaje
    assert "descripción" not in mensaje
