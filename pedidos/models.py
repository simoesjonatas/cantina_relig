from django.db import models, transaction
from django.db.models import Sum, F
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
import uuid


class Produto(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    estoque = models.PositiveIntegerField(default=0)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} (R$ {self.preco})"

class Combo(models.Model):
    """Conjunto de produtos vendido por um preço fechado, menor que a soma."""
    nome = models.CharField(max_length=120, unique=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} (R$ {self.preco})"

    @property
    def preco_avulso(self):
        """Quanto custaria comprando item por item, nos preços de hoje."""
        return sum((i.produto.preco * i.quantidade for i in self.itens.all()), Decimal("0.00"))

    @property
    def economia(self):
        return self.preco_avulso - self.preco

    @property
    def quantos_cabem(self):
        """Quantos combos o estoque atual ainda comporta."""
        itens = list(self.itens.all())
        if not itens:
            return 0
        return min(i.produto.estoque // i.quantidade for i in itens)

    @property
    def disponivel(self):
        return self.ativo and self.quantos_cabem > 0


class ComboItem(models.Model):
    combo = models.ForeignKey(Combo, related_name="itens", on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = [("combo", "produto")]
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantidade} x {self.produto.nome}"


class Pedido(models.Model):
    class Consumo(models.TextChoices):
        LOCAL = "LOCAL", "Comer no local"
        VIAGEM = "VIAGEM", "Para viagem"

    class Status(models.TextChoices):
        RASCUNHO = "RASC", "Rascunho"
        PAGAMENTO = "AGPG", "Aguardando Pagamento"
        ENVIADO_COZINHA = "ENVC", "Enviado à Cozinha"
        CONCLUIDO = "CONC", "Concluído"
        CANCELADO = "CANC", "Cancelado"

    numero = models.CharField(max_length=20, unique=True, blank=True)  # gerado no save
    nome_cliente = models.CharField(max_length=120)
    consumo = models.CharField(max_length=6, choices=Consumo.choices, default=Consumo.LOCAL)
    observacao = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=4, choices=Status.choices, default=Status.RASCUNHO)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    retirado_em = models.DateTimeField(null=True, blank=True)  # quando o cliente pegou no balcão
    # token_publico = models.UUIDField(default=uuid.uuid4, editable=False, ) # unique=True



    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.numero or '(sem número)'} - {self.nome_cliente}"

    @property
    def e_viagem(self):
        return self.consumo == self.Consumo.VIAGEM

    def gerar_numero(self):
        hoje = timezone.localdate().strftime("%Y%m%d")
        base = f"{hoje}-"
        ultimo = Pedido.objects.filter(numero__startswith=base).order_by("numero").last()
        seq = int(ultimo.numero.split("-")[1]) + 1 if ultimo else 1
        return f"{base}{seq:04d}"

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = self.gerar_numero()
        super().save(*args, **kwargs)

    def recalcular_total(self):
        avulsos = self.itens.aggregate(
            s=Sum(F("quantidade") * F("preco_unitario"))
        )["s"] or 0
        combos = self.combos.aggregate(
            s=Sum(F("quantidade") * F("preco_unitario"))
        )["s"] or 0
        self.total = avulsos + combos
        super().save(update_fields=["total", "atualizado_em"])

    def linhas(self):
        """Itens avulsos e combos numa lista só, para as telas."""
        saida = []
        for it in self.itens.select_related("produto"):
            saida.append({
                "nome": it.produto.nome,
                "qtd": it.quantidade,
                "unit": it.preco_unitario,
                "subtotal": it.preco_unitario * it.quantidade,
                "combo": None,
            })
        for pc in self.combos.select_related("combo").prefetch_related("combo__itens__produto"):
            saida.append({
                "nome": pc.combo.nome,
                "qtd": pc.quantidade,
                "unit": pc.preco_unitario,
                "subtotal": pc.preco_unitario * pc.quantidade,
                "combo": pc.combo,
            })
        return saida

class PedidoItem(models.Model):
    pedido = models.ForeignKey(Pedido, related_name="itens", on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField()
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = [("pedido", "produto")]  # evita duplicado do mesmo produto no pedido

    def clean(self):
        # quantidade vazia é erro de campo obrigatório; aqui ela ainda chega None
        if self.quantidade is not None and self.quantidade <= 0:
            raise ValidationError("Quantidade deve ser positiva.")
        # validação branda aqui; checagem dura acontece na função de confirmação com lock

    def __str__(self):
        return f"{self.quantidade} x {self.produto.nome}"

class PedidoCombo(models.Model):
    """Um combo escolhido num pedido. O preço fica congelado no momento da venda."""
    pedido = models.ForeignKey(Pedido, related_name="combos", on_delete=models.CASCADE)
    combo = models.ForeignKey(Combo, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField()
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = [("pedido", "combo")]

    def clean(self):
        # quantidade vazia é erro de campo obrigatório; aqui ela ainda chega None
        if self.quantidade is not None and self.quantidade <= 0:
            raise ValidationError("Quantidade deve ser positiva.")

    def __str__(self):
        return f"{self.quantidade} x {self.combo.nome}"


class MovimentoEstoque(models.Model):
    class Tipo(models.TextChoices):
        SAIDA = "SAIDA", "Saída"
        ENTRADA = "ENTRADA", "Entrada"
        ESTORNO = "ESTORNO", "Estorno"

    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    pedido = models.ForeignKey(Pedido, null=True, blank=True, on_delete=models.SET_NULL)
    item = models.ForeignKey(PedidoItem, null=True, blank=True, on_delete=models.SET_NULL)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    quantidade = models.PositiveIntegerField()
    criado_em = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=["tipo", "produto", "criado_em"]),
            models.Index(fields=["pedido"]),
        ]

class ComandaCozinha(models.Model):
    pedido = models.OneToOneField(Pedido, related_name="comanda", on_delete=models.CASCADE)
    impresso_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comanda {self.pedido.numero} - {self.pedido.nome_cliente}"
