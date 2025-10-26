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
