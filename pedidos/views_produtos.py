# views_produtos.py
# CRUD de produtos fora do admin do Django.
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .forms import ProdutoForm, ProdutoComponenteFormSet
from .models import Produto, ProdutoComponente, PedidoItem, MovimentoEstoque


def _registrar_entrada(produto, quantidade):
    """Guarda no histórico a reposição de estoque feita pela tela."""
    if quantidade > 0:
        MovimentoEstoque.objects.create(
            produto=produto,
            tipo=MovimentoEstoque.Tipo.ENTRADA,
            quantidade=quantidade,
        )


@login_required
def produto_lista(request):
    produtos = Produto.objects.annotate(vezes_vendido=Count("pedidoitem")).prefetch_related(
        "componentes__insumo"
    )

    busca = request.GET.get("q", "").strip()
    if busca:
        produtos = produtos.filter(nome__icontains=busca)

    situacao = request.GET.get("situacao")
    if situacao == "ativos":
        produtos = produtos.filter(ativo=True, insumo=False)
    elif situacao == "inativos":
        produtos = produtos.filter(ativo=False)
    elif situacao == "insumos":
        produtos = produtos.filter(insumo=True)

    todos = Produto.objects.aggregate(
        total=Count("id"),
        ativos=Count("id", filter=Q(ativo=True, insumo=False)),
        insumos=Count("id", filter=Q(insumo=True)),
        sem_estoque=Count("id", filter=Q(estoque=0, ativo=True, componentes__isnull=True)),
    )

    return render(request, "produtos/lista.html", {
        "produtos": produtos.order_by("insumo", "nome"),
        "resumo": todos,
        "busca": busca,
        "situacao": situacao or "",
    })


def _salvar_produto(request, produto=None):
    """
    Produto e ficha técnica saem na mesma tela: quem cadastra o hambúrguer
    duplo já diz ali que ele gasta 2 discos.
    """
    estoque_antes = produto.estoque if produto else 0

    if request.method == "POST":
        form = ProdutoForm(request.POST, request.FILES, instance=produto)
        formset = ProdutoComponenteFormSet(request.POST, instance=produto or Produto())
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                produto = form.save(commit=False)
                formset.instance = produto

                # linha sem insumo escolhido é linha em branco, não erro
                tem_ficha = any(
                    (getattr(f, "cleaned_data", None) or {}).get("insumo")
                    and not f.cleaned_data.get("DELETE")
                    for f in formset.forms
                )
                # montado a partir de insumos não tem estoque próprio: o que
                # vale é o que os insumos comportam
                if tem_ficha:
                    produto.estoque = 0
                produto.save()
                formset.save()

                if not tem_ficha:
                    _registrar_entrada(produto, produto.estoque - estoque_antes)
            return produto, None, None
    else:
        form = ProdutoForm(instance=produto)
        formset = ProdutoComponenteFormSet(instance=produto or Produto())

    return None, form, formset


@login_required
def produto_criar(request):
    produto, form, formset = _salvar_produto(request)
    if produto:
        messages.success(request, f"Produto “{produto.nome}” cadastrado.")
        return redirect("pedidos:produto_lista")

    return render(request, "produtos/form.html", {"form": form, "formset": formset, "produto": None})


@login_required
def produto_editar(request, pk):
    original = get_object_or_404(Produto, pk=pk)
    produto, form, formset = _salvar_produto(request, original)
    if produto:
        messages.success(request, f"Produto “{produto.nome}” atualizado.")
        return redirect("pedidos:produto_lista")

    return render(request, "produtos/form.html", {"form": form, "formset": formset, "produto": original})


@login_required
@require_POST
def produto_alternar_ativo(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    produto.ativo = not produto.ativo
    produto.save(update_fields=["ativo"])
    estado = "disponível para venda" if produto.ativo else "desativado"
    messages.success(request, f"“{produto.nome}” agora está {estado}.")
    return redirect("pedidos:produto_lista")


@login_required
def produto_excluir(request, pk):
    produto = get_object_or_404(Produto, pk=pk)
    # produto já usado em pedido não pode ser apagado (on_delete=PROTECT):
    # apagar reescreveria o histórico de vendas
    em_pedidos = PedidoItem.objects.filter(produto=produto).count()
    # insumo usado na ficha de outro produto também não pode sumir
    em_fichas = list(
        ProdutoComponente.objects.filter(insumo=produto).select_related("produto")
    )

    if request.method == "POST":
        if em_fichas:
            nomes = ", ".join(c.produto.nome for c in em_fichas)
            messages.error(
                request,
                f"“{produto.nome}” é insumo de {nomes}. Tire da ficha desses produtos antes de excluir."
            )
            return redirect("pedidos:produto_lista")
        if em_pedidos:
            messages.error(
                request,
                f"“{produto.nome}” já foi vendido em {em_pedidos} pedido(s) e não pode ser "
                f"excluído. Use “Desativar” para tirá-lo do cardápio."
            )
            return redirect("pedidos:produto_lista")
        nome = produto.nome
        produto.delete()
        messages.success(request, f"Produto “{nome}” excluído.")
        return redirect("pedidos:produto_lista")

    return render(request, "produtos/excluir.html", {
        "produto": produto,
        "em_pedidos": em_pedidos,
        "em_fichas": em_fichas,
    })
