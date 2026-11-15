import pytest

from src.classificador import Classificador
from src.precos import avaliar, conta_margem, referencia_de
from src.regiao import regiao_aceita, zona_de
from src.texto import detectar_armazenamento, normalizar, parse_preco


@pytest.mark.parametrize("entrada,esperado", [
    ("R$ 2.500", 2500), ("2.500,90", 2500.9), (1800, 1800), ("R$ 950", 950), ("", None), (None, None), (0, None),
])
def test_parse_preco(entrada, esperado):
    assert parse_preco(entrada) == esperado


def test_armazenamento():
    assert detectar_armazenamento(normalizar("iPhone 13 128 GB azul")) == "128GB"
    assert detectar_armazenamento("macbook air m1 1tb") == "1TB"
    assert detectar_armazenamento("iphone 13") is None


@pytest.mark.parametrize("titulo,item,motivo_contem", [
    ("iPhone 13 128GB Azul impecável", "iphone-13", None),
    ("iPhone 13 Pro Max 256gb", "iphone-13-pro", None),
    ("Iphone 13 mini 128", None, "nenhum produto"),
    ("Capa iPhone 13 silicone", "iphone-13", "acessório"),
    ("iPhone 13 com capa e película", "iphone-13", None),
    ("iPhone 12 sem nenhum defeito", "iphone-12", None),
    ("iPhone 12 com defeito na tela", "iphone-12", "defeito"),
    ("iPhone 11 bloqueado icloud", "iphone-11", "bloquead"),
    ("Compro iPhone 14", "iphone-14", "compro"),
    ("PS5 Slim mídia física + 2 controles", "ps5", None),
    ("Controle PS5 DualSense", "ps5", "acessório"),
    ("Nintendo Switch OLED branco", "switch-oled", None),
    ("Nintendo Switch V2 desbloqueado", "switch-v2", None),
    ("Xbox Series S 512GB", "xbox-series-s", None),
    ("Galaxy S23 Ultra 256", None, "nenhum produto"),
    ("Samsung Galaxy S23 FE 128gb", "galaxy-s23", None),
    ("MacBook Air M1 8GB 256GB", "macbook-air-m1", None),
    ("Placa de vídeo RTX 3060 12GB", "rtx-3060", None),
])
def test_classificador(catalogo, regras, titulo, item, motivo_contem):
    c = Classificador(catalogo, regras).classificar(titulo, 2000)
    assert c.chave_item == item
    if motivo_contem is None:
        assert c.motivo_exclusao is None, c.motivo_exclusao
    else:
        assert c.motivo_exclusao and motivo_contem in c.motivo_exclusao


def test_preco_minimo(catalogo, regras):
    c = Classificador(catalogo, regras).classificar("iPhone 13 128gb", 300)
    assert "mínimo" in c.motivo_exclusao


def test_regiao(regras):
    assert zona_de("Rio de Janeiro", "Tijuca") == "Zona Norte"
    assert zona_de("Rio de Janeiro", "Copacabana") == "Zona Sul"
    assert zona_de("Niterói", "Icaraí") == "Niterói"
    assert regiao_aceita("Rio de Janeiro", "Méier", regras) == (True, "Zona Norte")
    assert regiao_aceita("Duque de Caxias", "Centro", regras)[0] is False
    assert regiao_aceita("São Gonçalo", "Alcântara", regras)[0] is False
    ok, zona = regiao_aceita("Rio de Janeiro", "Bairro Inexistente", regras)
    assert ok and "não mapeado" in zona
    regras2 = {**regras, "zonas_aceitas": ["Zona Norte", "Centro"]}
    assert regiao_aceita("Rio de Janeiro", "Leblon", regras2)[0] is False


def test_referencia_remove_extremos():
    ref = referencia_de([2000, 2100, 2200, 2300, 2400, 150, 9000])
    assert ref.n == 5 and ref.mediana == 2200 and ref.menor == 2000


def test_conta_margem(regras):
    lucro, margem = conta_margem(1500, 2300, regras)
    # 2300 * 0.93 = 2139 - 1500 - 40 = 599
    assert round(lucro) == 599 and round(margem) == 40
