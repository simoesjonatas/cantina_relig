# views_estoque.py
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.shortcuts import render, get_object_or_404

from .models import MovimentoEstoque, Produto


def _aplicar_filtros(request, qs):
    """Reaproveita filtros nas duas telas."""
    de = request.GET.get("de")     # yyyy-mm-dd
    ate = request.GET.get("ate")   # yyyy-mm-dd
    q = request.GET.get("q")       # busca por nome do produto ou cliente
    pedido = request.GET.get("pedido")  # número exato

    if de:
        qs = qs.filter(criado_em__date__gte=de)
    if ate:
        qs = qs.filter(criado_em__date__lte=ate)
    if q:
        qs = qs.filter(Q(produto__nome__icontains=q) | Q(pedido__nome_cliente__icontains=q))
    if pedido:
        qs = qs.filter(pedido__numero=pedido)
    return qs


def _querystring(request):
    """Filtros atuais sem o 'page', já escapados (nomes com espaço/acento)."""
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


@login_required
def saidas_por_produto(request):
    """
    Lista agregada: total que saiu por produto no período.
    """
    qs = MovimentoEstoque.objects.filter(tipo=MovimentoEstoque.Tipo.SAIDA).select_related("produto")
    qs = _aplicar_filtros(request, qs)

    # group by produto (traz o estoque atual junto, para comparar com o que saiu)
    agregados = (
        qs.values("produto_id", "produto__nome", "produto__estoque")
          .annotate(total_saiu=Sum("quantidade"))
          .order_by("produto__nome")
    )

    # paginação
    paginator = Paginator(agregados, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    ctx = {
        "rows": page_obj,
        "page_obj": page_obj,
        "querystring": _querystring(request),
        "total_unidades": qs.aggregate(s=Sum("quantidade"))["s"] or 0,
        "total_produtos": paginator.count,
        "tem_filtro": any(request.GET.get(k) for k in ("de", "ate", "q", "pedido")),
    }
    return render(request, "estoque/saidas_por_produto.html", ctx)


@login_required
def saidas_do_produto_detail(request, produto_id):
    """
    Detalhe: ao clicar no produto, mostra por pedido quanto saiu.
    """
    produto = get_object_or_404(Produto, pk=produto_id)

    qs = MovimentoEstoque.objects.filter(
        tipo=MovimentoEstoque.Tipo.SAIDA,
        produto=produto
    ).select_related("pedido", "produto")
    qs = _aplicar_filtros(request, qs)

    # agregação por pedido (quanto desse produto saiu em cada pedido)
    por_pedido = (
        qs.values("pedido_id", "pedido__numero", "pedido__nome_cliente", "pedido__criado_em")
          .annotate(total_pedido=Sum("quantidade"))
          .order_by("-pedido__criado_em")
    )

    # (opcional) lista "linha a linha" para ver fragmentações/estornos
    linhas = qs.order_by("-criado_em")

    paginator = Paginator(por_pedido, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    ctx = {
        "produto": produto,
        "rows": page_obj,
        "linhas": linhas[:100],  # mostra até 100 últimas linhas como referência
        "page_obj": page_obj,
        "querystring": _querystring(request),
        "total_unidades": qs.aggregate(s=Sum("quantidade"))["s"] or 0,
        "total_pedidos": paginator.count,
        "tem_filtro": any(request.GET.get(k) for k in ("de", "ate", "q", "pedido")),
    }
    return render(request, "estoque/saidas_do_produto_detail.html", ctx)
