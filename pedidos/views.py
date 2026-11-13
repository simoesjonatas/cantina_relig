# views.py
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.forms import ModelForm, inlineformset_factory
from django.contrib import messages
from django.core.exceptions import ValidationError
from .models import Pedido, PedidoItem, Produto, ComandaCozinha, Combo
from .forms import PedidoForm, PedidoItemForm, PedidoItemFormSet, PedidoComboFormSet
from decimal import Decimal
from django.views.decorators.http import require_POST
from .services import (
    confirmar_pedido, concluir_pedido, cancelar_pedido, registrar_escolhas,
    marcar_retirado, prontos_aguardando_retirada, JANELA_PRONTOS_MIN,
)
from django.utils import timezone
from django.db.models import Sum, Count, Q
from collections import defaultdict
from django.core.paginator import Paginator
from .utils import querystring_sem_pagina, texto_para_escolhas
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse


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

@login_required
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


def _combos_disponiveis():
    """Combos que dá para vender agora (ativos e com algum conteúdo)."""
    combos = Combo.objects.filter(ativo=True).prefetch_related(
        "itens__produto__componentes__insumo",
        "escolhas__opcoes__produto__componentes__insumo",
    )
    return [c for c in combos if c.montavel]


def _partes_json(produto):
    return [{"produto": str(p.pk), "qtd": q} for p, q in produto.partes()]


def _dados_estoque(combos):
    """
    O que a tela precisa para avisar sobre estoque enquanto a pessoa monta o
    pedido, em vez de só descobrir na hora de confirmar. Manda a ficha técnica
    junto: na conta quem pesa é o insumo (o disco), não o produto montado.
    """
    produtos = Produto.objects.prefetch_related("componentes__insumo")
    return {
        "produtos": {
            str(p.id): {"nome": p.nome, "estoque": p.estoque} for p in produtos
        },
        "partes": {str(p.id): _partes_json(p) for p in produtos if not p.insumo},
        "combos": {
            str(c.id): {
                "fixos": [
                    {"produto": str(pk), "qtd": qtd}
                    for pk, (produto, qtd) in c.necessidade_fixa().items()
                ],
                "escolhas": [
                    {
                        "id": str(e.id),
                        "nome": e.nome,
                        "quantidade": e.quantidade,
                        "opcoes": [
                            {
                                "produto": str(o.produto_id),
                                "nome": o.produto.nome,
                                "adicional": float(o.adicional),
                                "partes": _partes_json(o.produto),
                                "cabem": o.quantos_cabem,
                            }
                            for o in e.opcoes.all()
                        ],
                    }
                    for e in c.escolhas.all()
                ],
            }
            for c in combos
        },
    }


def _falta_estoque(consumo):
    """Recebe {produto_id: quantidade} e devolve o que não cabe no estoque."""
    faltas = []
    produtos = Produto.objects.in_bulk([int(k) for k in consumo])
    for produto_id, pedida in consumo.items():
        produto = produtos.get(int(produto_id))
        if produto and pedida > produto.estoque:
            faltas.append(
                f"{produto.nome}: pedidas {pedida}, disponíveis {produto.estoque}"
            )
    return faltas


def detalhe_pedido(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)

    itens_ctx = pedido.linhas()
    total = sum((l["subtotal"] for l in itens_ctx), Decimal("0.00"))

    # se por algum motivo o total estiver divergente, ajusta
    if pedido.total != total:
        pedido.total = total
        pedido.save(update_fields=["total", "atualizado_em"])

    return render(request, "pedidos/detalhe_pedido.html", {
        "pedido": pedido,
        "itens": itens_ctx,
        "total": total,
    })



def _escolhas_da_linha(post, indice):
    """O que o atendente escolheu nesse combo, vindo do campo escondido da tela."""
    return texto_para_escolhas(post.get(f"combos-{indice}-escolhas", ""))


