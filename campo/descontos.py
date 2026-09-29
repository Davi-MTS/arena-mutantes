"""Regras de preço de uma distribuidora (campo de jogo da Arena)."""


def subtotal(itens):
    """Soma preco * quantidade de cada item. Lista vazia -> 0.0."""
    total = 0.0
    for item in itens:
        total += item["preco"] * item["quantidade"]
    return round(total, 2)


def desconto_volume(quantidade_total):
    """Percentual de desconto por volume:
    >= 100 unidades -> 10%; >= 50 unidades -> 5%; abaixo de 50 -> 0%."""
    if quantidade_total >= 100:
        return 0.10
    if quantidade_total >= 50:
        return 0.05
    return 0.0


def aplicar_cupom(valor, cupom):
    """Cupons: 'PRIMEIRA10' tira 10% do valor; 'MENOS20' tira R$ 20,00 fixos
    somente se o valor for maior ou igual a R$ 100,00. Cupom desconhecido ou
    None nao altera o valor. O resultado nunca e negativo."""
    if cupom == "PRIMEIRA10":
        valor = valor * 0.90
    elif cupom == "MENOS20" and valor >= 100:
        valor = valor - 20
    return round(max(valor, 0.0), 2)


def frete(subtotal_pedido, uf):
    """Frete: gratis para GO com subtotal >= R$ 300,00. Senao: GO paga R$ 15,00,
    DF paga R$ 25,00 e qualquer outra UF paga R$ 40,00."""
    if uf == "GO" and subtotal_pedido >= 300:
        return 0.0
    if uf == "GO":
        return 15.0
    if uf == "DF":
        return 25.0
    return 40.0


def total_pedido(itens, uf, cupom=None):
    """Total = subtotal com desconto de volume, depois cupom, depois soma o frete.
    O frete e calculado sobre o subtotal ORIGINAL (antes dos descontos)."""
    base = subtotal(itens)
    quantidade = sum(item["quantidade"] for item in itens)
    com_volume = base * (1 - desconto_volume(quantidade))
    com_cupom = aplicar_cupom(com_volume, cupom)
    return round(com_cupom + frete(base, uf), 2)
