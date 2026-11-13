# views_cardapio.py
# Cardápio público: o cliente navega, enche o carrinho e só no fim informa
# o nome e se come no local ou leva. Sem login em nenhum passo.
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from . import carrinho as cart
from .models import Produto, Combo, Pedido, PedidoItem, PedidoCombo, Categoria
from .services import registrar_escolhas
from .utils import chave_combo, ler_chave_combo, escolhas_do_post


def _pedidos_abertos(sessao):
    """Pedidos desta sessão que ainda estão acontecendo, do mais novo ao mais velho."""
    ids = cart.ids_dos_pedidos(sessao)
    if not ids:
        return []
    achados = {
        p.pk: p
        for p in Pedido.objects.filter(pk__in=ids).exclude(status=Pedido.Status.CANCELADO)
    }
    return [achados[i] for i in ids if i in achados][:3]


def cardapio(request):
    # insumo (o disco de hambúrguer, por exemplo) não é vendido sozinho
    produtos = (
        Produto.objects.filter(ativo=True, insumo=False)
        .select_related("categoria")
        .prefetch_related("componentes__insumo")
        .order_by("nome")
    )
    combos = [
        c for c in Combo.objects.filter(ativo=True)
        .prefetch_related(*cart.COMBO_COMPLETO).order_by("nome")
        if c.montavel
    ]
    resumo = cart.detalhar(request.session)
    if resumo["ajustado"]:
        messages.warning(request, "Ajustamos o carrinho: algum item saiu do cardápio ou acabou.")

    # marca em cada item quanto já está no carrinho; o template não tem
    # como procurar numa chave de dicionário
    no_carrinho = {(l["tipo"], l["chave"]): l["qtd"] for l in resumo["linhas"]}
    produtos = list(produtos)   # precisa materializar para marcar e para agrupar
    for p in produtos:
        p.escolhido = no_carrinho.get(("produtos", str(p.pk)), 0)
        p.sobra = p.estoque_disponivel
    for c in combos:
        # combo com escolha vira uma linha por combinação, então o cartão
        # soma todas elas só para dizer quantos já foram para o carrinho
        c.escolhido = sum(
            qtd for (tipo, chave), qtd in no_carrinho.items()
            if tipo == "combos" and ler_chave_combo(chave)[0] == c.pk
        )
        c.sobra = c.quantos_cabem

    # agrupa na ordem definida em Categoria; quem não tem vai para "Outros",
    # no fim, para nenhum produto sumir do cardápio
    secoes = []
    for cat in Categoria.objects.all():
        itens = [p for p in produtos if p.categoria_id == cat.id]
        if itens:
            secoes.append({"id": f"cat-{cat.id}", "nome": cat.nome, "itens": itens})
    soltos = [p for p in produtos if p.categoria_id is None]
    if soltos:
        secoes.append({"id": "cat-outros", "nome": "Outros" if secoes else "Itens", "itens": soltos})

    return render(request, "cardapio/cardapio.html", {
        "secoes": secoes,
        "combos": combos,
        "resumo": resumo,
        "pedidos_abertos": _pedidos_abertos(request.session),
    })


@require_POST
def cardapio_adicionar(request):
    tipo = request.POST.get("tipo")
    if tipo not in ("produtos", "combos"):
        return redirect("pedidos:cardapio")

    voltar = request.POST.get("voltar") or "pedidos:cardapio"

    if tipo == "combos":
        # a linha do carrinho é o combo + o que foi escolhido nele; o cardápio
        # manda as escolhas, o carrinho manda a chave que já existe
        chave = request.POST.get("chave")
        if not chave:
            combo_pk = request.POST.get("pk")
            combo = Combo.objects.filter(pk=combo_pk, ativo=True).prefetch_related("escolhas").first()
            if not combo:
                return redirect("pedidos:cardapio")
            escolhas = escolhas_do_post(request.POST)
            faltando = [e.nome for e in combo.escolhas.all() if not escolhas.get(e.pk)]
            if faltando:
                messages.error(request, f"Antes de adicionar, escolha: {', '.join(faltando)}.")
                return redirect(voltar)
            chave = chave_combo(combo_pk, escolhas)
        alvo = chave
    else:
        alvo = request.POST.get("pk")

    if not alvo:
        return redirect("pedidos:cardapio")

    if request.POST.get("quantidade") not in (None, ""):
        qtd = cart.ajustar(request.session, tipo, alvo, quantidade=int(request.POST["quantidade"]))
    else:
        qtd = cart.ajustar(request.session, tipo, alvo, delta=int(request.POST.get("delta", 1)))

    resumo = cart.detalhar(request.session)
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({
            "quantidade": qtd,
            "itens": resumo["itens"],
            "total": f'{resumo["total"]:.2f}'.replace(".", ","),
        })
    return redirect(voltar)


