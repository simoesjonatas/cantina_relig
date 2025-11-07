from django.db import models, transaction
from django.db.models import Sum, F
from django.core.exceptions import ValidationError
from django.utils import timezone

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

class Pedido(models.Model):
    class Status(models.TextChoices):
        RASCUNHO = "RASC", "Rascunho"
        ENVIADO_COZINHA = "ENVC", "Enviado à Cozinha"
        CONCLUIDO = "CONC", "Concluído"
        CANCELADO = "CANC", "Cancelado"

    numero = models.CharField(max_length=20, unique=True, blank=True)  # gerado no save
    nome_cliente = models.CharField(max_length=120)
    status = models.CharField(max_length=4, choices=Status.choices, default=Status.RASCUNHO)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    finalizado_em = models.DateTimeField(null=True, blank=True)


    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return f"{self.numero or '(sem número)'} - {self.nome_cliente}"

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
        total = self.itens.aggregate(
            s=Sum(F("quantidade") * F("preco_unitario"))
        )["s"] or 0
        self.total = total
        super().save(update_fields=["total", "atualizado_em"])

class PedidoItem(models.Model):
    pedido = models.ForeignKey(Pedido, related_name="itens", on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField()
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = [("pedido", "produto")]  # evita duplicado do mesmo produto no pedido

    def clean(self):
        if self.quantidade <= 0:
            raise ValidationError("Quantidade deve ser positiva.")
        # validação branda aqui; checagem dura acontece na função de confirmação com lock

    def __str__(self):
        return f"{self.quantidade} x {self.produto.nome}"

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
