from django.db import transaction
from django.db.models import F, Sum
from collections import defaultdict
from django.core.exceptions import ValidationError
from .models import Pedido, Produto, MovimentoEstoque, ComandaCozinha
from django.utils import timezone
from datetime import timedelta

# Por quanto tempo um pedido pronto continua na fila de retirada mesmo que
# ninguém clique em "Retirado" (rede de segurança para dias movimentados).
JANELA_PRONTOS_MIN = 60


def prontos_aguardando_retirada():
    """Pedidos concluídos que ainda não foram entregues (e não expiraram)."""
    corte = timezone.now() - timedelta(minutes=JANELA_PRONTOS_MIN)
    return Pedido.objects.filter(
        status=Pedido.Status.CONCLUIDO,
        retirado_em__isnull=True,
        finalizado_em__gte=corte,
    )


@transaction.atomic
def marcar_retirado(pedido_id: int) -> Pedido:
    """Balcão confirma que o cliente pegou o pedido: sai do painel na hora."""
    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)
    if pedido.status != Pedido.Status.CONCLUIDO:
        raise ValidationError("Apenas pedidos concluídos podem ser marcados como retirados.")
    if pedido.retirado_em:
        return pedido  # idempotente: dois cliques seguidos não quebram nada
    pedido.retirado_em = timezone.now()
    pedido.save(update_fields=["retirado_em", "atualizado_em"])
    return pedido


@transaction.atomic
def concluir_pedido(pedido_id: int) -> Pedido:
    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)
    if pedido.status != Pedido.Status.ENVIADO_COZINHA:
        raise ValidationError("Apenas pedidos enviados à cozinha podem ser concluídos.")
    pedido.status = Pedido.Status.CONCLUIDO
    pedido.finalizado_em = timezone.now()
    pedido.save(update_fields=["status", "finalizado_em", "atualizado_em"])
    return pedido


def _consumo_por_produto(pedido):
    """
    Quanto cada produto sai neste pedido, somando itens avulsos e o conteúdo
    dos combos. Precisa ser somado: o mesmo produto pode estar solto e dentro
    de um combo, e conferir separado deixaria vender mais do que há no estoque.
    """
    necessidade = defaultdict(int)
    for item in pedido.itens.all():
        necessidade[item.produto_id] += item.quantidade
    for pc in pedido.combos.all():
        for ci in pc.combo.itens.all():
            necessidade[ci.produto_id] += ci.quantidade * pc.quantidade
    return necessidade


@transaction.atomic
def confirmar_pedido(pedido_id: int) -> Pedido:
    pedido = (
        Pedido.objects.select_for_update()
        .select_related()
        .prefetch_related("itens__produto", "combos__combo__itens__produto")
        .get(pk=pedido_id)
    )

    if not pedido.itens.exists() and not pedido.combos.exists():
        raise ValidationError("Pedido sem itens.")

    # confere o estoque somando avulsos + combos, com os produtos travados
    necessidade = _consumo_por_produto(pedido)
    for produto_id, quantidade in necessidade.items():
        produto = Produto.objects.select_for_update().get(pk=produto_id)
        if quantidade > produto.estoque:
            raise ValidationError(
                f"Estoque insuficiente para {produto.nome}: "
                f"solicitado {quantidade}, disponível {produto.estoque}."
            )

    # baixa dos itens avulsos (guarda o vínculo com a linha do pedido)
    for item in pedido.itens.all():
        produto = Produto.objects.select_for_update().get(pk=item.produto_id)
        produto.estoque = F("estoque") - item.quantidade
        produto.save(update_fields=["estoque"])
        MovimentoEstoque.objects.create(
            produto=produto,
            pedido=pedido,
            item=item,
            tipo=MovimentoEstoque.Tipo.SAIDA,
            quantidade=item.quantidade,
        )

    # baixa do conteúdo dos combos
    for pc in pedido.combos.all():
        for ci in pc.combo.itens.all():
            quantidade = ci.quantidade * pc.quantidade
            produto = Produto.objects.select_for_update().get(pk=ci.produto_id)
            produto.estoque = F("estoque") - quantidade
            produto.save(update_fields=["estoque"])
            MovimentoEstoque.objects.create(
                produto=produto,
                pedido=pedido,
                item=None,
                tipo=MovimentoEstoque.Tipo.SAIDA,
                quantidade=quantidade,
            )

    pedido.recalcular_total()
    pedido.status = Pedido.Status.ENVIADO_COZINHA
    pedido.save(update_fields=["status", "total", "atualizado_em"])

    ComandaCozinha.objects.get_or_create(pedido=pedido)
    return pedido

@transaction.atomic
def cancelar_pedido(pedido_id: int) -> Pedido:
    pedido = (
        Pedido.objects.select_for_update()
        .get(pk=pedido_id)
    )

    if pedido.status == Pedido.Status.CANCELADO:
        return pedido  # já cancelado, nada a fazer

    # 1) Se ainda é RASCUNHO ou PAGAMENTO, não houve baixa de estoque: só muda status.
    if pedido.status in (Pedido.Status.RASCUNHO, Pedido.Status.PAGAMENTO):
        pedido.status = Pedido.Status.CANCELADO
        pedido.save(update_fields=["status", "atualizado_em"])
        return pedido

    # 2) Para pedidos já confirmados (ex.: ENVIADO_COZINHA),
    #    devolva apenas o que foi baixado e ainda não foi estornado (idempotente).
    saidas = (
        MovimentoEstoque.objects
        .filter(pedido=pedido, tipo=MovimentoEstoque.Tipo.SAIDA)
        .values("produto_id")
        .annotate(qtd_saida=Sum("quantidade"))
    )
    estornos = {
        row["produto_id"]: row["qtd_estorno"]
        for row in MovimentoEstoque.objects
            .filter(pedido=pedido, tipo=MovimentoEstoque.Tipo.ESTORNO)
            .values("produto_id")
            .annotate(qtd_estorno=Sum("quantidade"))
    }

    for row in saidas:
        produto_id = row["produto_id"]
        qtd_saida = row["qtd_saida"] or 0
        qtd_estorno = estornos.get(produto_id, 0) or 0
        qtd_a_devolver = qtd_saida - qtd_estorno

        if qtd_a_devolver > 0:
            produto = Produto.objects.select_for_update().get(pk=produto_id)
            produto.estoque = F("estoque") + qtd_a_devolver
            produto.save(update_fields=["estoque"])

            MovimentoEstoque.objects.create(
                produto=produto,
                pedido=pedido,
                item=None,  # opcional; ou some o estorno por item se preferir
                tipo=MovimentoEstoque.Tipo.ESTORNO,
                quantidade=qtd_a_devolver,
            )

    pedido.status = Pedido.Status.CANCELADO
    pedido.save(update_fields=["status", "atualizado_em"])
    return pedido