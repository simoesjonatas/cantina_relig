# views.py
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.forms import ModelForm, inlineformset_factory
from django.contrib import messages
from django.core.exceptions import ValidationError
from .models import Pedido, PedidoItem, Produto, ComandaCozinha

from decimal import Decimal
from django.views.decorators.http import require_POST
from .services import confirmar_pedido, concluir_pedido, cancelar_pedido  
from django.utils import timezone
from django.db.models import Sum

@require_POST
def cancelar_pedido_view(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    try:
        cancelar_pedido(pedido.id)  # devolve estoque + muda status
        messages.success(request, f"Pedido {pedido.numero} cancelado e estoque restaurado.")
    except ValidationError as e:
        messages.error(request, str(e))
    # volta para o detalhe do pedido
    return redirect("pedidos:detalhe", pk=pk)

@require_POST
def concluir_pedido_view(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    try:
        concluir_pedido(pedido.id)
        messages.success(request, f"Pedido {pedido.numero} concluído!")
    except ValidationError as e:
        messages.error(request, str(e))
    # volta pra cozinha se veio de lá; senão, para o detalhe
    next_url = request.POST.get("next") or "pedidos:detalhe"
    if next_url == "pedidos:cozinha":
        return redirect("pedidos:cozinha")
    return redirect("pedidos:detalhe", pk=pk)


def detalhe_pedido(request, pk):
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

    return render(request, "pedidos/detalhe_pedido.html", {
        "pedido": pedido,
        "itens": itens_ctx,
        "total": total,
    })


class PedidoForm(ModelForm):
    class Meta:
        model = Pedido
        fields = ["nome_cliente"]

class PedidoItemForm(ModelForm):
    class Meta:
        model = PedidoItem
        fields = ["produto", "quantidade"]  # sem preco_unitario no form

PedidoItemFormSet = inlineformset_factory(
    Pedido, PedidoItem, form=PedidoItemForm, extra=1, can_delete=True
)

def criar_pedido(request):
    if request.method == "POST":
        form = PedidoForm(request.POST)
        formset = PedidoItemFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            pedido = form.save()
            formset.instance = pedido
            itens = formset.save(commit=False)

            for it in itens:
                it.preco_unitario = it.produto.preco  # sempre do produto
                it.save()
            formset.save_m2m()

            # 🔑 já calcula o total agora (antes mesmo de confirmar)
            pedido.recalcular_total()

            messages.success(request, "Pedido criado em rascunho.")
            return redirect("pedidos:detalhe", pk=pedido.pk)
    else:
        form = PedidoForm()
        formset = PedidoItemFormSet()

    # mapa para exibir preço automático no front
    preco_map = {p.id: float(p.preco) for p in Produto.objects.all()}
    return render(request, "pedidos/criar_pedido.html", {
        "form": form, "formset": formset, "preco_map": preco_map
    })


# def detalhe_pedido(request, pk):
#     pedido = get_object_or_404(Pedido, pk=pk)
#     return render(request, "pedidos/detalhe_pedido.html", {"pedido": pedido})

def confirmar_enviar(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    try:
        confirmar_pedido(pedido.id)
        messages.success(request, "Pedido confirmado e enviado à cozinha!")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("pedidos:detalhe", pk=pk)

def cozinha_painel(request):
    # mostra apenas pedidos enviados e não concluídos/cancelados
    comandas = ComandaCozinha.objects.select_related("pedido").filter(
        pedido__status__in=[Pedido.Status.ENVIADO_COZINHA]
    ).order_by("impresso_em")
    return render(request, "pedidos/cozinha.html", {"comandas": comandas})


def home(request):
    hoje = timezone.localdate()
    qs_hoje = Pedido.objects.filter(criado_em__date=hoje)
    resumo = {
        "hoje_pedidos": qs_hoje.count(),
        "hoje_concluidos": qs_hoje.filter(status=Pedido.Status.CONCLUIDO).count(),
        "hoje_total": qs_hoje.aggregate(s=Sum("total"))["s"] or 0,
    }
    ultimos = Pedido.objects.order_by("-criado_em")[:10]
    return render(request, "home.html", {"resumo": resumo, "ultimos": ultimos})
