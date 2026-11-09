# views_painel.py
# Painel público de acompanhamento de pedidos (estilo praça de alimentação):
# coluna "Em preparo" x coluna "Pronto", atualizado sozinho por polling.
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .models import Pedido
from .services import prontos_aguardando_retirada

# Máximo de nomes exibidos por coluna (para caber na tela)
LIMITE_COLUNA = 12


def _numero_curto(numero: str) -> str:
    """20260908-0012 -> 12 (só a sequência do dia, mais legível de longe)."""
    if not numero:
        return ""
    sufixo = numero.split("-")[-1].lstrip("0")
    return sufixo or numero


def _serializar(pedidos) -> list[dict]:
    return [
        {
            "id": p.id,
            "nome": p.nome_cliente,
            "numero": p.numero,
            "curto": _numero_curto(p.numero),
            "viagem": p.e_viagem,
        }
        for p in pedidos
    ]


def _dados_painel() -> dict:
    em_preparo = Pedido.objects.filter(
        status=Pedido.Status.ENVIADO_COZINHA
    ).order_by("criado_em")
    # sai daqui quando o balcão clica em "Retirado" (ou pela janela de segurança)
    prontos = prontos_aguardando_retirada().order_by("-finalizado_em")

    total_preparo = em_preparo.count()
    total_prontos = prontos.count()

    return {
        "em_preparo": _serializar(em_preparo[:LIMITE_COLUNA]),
        "prontos": _serializar(prontos[:LIMITE_COLUNA]),
        # totais reais: a tela mostra "+N" quando não cabe tudo
        "total_em_preparo": total_preparo,
        "total_prontos": total_prontos,
        "atualizado_em": timezone.localtime().strftime("%H:%M:%S"),
    }


def painel(request):
    """Tela cheia para a TV/monitor da cantina."""
    return render(request, "pedidos/painel.html", {"dados": _dados_painel()})


def painel_dados(request):
    """JSON consumido pelo painel a cada poucos segundos."""
    return JsonResponse(_dados_painel())
