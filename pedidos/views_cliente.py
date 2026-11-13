from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from .forms import PedidoForm, PedidoItemFormSet, PedidoComboFormSet
from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Pedido
from .services import registrar_escolhas
from .utils import texto_para_escolhas
from .views import _combos_disponiveis

def pedido_novo_cliente(request):
    if request.method == "POST":
        form = PedidoForm(request.POST)
        formset = PedidoItemFormSet(request.POST)
        formset_combos = PedidoComboFormSet(request.POST)
        if form.is_valid() and formset.is_valid() and formset_combos.is_valid():
            pedido = form.save(commit=False)
            pedido.status = Pedido.Status.RASCUNHO  # cliente sempre começa em RASC
            pedido.save()

            formset.instance = pedido
            for it in formset.save(commit=False):
                it.preco_unitario = it.produto.preco
                it.save()

            formset_combos.instance = pedido
            for i, f in enumerate(formset_combos.forms):
                dados = getattr(f, "cleaned_data", None) or {}
                if not dados.get("combo") or not dados.get("quantidade") or dados.get("DELETE"):
                    continue
                pc = f.save(commit=False)
                pc.pedido = pedido
                pc.preco_unitario = pc.combo.preco
                pc.save()
                extra = registrar_escolhas(
                    pc, texto_para_escolhas(request.POST.get(f"combos-{i}-escolhas", ""))
                )
                if extra:
                    pc.preco_unitario = pc.combo.preco + extra
                    pc.save(update_fields=["preco_unitario"])

            pedido.recalcular_total()

            return redirect("pedidos:cliente_pedido_detalhe", pk=pedido.pk)
    else:
        form = PedidoForm()
        formset = PedidoItemFormSet()
        formset_combos = PedidoComboFormSet()

    return render(request, "cliente/pedido_novo.html", {
        "form": form,
        "formset": formset,
        "formset_combos": formset_combos,
        "combos": _combos_disponiveis(),
    })

def pedido_cliente_detalhe(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)

    itens_ctx = pedido.linhas()
    total = sum((l["subtotal"] for l in itens_ctx), Decimal("0.00"))

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

    itens_ctx = pedido.linhas()
    total = sum((l["subtotal"] for l in itens_ctx), Decimal("0.00"))

    # se por algum motivo o total estiver divergente, ajusta
    if pedido.total != total:
        pedido.total = total
        pedido.save(update_fields=["total", "atualizado_em"])

    return render(request, "cliente/pedido_pagamento.html", {
        "pedido": pedido,
        "itens": itens_ctx,
        "total": total,
    })


def pedido_cliente_status(request, pk):
    """Só o status, para a tela do cliente saber quando algo mudou."""
    pedido = get_object_or_404(Pedido, pk=pk)
    return JsonResponse({"status": pedido.status})
