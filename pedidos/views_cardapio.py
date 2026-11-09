# views_cardapio.py
# Cardápio público: o cliente navega, enche o carrinho e só no fim informa
# o nome e se come no local ou leva. Sem login em nenhum passo.
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST

from . import carrinho as cart
from .models import Produto, Combo, Pedido, PedidoItem, PedidoCombo


def cardapio(request):
    produtos = Produto.objects.filter(ativo=True).order_by("nome")
    combos = [
        c for c in Combo.objects.filter(ativo=True).prefetch_related("itens__produto").order_by("nome")
        if c.itens.exists()
    ]
    resumo = cart.detalhar(request.session)
    if resumo["ajustado"]:
        messages.warning(request, "Ajustamos o carrinho: algum item saiu do cardápio ou acabou.")

    # marca em cada item quanto já está no carrinho; o template não tem
    # como procurar numa chave de dicionário
    no_carrinho = {(l["tipo"], l["obj"].pk): l["qtd"] for l in resumo["linhas"]}
    produtos = list(produtos)
    for p in produtos:
        p.escolhido = no_carrinho.get(("produtos", p.pk), 0)
    for c in combos:
        c.escolhido = no_carrinho.get(("combos", c.pk), 0)

    return render(request, "cardapio/cardapio.html", {
        "produtos": produtos,
        "combos": combos,
        "resumo": resumo,
    })


@require_POST
def cardapio_adicionar(request):
    tipo = request.POST.get("tipo")
    pk = request.POST.get("pk")
    if tipo not in ("produtos", "combos") or not pk:
        return redirect("pedidos:cardapio")

    if request.POST.get("quantidade") not in (None, ""):
        qtd = cart.ajustar(request.session, tipo, pk, quantidade=int(request.POST["quantidade"]))
    else:
        qtd = cart.ajustar(request.session, tipo, pk, delta=int(request.POST.get("delta", 1)))

    resumo = cart.detalhar(request.session)
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({
            "quantidade": qtd,
            "itens": resumo["itens"],
            "total": f'{resumo["total"]:.2f}'.replace(".", ","),
        })
    return redirect(request.POST.get("voltar") or "pedidos:cardapio")


def carrinho_ver(request):
    resumo = cart.detalhar(request.session)
    if resumo["ajustado"]:
        messages.warning(request, "Ajustamos o carrinho: algum item saiu do cardápio ou acabou.")
    return render(request, "cardapio/carrinho.html", {"resumo": resumo})


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
                pedido = Pedido.objects.create(
                    nome_cliente=nome,
                    consumo=consumo,
                    observacao=observacao,
                    status=Pedido.Status.RASCUNHO,
                )
                for l in resumo["linhas"]:
                    if l["tipo"] == "produtos":
                        PedidoItem.objects.create(
                            pedido=pedido, produto=l["obj"],
                            quantidade=l["qtd"], preco_unitario=l["unit"],
                        )
                    else:
                        PedidoCombo.objects.create(
                            pedido=pedido, combo=l["obj"],
                            quantidade=l["qtd"], preco_unitario=l["unit"],
                        )
                pedido.recalcular_total()
            cart.esvaziar(request.session)
            return redirect("pedidos:cliente_pedido_detalhe", pk=pedido.pk)

    return render(request, "cardapio/finalizar.html", {
        "resumo": resumo,
        "consumos": Pedido.Consumo.choices,
        "nome_cliente": request.POST.get("nome_cliente", ""),
        "observacao": request.POST.get("observacao", ""),
    })
