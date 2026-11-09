# pedidos/context_processors.py
from django.db.models import Sum
from .models import Produto

def estoque_widget_data(request):
    # Mostra só produtos ativos; ajuste se quiser
    produtos = Produto.objects.filter(ativo=True).order_by("nome")\
                .values("id", "nome", "estoque")

    total_disponivel = sum(p["estoque"] for p in produtos)
    # Destaque para baixo estoque (ex.: <= 5)
    baixo_estoque = [p for p in produtos if p["estoque"] <= 5]

    return {
        "estoque_total_disponivel": total_disponivel,
        "estoque_produtos": produtos,           # para listar no widget
        "estoque_baixo": baixo_estoque,         # para alertas
    }


def meus_pedidos_resumo(request):
    """Quantos pedidos a pessoa tem em aberto, para o atalho no menu."""
    ids = request.session.get("meus_pedidos") if hasattr(request, "session") else None
    if not ids:
        return {"meus_pedidos_qtd": 0}

    from .models import Pedido
    qtd = Pedido.objects.filter(pk__in=ids).exclude(
        status__in=[Pedido.Status.CONCLUIDO, Pedido.Status.CANCELADO]
    ).count()
    return {"meus_pedidos_qtd": qtd, "meus_pedidos_tem": True}
