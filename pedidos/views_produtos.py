# views_produtos.py
# CRUD de produtos fora do admin do Django.
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .forms import ProdutoForm
from .models import Produto, PedidoItem, MovimentoEstoque


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
    produtos = Produto.objects.annotate(vezes_vendido=Count("pedidoitem"))

    busca = request.GET.get("q", "").strip()
    if busca:
        produtos = produtos.filter(nome__icontains=busca)

    situacao = request.GET.get("situacao")
    if situacao == "ativos":
        produtos = produtos.filter(ativo=True)
    elif situacao == "inativos":
        produtos = produtos.filter(ativo=False)

    todos = Produto.objects.aggregate(
        total=Count("id"),
        ativos=Count("id", filter=Q(ativo=True)),
        sem_estoque=Count("id", filter=Q(estoque=0, ativo=True)),
    )

    return render(request, "produtos/lista.html", {
        "produtos": produtos.order_by("nome"),
        "resumo": todos,
        "busca": busca,
        "situacao": situacao or "",
    })


@login_required
def produto_criar(request):
    if request.method == "POST":
        form = ProdutoForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                produto = form.save()
                _registrar_entrada(produto, produto.estoque)
            messages.success(request, f"Produto “{produto.nome}” cadastrado.")
            return redirect("pedidos:produto_lista")
    else:
        form = ProdutoForm()

    return render(request, "produtos/form.html", {"form": form, "produto": None})


@login_required
def produto_editar(request, pk):
    produto = get_object_or_404(Produto, pk=pk)

    if request.method == "POST":
        estoque_antes = produto.estoque
        form = ProdutoForm(request.POST, instance=produto)
        if form.is_valid():
            with transaction.atomic():
                produto = form.save()
                _registrar_entrada(produto, produto.estoque - estoque_antes)
            messages.success(request, f"Produto “{produto.nome}” atualizado.")
            return redirect("pedidos:produto_lista")
    else:
        form = ProdutoForm(instance=produto)

    return render(request, "produtos/form.html", {"form": form, "produto": produto})


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

    if request.method == "POST":
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
    })