@login_required
def criar_pedido(request):
    if request.method == "POST":
        form = PedidoForm(request.POST)
        formset = PedidoItemFormSet(request.POST)
        formset_combos = PedidoComboFormSet(request.POST)
        if form.is_valid() and formset.is_valid() and formset_combos.is_valid():
            # soma avulsos e combos antes de salvar, já abrindo a ficha técnica:
            # o mesmo insumo pode estar nos dois lugares, e conferir separado
            # deixaria passar
            consumo = defaultdict(int)
            for f in formset:
                dados = getattr(f, "cleaned_data", None) or {}
                if dados.get("produto") and not dados.get("DELETE"):
                    pedida = dados.get("quantidade") or 0
                    for produto, qtd in dados["produto"].partes():
                        consumo[str(produto.pk)] += qtd * pedida
            for i, f in enumerate(formset_combos.forms):
                dados = getattr(f, "cleaned_data", None) or {}
                if dados.get("combo") and dados.get("quantidade") and not dados.get("DELETE"):
                    vezes = dados["quantidade"]
                    necessidade = dados["combo"].necessidade(_escolhas_da_linha(request.POST, i))
                    for produto, qtd in necessidade.values():
                        consumo[str(produto.pk)] += qtd * vezes

            faltas = _falta_estoque(consumo)
            if faltas:
                for f in faltas:
                    messages.error(request, f"Estoque insuficiente — {f}")
                combos_disp = _combos_disponiveis()
                return render(request, "pedidos/criar_pedido.html", {
                    "form": form, "formset": formset, "formset_combos": formset_combos,
                    "preco_map": {p.id: float(p.preco) for p in Produto.objects.all()},
                    "combos": combos_disp,
                    "estoque": _dados_estoque(combos_disp),
                })

            pedido = form.save()

            formset.instance = pedido
            for it in formset.save(commit=False):
                it.preco_unitario = it.produto.preco  # sempre do produto
                it.save()
            formset.save_m2m()

            formset_combos.instance = pedido
            for i, f in enumerate(formset_combos.forms):
                dados = getattr(f, "cleaned_data", None) or {}
                if not dados.get("combo") or not dados.get("quantidade") or dados.get("DELETE"):
                    continue
                pc = f.save(commit=False)
                pc.pedido = pedido
                pc.preco_unitario = pc.combo.preco  # congela o preço da venda
                pc.save()
                extra = registrar_escolhas(pc, _escolhas_da_linha(request.POST, i))
                if extra:
                    pc.preco_unitario = pc.combo.preco + extra
                    pc.save(update_fields=["preco_unitario"])

            # 🔑 já calcula o total agora (antes mesmo de confirmar)
            pedido.recalcular_total()

            messages.success(request, "Pedido criado em rascunho.")
            return redirect("pedidos:detalhe", pk=pedido.pk)
    else:
        form = PedidoForm()
        formset = PedidoItemFormSet()
        formset_combos = PedidoComboFormSet()

    # mapa para exibir preço automático no front
    preco_map = {p.id: float(p.preco) for p in Produto.objects.all()}
    combos_disp = _combos_disponiveis()
    return render(request, "pedidos/criar_pedido.html", {
        "form": form, "formset": formset, "formset_combos": formset_combos,
        "preco_map": preco_map, "combos": combos_disp,
        "estoque": _dados_estoque(combos_disp),
    })


