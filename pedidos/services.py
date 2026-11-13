from django.db import transaction
from django.db.models import F, Sum
from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import (
    Pedido, Produto, MovimentoEstoque, ComandaCozinha,
    PedidoComboEscolha, somar_parte,
)
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


def registrar_escolhas(pedido_combo, escolhas):
    """
    Congela no pedido o que o cliente escolheu (“Bebida: Coca Zero”) e devolve
    quanto isso soma ao preço do combo. Guardamos o rótulo e o adicional aqui
    porque o combo pode mudar depois sem reescrever a venda.
    """
    combo = pedido_combo.combo
    escolhas = {int(k): int(v) for k, v in (escolhas or {}).items() if v}
    pedido_combo.escolhas.all().delete()

    extra = Decimal("0.00")
    for escolha in combo.escolhas.all():
        opcao = escolha.opcao(escolhas.get(escolha.pk))
        if not opcao:
            continue
        PedidoComboEscolha.objects.create(
            pedido_combo=pedido_combo,
            escolha=escolha,
            rotulo=escolha.nome,
            produto=opcao.produto,
            quantidade=escolha.quantidade,
            adicional=opcao.adicional,
        )
        extra += opcao.adicional * escolha.quantidade
    return extra


def _consumo_por_produto(pedido):
    """
    Quanto cada item de estoque sai neste pedido. Dois passos importantes:
    produto com ficha técnica vira os insumos dele (um duplo são 2 discos), e
    o mesmo insumo pode vir de lugares diferentes — avulso, dentro de um combo
    e ainda pela bebida escolhida. Tudo isso precisa somar antes de conferir,
    senão daria para vender mais do que existe.

    Devolve {pk: (produto, quantidade)}.
    """
    necessidade = {}
    for item in pedido.itens.all():
        for produto, quantidade in item.produto.partes():
            somar_parte(necessidade, produto, quantidade * item.quantidade)
    for pc in pedido.combos.all():
        for produto, quantidade in pc.necessidade().values():
            somar_parte(necessidade, produto, quantidade * pc.quantidade)
    return necessidade


@transaction.atomic
def confirmar_pedido(pedido_id: int) -> Pedido:
    pedido = (
        Pedido.objects.select_for_update()
        .select_related()
        .prefetch_related(
            "itens__produto__componentes__insumo",
            "combos__combo__itens__produto__componentes__insumo",
            "combos__escolhas__produto__componentes__insumo",
        )
        .get(pk=pedido_id)
    )

    if not pedido.itens.exists() and not pedido.combos.exists():
        raise ValidationError("Pedido sem itens.")

    # confere o estoque já somado, com os produtos travados
    necessidade = _consumo_por_produto(pedido)
    for produto_id, (produto, quantidade) in necessidade.items():
        travado = Produto.objects.select_for_update().get(pk=produto_id)
        if quantidade > travado.estoque:
            raise ValidationError(
                f"Estoque insuficiente para {travado.nome}: "
                f"solicitado {quantidade}, disponível {travado.estoque}."
            )

    def baixar(produto_id, quantidade, item=None):
        produto = Produto.objects.select_for_update().get(pk=produto_id)
        produto.estoque = F("estoque") - quantidade
        produto.save(update_fields=["estoque"])
        MovimentoEstoque.objects.create(
            produto=produto,
            pedido=pedido,
            item=item,
            tipo=MovimentoEstoque.Tipo.SAIDA,
            quantidade=quantidade,
        )

    # baixa dos itens avulsos (guarda o vínculo com a linha do pedido)
    for item in pedido.itens.all():
        for produto, quantidade in item.produto.partes():
            baixar(produto.pk, quantidade * item.quantidade, item=item)

    # baixa do conteúdo dos combos, incluindo o que o cliente escolheu
    for pc in pedido.combos.all():
        for produto, quantidade in pc.necessidade().values():
            baixar(produto.pk, quantidade * pc.quantidade)

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