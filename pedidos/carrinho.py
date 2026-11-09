# carrinho.py
# O carrinho vive na sessão: o cliente não tem login, e assim ele sobrevive
# à navegação entre o cardápio e a finalização sem precisar de conta.
from decimal import Decimal

from .models import Produto, Combo

CHAVE = "carrinho"
CHAVE_PEDIDOS = "meus_pedidos"
LIMITE_HISTORICO = 20


def _vazio():
    return {"produtos": {}, "combos": {}}


def ler(sessao):
    dados = sessao.get(CHAVE) or _vazio()
    dados.setdefault("produtos", {})
    dados.setdefault("combos", {})
    return dados


def _gravar(sessao, dados):
    sessao[CHAVE] = dados
    sessao.modified = True


def _limite(tipo, pk):
    """Quanto dá para levar desse item, pelo estoque."""
    if tipo == "produtos":
        p = Produto.objects.filter(pk=pk, ativo=True).first()
        return p.estoque if p else 0
    c = Combo.objects.filter(pk=pk, ativo=True).first()
    return c.quantos_cabem if c else 0


def ajustar(sessao, tipo, pk, delta=None, quantidade=None):
    """Soma delta ou fixa a quantidade. Nunca passa do estoque."""
    dados = ler(sessao)
    pk = str(pk)
    atual = dados[tipo].get(pk, 0)
    nova = quantidade if quantidade is not None else atual + delta

    teto = _limite(tipo, pk)
    nova = max(0, min(nova, teto))

    if nova:
        dados[tipo][pk] = nova
    else:
        dados[tipo].pop(pk, None)
    _gravar(sessao, dados)
    return nova


def esvaziar(sessao):
    _gravar(sessao, _vazio())


def detalhar(sessao):
    """
    Monta as linhas do carrinho com os objetos carregados. Já remove o que
    saiu do ar ou perdeu estoque desde que foi colocado — o cliente pode
    ter deixado a aba aberta.
    """
    dados = ler(sessao)
    linhas, total, ajustado = [], Decimal("0.00"), False

    produtos = Produto.objects.filter(pk__in=dados["produtos"].keys(), ativo=True)
    for p in produtos:
        pedida = dados["produtos"][str(p.pk)]
        qtd = min(pedida, p.estoque)
        if qtd != pedida:
            ajustado = True
        if qtd <= 0:
            continue
        linhas.append({
            "tipo": "produtos", "obj": p, "nome": p.nome, "foto": p.foto,
            "qtd": qtd, "unit": p.preco, "subtotal": p.preco * qtd, "teto": p.estoque,
        })
        total += p.preco * qtd

    combos = Combo.objects.filter(pk__in=dados["combos"].keys(), ativo=True).prefetch_related("itens__produto")
    for c in combos:
        pedida = dados["combos"][str(c.pk)]
        qtd = min(pedida, c.quantos_cabem)
        if qtd != pedida:
            ajustado = True
        if qtd <= 0:
            continue
        linhas.append({
            "tipo": "combos", "obj": c, "nome": c.nome, "foto": c.foto,
            "qtd": qtd, "unit": c.preco, "subtotal": c.preco * qtd, "teto": c.quantos_cabem,
        })
        total += c.preco * qtd

    # se algo foi cortado ou sumiu, a sessão precisa refletir isso
    novos = {"produtos": {}, "combos": {}}
    for l in linhas:
        novos[l["tipo"]][str(l["obj"].pk)] = l["qtd"]
    if novos != {"produtos": dados["produtos"], "combos": dados["combos"]}:
        _gravar(sessao, novos)
        ajustado = True

    return {"linhas": linhas, "total": total, "itens": sum(l["qtd"] for l in linhas), "ajustado": ajustado}


# --- pedidos que esta pessoa fez ------------------------------------------
# Sem login, a sessão é o que liga o cliente aos pedidos dele. Vale 14 dias
# e sobrevive a fechar o navegador, então ele acha o pedido depois de um F5
# ou de sair da página.

def registrar_pedido(sessao, pedido_id):
    ids = [i for i in sessao.get(CHAVE_PEDIDOS, []) if i != pedido_id]
    ids.insert(0, pedido_id)
    sessao[CHAVE_PEDIDOS] = ids[:LIMITE_HISTORICO]
    sessao.modified = True


def ids_dos_pedidos(sessao):
    return sessao.get(CHAVE_PEDIDOS, [])


def e_meu(sessao, pedido_id):
    return pedido_id in sessao.get(CHAVE_PEDIDOS, [])
