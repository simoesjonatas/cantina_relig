# views_combos.py
# CRUD de combos: conjuntos de produtos vendidos por um preço fechado.
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .forms import ComboForm, ComboItemFormSet
from .models import Combo, PedidoCombo, Produto


@login_required
def combo_lista(request):
    combos = Combo.objects.prefetch_related("itens__produto")

    busca = request.GET.get("q", "").strip()
    if busca:
        combos = combos.filter(nome__icontains=busca)

    combos = list(combos.order_by("nome"))
    return render(request, "combos/lista.html", {
        "combos": combos,
        "busca": busca,
        "resumo": {
            "total": Combo.objects.count(),
            "ativos": Combo.objects.filter(ativo=True).count(),
            "sem_estoque": sum(1 for c in combos if c.ativo and c.quantos_cabem == 0),
        },
    })


def _salvar(request, combo=None):
    if request.method == "POST":
        form = ComboForm(request.POST, instance=combo)
        formset = ComboItemFormSet(request.POST, instance=combo)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                combo = form.save()
                formset.instance = combo
                formset.save()
            verbo = "atualizado" if combo.pk else "criado"
            messages.success(request, f"Combo “{combo.nome}” {verbo}.")
            return None, None, redirect("pedidos:combo_lista")
    else:
        form = ComboForm(instance=combo)
        formset = ComboItemFormSet(instance=combo)
    return form, formset, None


def _precos():
    """Para a prévia no formulário mostrar quanto sairia avulso."""
    return {str(p.id): float(p.preco) for p in Produto.objects.filter(ativo=True)}


@login_required
def combo_criar(request):
    form, formset, resposta = _salvar(request)
    if resposta:
        return resposta
    return render(request, "combos/form.html", {
        "form": form, "formset": formset, "combo": None, "precos": _precos(),
    })


@login_required
def combo_editar(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    form, formset, resposta = _salvar(request, combo)
    if resposta:
        return resposta
    return render(request, "combos/form.html", {
        "form": form, "formset": formset, "combo": combo, "precos": _precos(),
    })


@login_required
@require_POST
def combo_alternar_ativo(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    combo.ativo = not combo.ativo
    combo.save(update_fields=["ativo"])
    estado = "disponível para venda" if combo.ativo else "desativado"
    messages.success(request, f"“{combo.nome}” agora está {estado}.")
    return redirect("pedidos:combo_lista")


@login_required
def combo_excluir(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    # combo já vendido não pode sumir: apagaria o histórico (PedidoCombo usa PROTECT)
    em_pedidos = PedidoCombo.objects.filter(combo=combo).count()

    if request.method == "POST":
        if em_pedidos:
            messages.error(
                request,
                f"“{combo.nome}” já foi vendido em {em_pedidos} pedido(s) e não pode ser "
                f"excluído. Use “Desativar” para tirá-lo do cardápio."
            )
            return redirect("pedidos:combo_lista")
        nome = combo.nome
        combo.delete()
        messages.success(request, f"Combo “{nome}” excluído.")
        return redirect("pedidos:combo_lista")

    return render(request, "combos/excluir.html", {"combo": combo, "em_pedidos": em_pedidos})
