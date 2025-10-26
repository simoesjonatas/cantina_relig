from django.db import transaction
from django.db.models import F
from django.core.exceptions import ValidationError
from .models import Pedido, Produto, MovimentoEstoque, ComandaCozinha
from django.utils import timezone

@transaction.atomic
def concluir_pedido(pedido_id: int) -> Pedido:
    pedido = Pedido.objects.select_for_update().get(pk=pedido_id)
    if pedido.status != Pedido.Status.ENVIADO_COZINHA:
        raise ValidationError("Apenas pedidos enviados à cozinha podem ser concluídos.")
    pedido.status = Pedido.Status.CONCLUIDO
    pedido.finalizado_em = timezone.now()
    pedido.save(update_fields=["status", "finalizado_em", "atualizado_em"])
    return pedido


@transaction.atomic
def confirmar_pedido(pedido_id: int) -> Pedido:
    pedido = (
        Pedido.objects.select_for_update()
        .select_related()
        .prefetch_related("itens__produto")
        .get(pk=pedido_id)
    )

    if not pedido.itens.exists():
        raise ValidationError("Pedido sem itens.")

    # trava produtos e confere estoque
    for item in pedido.itens.all():
        produto = Produto.objects.select_for_update().get(pk=item.produto_id)
        if item.quantidade > produto.estoque:
            raise ValidationError(
                f"Estoque insuficiente para {produto.nome}: "
                f"solicitado {item.quantidade}, disponível {produto.estoque}."
            )

    # baixa de estoque
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

    # 1) Se ainda é RASCUNHO, não houve baixa de estoque: só muda status.
    if pedido.status == Pedido.Status.RASCUNHO:
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