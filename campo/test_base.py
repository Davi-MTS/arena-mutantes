"""Suíte inicial propositalmente fraca: o Mutante começa com vantagem."""
from descontos import subtotal, total_pedido


def test_subtotal_simples():
    assert subtotal([{"preco": 10.0, "quantidade": 3}]) == 30.0


def test_total_pedido_go_sem_cupom():
    itens = [{"preco": 5.0, "quantidade": 10}]
    assert total_pedido(itens, "GO") == 65.0
