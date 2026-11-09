# views_categorias.py
# Seções do cardápio. CRUD enxuto: a lista é também o formulário.
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .forms import CategoriaForm
from .models import Categoria, Produto


@login_required
def categoria_lista(request):
    if request.method == "POST":
        form = CategoriaForm(request.POST)
        if form.is_valid():
            cat = form.save()
            messages.success(request, f"Categoria “{cat.nome}” criada.")
            return redirect("pedidos:categoria_lista")
    else:
        form = CategoriaForm()

    categorias = Categoria.objects.annotate(qtd=Count("produtos")).order_by("ordem", "nome")
    return render(request, "categorias/lista.html", {
        "categorias": categorias,
        "form": form,
        "sem_categoria": Produto.objects.filter(categoria__isnull=True, ativo=True).count(),
    })


@login_required
def categoria_editar(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == "POST":
        form = CategoriaForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            messages.success(request, f"Categoria “{categoria.nome}” atualizada.")
            return redirect("pedidos:categoria_lista")
    else:
        form = CategoriaForm(instance=categoria)
    return render(request, "categorias/editar.html", {"form": form, "categoria": categoria})


@login_required
@require_POST
def categoria_excluir(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    nome = categoria.nome
    # os produtos não somem junto: ficam sem categoria (SET_NULL)
    quantos = categoria.produtos.count()
    categoria.delete()
    extra = f" {quantos} produto(s) ficaram sem categoria." if quantos else ""
    messages.success(request, f"Categoria “{nome}” excluída.{extra}")
    return redirect("pedidos:categoria_lista")
