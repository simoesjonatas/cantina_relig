from django.shortcuts import render, redirect, get_object_or_404
from .forms import PedidoForm, PedidoItemFormSet
from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Pedido

def pedido_novo_cliente(request):
    if request.method == "POST":
        form = PedidoForm(request.POST)
        formset = PedidoItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            pedido = form.save(commit=False)
            pedido.status = Pedido.Status.RASCUNHO  # cliente sempre começa em RASC
            pedido.save()

            formset.instance = pedido
            itens = formset.save(commit=False)
            for it in itens:
                it.preco_unitario = it.produto.preco
                it.save()

            pedido.recalcular_total()

            return redirect("pedidos:cliente_pedido_detalhe", pk=pedido.pk)
    else:
        form = PedidoForm()
        formset = PedidoItemFormSet()

    return render(request, "cliente/pedido_novo.html", {
        "form": form,
        "formset": formset
    })

def pedido_cliente_detalhe(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)

    itens_ctx = []
    total = Decimal("0.00")

    for it in pedido.itens.select_related("produto"):
        subtotal = it.preco_unitario * it.quantidade
        itens_ctx.append({
            "nome": it.produto.nome,
            "qtd": it.quantidade,
            "unit": it.preco_unitario,
            "subtotal": subtotal,
        })
        total += subtotal

    # se por algum motivo o total estiver divergente, ajusta
    if pedido.total != total:
        pedido.total = total
        pedido.save(update_fields=["total", "atualizado_em"])

    return render(request, "cliente/pedido_detalhe.html", {
        "pedido": pedido,
        "itens": itens_ctx,
        "total": total,
    })

def pedido_cliente_enviar_pagamento(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)

    if pedido.status != Pedido.Status.RASCUNHO:
        messages.error(request, "Este pedido já foi enviado.")
        return redirect("pedidos:cliente_pedido_detalhe", pk=pk)

    pedido.status = Pedido.Status.PAGAMENTO
    # pedido.gerar_token_publico()
    pedido.save(update_fields=["status"])

    messages.success(request, "Seu pedido foi enviado para pagamento! Vá ao caixa.")
    return redirect("pedidos:cliente_pedido_pagamento", pk=pk)



def pedido_cliente_pagamento(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)

    # Garante que só aparece se estiver aguardando pagamento
    if pedido.status != Pedido.Status.PAGAMENTO:
        return redirect("pedidos:cliente_pedido_detalhe", pk=pk)

    itens_ctx = []
    total = Decimal("0.00")

    for it in pedido.itens.select_related("produto"):
        subtotal = it.preco_unitario * it.quantidade
        itens_ctx.append({
            "nome": it.produto.nome,
            "qtd": it.quantidade,
            "unit": it.preco_unitario,
            "subtotal": subtotal,
        })
        total += subtotal

    # se por algum motivo o total estiver divergente, ajusta
    if pedido.total != total:
        pedido.total = total
        pedido.save(update_fields=["total", "atualizado_em"])

    return render(request, "cliente/pedido_pagamento.html", {
        "pedido": pedido,
        "itens": itens_ctx,
        "total": total,
    })