def carrinho_ver(request):
    resumo = cart.detalhar(request.session)
    if resumo["ajustado"]:
        messages.warning(request, "Ajustamos o carrinho: algum item saiu do cardápio ou acabou.")
    return render(request, "cardapio/carrinho.html", {
        "resumo": resumo,
        "pedidos_abertos": _pedidos_abertos(request.session),
    })


def finalizar(request):
    resumo = cart.detalhar(request.session)
    if not resumo["linhas"]:
        messages.error(request, "Seu carrinho está vazio.")
        return redirect("pedidos:cardapio")

    if request.method == "POST":
        nome = (request.POST.get("nome_cliente") or "").strip()
        consumo = request.POST.get("consumo") or Pedido.Consumo.LOCAL
        observacao = (request.POST.get("observacao") or "").strip()

        if not nome:
            messages.error(request, "Precisamos do seu nome para chamar quando ficar pronto.")
        elif consumo not in Pedido.Consumo.values:
            messages.error(request, "Escolha se vai comer no local ou levar.")
        else:
            with transaction.atomic():
                # já entra aguardando pagamento: quem clicou em "Enviar
                # pedido" no cardápio já confirmou, e o rascunho só somava
                # um clique a mais antes de ir ao caixa
                pedido = Pedido.objects.create(
                    nome_cliente=nome,
                    consumo=consumo,
                    observacao=observacao,
                    status=Pedido.Status.PAGAMENTO,
                )
                for l in resumo["linhas"]:
                    if l["tipo"] == "produtos":
                        PedidoItem.objects.create(
                            pedido=pedido, produto=l["obj"],
                            quantidade=l["qtd"], preco_unitario=l["unit"],
                        )
                    else:
                        pc = PedidoCombo.objects.create(
                            pedido=pedido, combo=l["obj"],
                            quantidade=l["qtd"], preco_unitario=l["unit"],
                        )
                        # congela a bebida que a pessoa escolheu; o preço já
                        # veio do carrinho com o adicional somado
                        registrar_escolhas(pc, ler_chave_combo(l["chave"])[1])
                pedido.recalcular_total()
            cart.esvaziar(request.session)
            cart.registrar_pedido(request.session, pedido.pk)
            return redirect("pedidos:cliente_pedido_pagamento", pk=pedido.pk)

    return render(request, "cardapio/finalizar.html", {
        "resumo": resumo,
        "consumos": Pedido.Consumo.choices,
        "nome_cliente": request.POST.get("nome_cliente", ""),
        "observacao": request.POST.get("observacao", ""),
    })


def meus_pedidos(request):
    """Os pedidos desta pessoa, pela sessão. Serve para ela acompanhar."""
    ids = cart.ids_dos_pedidos(request.session)
    encontrados = {
        p.pk: p
        for p in Pedido.objects.filter(pk__in=ids).prefetch_related(
            "itens__produto", "combos__combo", "combos__escolhas__produto"
        )
    }
    pedidos = [encontrados[i] for i in ids if i in encontrados]

    # pedido apagado some da lista, senão fica um fantasma para sempre
    if len(pedidos) != len(ids):
        request.session[cart.CHAVE_PEDIDOS] = [p.pk for p in pedidos]
        request.session.modified = True

    return render(request, "cardapio/meus_pedidos.html", {"pedidos": pedidos})