# def detalhe_pedido(request, pk):
#     pedido = get_object_or_404(Pedido, pk=pk)
#     return render(request, "pedidos/detalhe_pedido.html", {"pedido": pedido})
@login_required
def confirmar_enviar(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    try:
        confirmar_pedido(pedido.id)
        messages.success(request, "Pedido confirmado e enviado à cozinha!")
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect("pedidos:detalhe", pk=pk)  
    return redirect("home")
    # return redirect("pedidos:detalhe", pk=pk)

@login_required
@require_POST
def marcar_retirado_view(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    try:
        marcar_retirado(pedido.id)
        messages.success(request, f"Pedido {pedido.numero} entregue para {pedido.nome_cliente}.")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("pedidos:balcao")


@login_required
def cozinha_painel(request):
    # mostra apenas pedidos enviados e não concluídos/cancelados
    comandas = ComandaCozinha.objects.select_related("pedido").filter(
        pedido__status__in=[Pedido.Status.ENVIADO_COZINHA]
    ).order_by("impresso_em")
    return render(request, "pedidos/cozinha.html", {"comandas": comandas})


@login_required
def balcao_painel(request):
    """Tela de quem entrega: só os pedidos prontos, com o botão de retirada."""
    prontos = (
        prontos_aguardando_retirada()
        .order_by("finalizado_em")
        .prefetch_related("itens__produto", "combos__combo", "combos__escolhas__produto")
    )
    return render(request, "pedidos/balcao.html", {
        "prontos": prontos,
        "ids_atuais": ",".join(str(p.id) for p in prontos),
        "janela_prontos": JANELA_PRONTOS_MIN,
    })


@login_required
def balcao_dados(request):
    """Só os ids, para a tela saber quando precisa se atualizar."""
    ids = prontos_aguardando_retirada().order_by("finalizado_em").values_list("id", flat=True)
    return JsonResponse({"ids": list(ids)})


@login_required
def pedido_lista(request):
    """Todos os pedidos, com busca e filtros — substitui o admin."""
    base = Pedido.objects.all()

    busca = request.GET.get("q", "").strip()
    if busca:
        base = base.filter(Q(numero__icontains=busca) | Q(nome_cliente__icontains=busca))

    status = request.GET.get("status", "")
    if status:
        base = base.filter(status=status)

    de = request.GET.get("de")
    ate = request.GET.get("ate")
    if de:
        base = base.filter(criado_em__date__gte=de)
    if ate:
        base = base.filter(criado_em__date__lte=ate)

    # o resumo sai da queryset sem annotate, senão o join dos itens duplicaria a soma
    resumo = base.aggregate(
        quantidade=Count("id"),
        faturamento=Sum("total", filter=~Q(status=Pedido.Status.CANCELADO)),
    )

    pedidos = base.annotate(
        qtd_itens=Count("itens", distinct=True),
        qtd_combos=Count("combos", distinct=True),
    ).order_by("-criado_em")
    page_obj = Paginator(pedidos, 25).get_page(request.GET.get("page"))

    return render(request, "pedidos/lista.html", {
        "page_obj": page_obj,
        "pedidos": page_obj,
        "resumo": resumo,
        "busca": busca,
        "status": status,
        "status_opcoes": Pedido.Status.choices,
        "querystring": querystring_sem_pagina(request),
        "tem_filtro": bool(busca or status or de or ate),
    })


@login_required
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

def _pendentes_qs():
    return (
        Pedido.objects.filter(status=Pedido.Status.PAGAMENTO)
        .prefetch_related("itens__produto", "combos__combo", "combos__escolhas__produto")
        .order_by("criado_em")
    )


@login_required
def caixa_pendentes(request):
    pendentes = list(_pendentes_qs())
    return render(request, "caixa/pendentes.html", {
        "pedidos": pendentes,
        "ids_atuais": ",".join(str(p.id) for p in pendentes),
        "total_fila": sum((p.total for p in pendentes), Decimal("0.00")),
    })


@login_required
def caixa_pendentes_dados(request):
    """Só os ids, para a tela saber quando chegou pedido novo."""
    ids = _pendentes_qs().values_list("id", flat=True)
    return JsonResponse({"ids": list(ids)})


@login_required
@require_POST
def caixa_confirmar_pagamento(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)

    if pedido.status != Pedido.Status.PAGAMENTO:
        messages.error(request, "Este pedido não está aguardando pagamento.")
        return redirect("caixa_pendentes")
    try:
        confirmar_pedido(pedido.id)
        messages.success(request, f"Pagamento do pedido {pedido.numero} confirmado!")
    except ValidationError as e:
        messages.error(request, str(e))
        redirect("pedidos:caixa_pendentes")
    return redirect("pedidos:caixa_pendentes")

@login_required
def caixa_buscar_pedido(request):
    numero = request.GET.get("numero", "").strip()

    if not numero:
        messages.error(request, "Informe o número do pedido.")
        return redirect("pedidos:caixa_pendentes")

    try:
        pedido = Pedido.objects.get(numero=numero)
    except Pedido.DoesNotExist:
        messages.error(request, f"Pedido {numero} não encontrado.")
        return redirect("pedidos:caixa_pendentes")

    if pedido.status != Pedido.Status.PAGAMENTO:
        messages.error(
            request,
            f"O pedido {numero} não está aguardando pagamento (status atual: {pedido.get_status_display()})."
        )
        return redirect("pedidos:caixa_pendentes")
    

    itens_ctx = pedido.linhas()
    total = sum((l["subtotal"] for l in itens_ctx), Decimal("0.00"))

    # se por algum motivo o total estiver divergente, ajusta
    if pedido.total != total:
        pedido.total = total
        pedido.save(update_fields=["total", "atualizado_em"])

    # Tela de confirmação do caixa para esse pedido
    return render(request, "caixa/pedido_confirmar.html", {
        "pedido": pedido,
        "itens": itens_ctx,
        "total": total,
    })