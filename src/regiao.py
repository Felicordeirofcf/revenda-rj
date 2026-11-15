"""Mapeia bairro -> zona do Rio de Janeiro e decide se o anúncio está numa região aceita."""

from __future__ import annotations

from .texto import normalizar

_ZONAS: dict[str, list[str]] = {
    "Zona Sul": [
        "Botafogo", "Catete", "Copacabana", "Cosme Velho", "Flamengo", "Gávea", "Glória", "Humaitá",
        "Ipanema", "Jardim Botânico", "Lagoa", "Laranjeiras", "Leblon", "Leme", "Rocinha",
        "São Conrado", "Urca", "Vidigal",
    ],
    "Centro": [
        "Centro", "Lapa", "Santa Teresa", "Saúde", "Gamboa", "Santo Cristo", "Cidade Nova", "Estácio",
        "Rio Comprido", "Catumbi", "Caju", "Paquetá",
    ],
    "Barra/Jacarepaguá": [
        "Barra da Tijuca", "Barra Olímpica", "Recreio dos Bandeirantes", "Recreio", "Jacarepaguá",
        "Taquara", "Freguesia", "Freguesia (Jacarepaguá)", "Pechincha", "Tanque", "Anil",
        "Gardênia Azul", "Cidade de Deus", "Curicica", "Praça Seca", "Vila Valqueire", "Itanhangá",
        "Joá", "Camorim", "Vargem Grande", "Vargem Pequena", "Grumari",
    ],
    "Zona Oeste": [
        "Bangu", "Campo Grande", "Santa Cruz", "Realengo", "Padre Miguel", "Senador Camará",
        "Guaratiba", "Pedra de Guaratiba", "Barra de Guaratiba", "Sepetiba", "Cosmos", "Inhoaíba",
        "Paciência", "Santíssimo", "Senador Vasconcelos", "Deodoro", "Vila Militar",
        "Magalhães Bastos", "Jardim Sulacap", "Campo dos Afonsos", "Gericinó",
    ],
    "Zona Norte": [
        "Tijuca", "Vila Isabel", "Grajaú", "Andaraí", "Maracanã", "Praça da Bandeira",
        "Alto da Boa Vista", "Méier", "Engenho Novo", "Lins de Vasconcelos", "Cachambi",
        "Todos os Santos", "Engenho de Dentro", "Abolição", "Pilares", "Piedade", "Encantado",
        "Água Santa", "Riachuelo", "Rocha", "Sampaio", "São Francisco Xavier", "Jacaré",
        "Maria da Graça", "Del Castilho", "Inhaúma", "Engenho da Rainha", "Tomás Coelho",
        "Higienópolis", "Bonsucesso", "Ramos", "Olaria", "Penha", "Penha Circular", "Brás de Pina",
        "Cordovil", "Parada de Lucas", "Vigário Geral", "Jardim América", "Irajá", "Vista Alegre",
        "Vila da Penha", "Vicente de Carvalho", "Vila Kosmos", "Colégio", "Madureira",
        "Oswaldo Cruz", "Bento Ribeiro", "Marechal Hermes", "Cascadura", "Campinho", "Cavalcanti",
        "Engenheiro Leal", "Quintino Bocaiúva", "Turiaçu", "Rocha Miranda", "Honório Gurgel",
        "Coelho Neto", "Acari", "Barros Filho", "Costa Barros", "Pavuna", "Guadalupe", "Anchieta",
        "Parque Anchieta", "Ricardo de Albuquerque", "Ilha do Governador", "Jardim Guanabara",
        "Cacuia", "Portuguesa", "Pitangueiras", "Bancários", "Moneró", "Tauá", "Cocotá", "Zumbi",
        "Jardim Carioca", "Galeão", "Ribeira", "Praia da Bandeira", "Maré", "Manguinhos", "Benfica",
        "São Cristóvão", "Mangueira", "Vasco da Gama", "Complexo do Alemão", "Jacarezinho",
    ],
}

BAIRRO_PARA_ZONA: dict[str, str] = {
    normalizar(b): zona for zona, bairros in _ZONAS.items() for b in bairros
}

ZONA_DESCONHECIDA = "Rio (bairro não mapeado)"


def zona_de(cidade: str | None, bairro: str | None) -> str | None:
    """Zona para exibição/filtro. None se a cidade não for Rio nem Niterói."""
    c = normalizar(cidade)
    if c == "niteroi":
        return "Niterói"
    if c != "rio de janeiro":
        return None
    return BAIRRO_PARA_ZONA.get(normalizar(bairro), ZONA_DESCONHECIDA)


def regiao_aceita(cidade: str | None, bairro: str | None, regras: dict) -> tuple[bool, str | None]:
    municipios = {normalizar(m) for m in regras.get("municipios_aceitos", [])}
    if normalizar(cidade) not in municipios:
        return False, None
    zona = zona_de(cidade, bairro)
    if zona is None:  # município aceito mas fora do mapeamento (ex.: outra cidade adicionada)
        return True, cidade
    if zona == ZONA_DESCONHECIDA:
        return bool(regras.get("aceitar_bairro_desconhecido", True)), zona
    return zona in set(regras.get("zonas_aceitas", [])), zona
