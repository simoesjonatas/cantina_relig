# carrinho.py
# O carrinho vive na sessão: o cliente não tem login, e assim ele sobrevive
# à navegação entre o cardápio e a finalização sem precisar de conta.
from decimal import Decimal

from .models import Produto, Combo
from .utils import chave_combo, ler_chave_combo

CHAVE = "carrinho"
CHAVE_PEDIDOS = "meus_pedidos"
LIMITE_HISTORICO = 20

# O que o combo precisa junto para fazer as contas de preço e estoque sem
# voltar ao banco a cada linha.
COMBO_COMPLETO = (
    "itens__produto__componentes__insumo",
    "escolhas__opcoes__produto__componentes__insumo",
)


def _vazio():
    return {"produtos": {}, "combos": {}}


def ler(sessao):
    """
    Lê o carrinho da sessão. Um combo é identificado pelo combo + o que foi
    escolhido nele (ver utils.chave_combo): assim dois “Combo Duplo”, um com
    Coca e outro com Coca Zero, são duas linhas e não uma com quantidade 2.
    """
    dados = sessao.get(CHAVE) or _vazio()
    dados.setdefault("produtos", {})
    # carrinho salvo antes das escolhas guardava {combo: quantidade}
    dados["combos"] = {
        chave: (valor if isinstance(valor, dict) else {"qtd": valor})
        for chave, valor in (dados.get("combos") or {}).items()
    }
    return dados


def _gravar(sessao, dados):
    sessao[CHAVE] = dados
    sessao.modified = True


def _combo_da_chave(chave):
    combo_pk, escolhas = ler_chave_combo(chave)
    if not combo_pk:
        return None, {}
    combo = Combo.objects.filter(pk=combo_pk, ativo=True).prefetch_related(*COMBO_COMPLETO).first()
    return combo, escolhas


def montar_linha_combo(combo, escolhas):
    """
    Preço e rótulos de um combo com estas escolhas. Devolve None se alguma
    escolha obrigatória ficou sem opção válida — aí a linha não existe.
    """
    escolhidos, unit = [], combo.preco
    for escolha in combo.escolhas.all():
        opcao = escolha.opcao(escolhas.get(escolha.pk))
        if not opcao:
            return None
        escolhidos.append({
            "escolha": escolha, "rotulo": escolha.nome,
            "produto": opcao.produto, "qtd": escolha.quantidade,
        })
        unit += opcao.adicional * escolha.quantidade
    return {"escolhas": escolhidos, "unit": unit}


def _limite(tipo, chave):
    """Quanto dá para levar desse item, pelo estoque."""
    if tipo == "produtos":
        p = (
            Produto.objects.filter(pk=chave, ativo=True, insumo=False)
            .prefetch_related("componentes__insumo")
            .first()
        )
        return p.estoque_disponivel if p else 0

    combo, escolhas = _combo_da_chave(chave)
    if not combo or not combo.montavel:
        return 0
    if montar_linha_combo(combo, escolhas) is None:
        return 0
    return combo.quantos_cabem_com(escolhas)


def ajustar(sessao, tipo, chave, delta=None, quantidade=None):
    """Soma delta ou fixa a quantidade. Nunca passa do estoque."""
    dados = ler(sessao)
    chave = str(chave)
    linha = dados[tipo].get(chave)
    atual = (linha["qtd"] if isinstance(linha, dict) else linha) or 0
    nova = quantidade if quantidade is not None else atual + delta

    teto = _limite(tipo, chave)
    nova = max(0, min(nova, teto))

    if nova:
        dados[tipo][chave] = {"qtd": nova} if tipo == "combos" else nova
    else:
        dados[tipo].pop(chave, None)
    _gravar(sessao, dados)
    return nova


def adicionar_combo(sessao, combo_pk, escolhas=None, delta=1):
    """Põe um combo no carrinho já com as escolhas feitas."""
    return ajustar(sessao, "combos", chave_combo(combo_pk, escolhas), delta=delta)


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

    produtos = (
        Produto.objects.filter(pk__in=dados["produtos"].keys(), ativo=True, insumo=False)
        .prefetch_related("componentes__insumo")
    )
    for p in produtos:
        pedida = dados["produtos"][str(p.pk)]
        teto = p.estoque_disponivel
        qtd = min(pedida, teto)
        if qtd != pedida:
            ajustado = True
        if qtd <= 0:
            continue
        linhas.append({
            "tipo": "produtos", "chave": str(p.pk), "obj": p, "nome": p.nome, "foto": p.foto,
            "qtd": qtd, "unit": p.preco, "subtotal": p.preco * qtd, "teto": teto,
            "escolhas": [],
        })
        total += p.preco * qtd

    chaves = list(dados["combos"].keys())
    pedidos_por_combo = {}
    for chave in chaves:
        combo_pk, escolhas = ler_chave_combo(chave)
        if combo_pk:
            pedidos_por_combo[chave] = (combo_pk, escolhas)

    combos = {
        c.pk: c
        for c in Combo.objects.filter(
            pk__in={pk for pk, _ in pedidos_por_combo.values()}, ativo=True
        ).prefetch_related(*COMBO_COMPLETO)
    }

    for chave in chaves:
        if chave not in pedidos_por_combo:
            ajustado = True
            continue
        combo_pk, escolhas = pedidos_por_combo[chave]
        combo = combos.get(combo_pk)
        montada = montar_linha_combo(combo, escolhas) if combo else None
        if not montada:
            ajustado = True
            continue

        pedida = dados["combos"][chave]["qtd"]
        teto = combo.quantos_cabem_com(escolhas)
        qtd = min(pedida, teto)
        if qtd != pedida:
            ajustado = True
        if qtd <= 0:
            continue
        unit = montada["unit"]
        linhas.append({
            "tipo": "combos", "chave": chave, "obj": combo, "nome": combo.nome, "foto": combo.foto,
            "qtd": qtd, "unit": unit, "subtotal": unit * qtd, "teto": teto,
            "escolhas": montada["escolhas"],
        })
        total += unit * qtd

    # se algo foi cortado ou sumiu, a sessão precisa refletir isso
    novos = {"produtos": {}, "combos": {}}
    for l in linhas:
        if l["tipo"] == "produtos":
            novos["produtos"][l["chave"]] = l["qtd"]
        else:
            novos["combos"][l["chave"]] = {"qtd": l["qtd"]}
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
