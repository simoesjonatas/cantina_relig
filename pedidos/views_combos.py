# views_combos.py
# CRUD de combos: conjuntos de produtos vendidos por um preço fechado.
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .forms import ComboForm, ComboItemFormSet, ComboEscolhaForm, ComboEscolhaOpcaoFormSet
from .models import Combo, ComboEscolha, PedidoCombo, Produto


@login_required
def combo_lista(request):
    combos = Combo.objects.prefetch_related(
        "itens__produto__componentes__insumo",
        "escolhas__opcoes__produto__componentes__insumo",
    )

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
        form = ComboForm(request.POST, request.FILES, instance=combo)
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
    return {str(p.id): float(p.preco) for p in Produto.objects.filter(ativo=True, insumo=False)}


def _avulso_das_escolhas(combo):
    """
    Quanto as escolhas somam no preço avulso. Usa a opção mais barata de cada
    uma — é o piso: o cliente pode escolher algo mais caro.
    """
    if not combo:
        return 0.0
    total = 0.0
    for escolha in combo.escolhas.prefetch_related("opcoes__produto"):
        precos = [float(o.produto.preco) for o in escolha.opcoes.all()]
        if precos:
            total += min(precos) * escolha.quantidade
    return total


@login_required
def combo_criar(request):
    form, formset, resposta = _salvar(request)
    if resposta:
        return resposta
    return render(request, "combos/form.html", {
        "form": form, "formset": formset, "combo": None, "precos": _precos(),
        "avulso_escolhas": 0.0,
    })


@login_required
def combo_editar(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    form, formset, resposta = _salvar(request, combo)
    if resposta:
        return resposta
    return render(request, "combos/form.html", {
        "form": form, "formset": formset, "combo": combo, "precos": _precos(),
        "escolhas": combo.escolhas.prefetch_related("opcoes__produto"),
        "avulso_escolhas": _avulso_das_escolhas(combo),
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


# --- escolhas do combo -----------------------------------------------------
# “Bebida: Coca ou Coca Zero”. Fica numa tela à parte porque cada escolha tem
# a própria lista de opções — dois formsets encaixados na tela do combo
# seriam bem mais difíceis de usar e de manter.

def _salvar_escolha(request, combo, escolha=None):
    if request.method == "POST":
        form = ComboEscolhaForm(request.POST, instance=escolha)
        formset = ComboEscolhaOpcaoFormSet(request.POST, instance=escolha or ComboEscolha())
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                escolha = form.save(commit=False)
                escolha.combo = combo
                escolha.save()
                formset.instance = escolha
                formset.save()
            return escolha, None, None
    else:
        form = ComboEscolhaForm(instance=escolha)
        formset = ComboEscolhaOpcaoFormSet(instance=escolha or ComboEscolha())
    return None, form, formset


@login_required
def combo_escolha_criar(request, pk):
    combo = get_object_or_404(Combo, pk=pk)
    escolha, form, formset = _salvar_escolha(request, combo)
    if escolha:
        messages.success(request, f"O cliente agora escolhe “{escolha.nome}” neste combo.")
        return redirect("pedidos:combo_editar", pk=combo.pk)
    return render(request, "combos/escolha_form.html", {
        "combo": combo, "form": form, "formset": formset, "escolha": None,
    })


@login_required
def combo_escolha_editar(request, pk):
    atual = get_object_or_404(ComboEscolha.objects.select_related("combo"), pk=pk)
    escolha, form, formset = _salvar_escolha(request, atual.combo, atual)
    if escolha:
        messages.success(request, f"Escolha “{escolha.nome}” atualizada.")
        return redirect("pedidos:combo_editar", pk=atual.combo_id)
    return render(request, "combos/escolha_form.html", {
        "combo": atual.combo, "form": form, "formset": formset, "escolha": atual,
    })


@login_required
@require_POST
def combo_escolha_excluir(request, pk):
    escolha = get_object_or_404(ComboEscolha.objects.select_related("combo"), pk=pk)
    combo_id, nome = escolha.combo_id, escolha.nome
    escolha.delete()
    messages.success(request, f"Escolha “{nome}” removida do combo.")
    return redirect("pedidos:combo_editar", pk=combo_id)
