from django.db import models, transaction
from django.db.models import Sum, F
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal
import uuid


def somar_parte(necessidade, produto, quantidade):
    """
    Acumula {pk: (produto, quantidade)}. Guardamos o objeto junto para não
    voltar ao banco a cada conta de estoque.
    """
    atual = necessidade.get(produto.pk)
    necessidade[produto.pk] = (produto, (atual[1] if atual else 0) + quantidade)
    return necessidade


def cabem(necessidade):
    """Quantas vezes o estoque atual atende essa necessidade por unidade."""
    if not necessidade:
        return 0
    return min(
        (produto.estoque // quantidade if quantidade else 0)
        for produto, quantidade in necessidade.values()
    )


class Categoria(models.Model):
    """Seção do cardápio: Lanches, Bebidas, Doces..."""
    nome = models.CharField(max_length=60, unique=True)
    ordem = models.PositiveIntegerField(default=0, help_text="Menor aparece primeiro no cardápio.")

    class Meta:
        ordering = ["ordem", "nome"]
        verbose_name_plural = "categorias"

    def __str__(self):
        return self.nome


class Produto(models.Model):
    nome = models.CharField(max_length=120, unique=True)
    categoria = models.ForeignKey(
        Categoria, null=True, blank=True, on_delete=models.SET_NULL, related_name="produtos"
    )
    descricao = models.CharField(max_length=200, blank=True)
    foto = models.ImageField(upload_to="produtos/", blank=True, null=True)
    preco = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estoque = models.PositiveIntegerField(default=0)
    insumo = models.BooleanField(
        default=False,
        verbose_name="É um insumo",
        help_text="Insumo não é vendido sozinho: só entra na ficha de outros produtos.",
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} (R$ {self.preco})"

    # --- ficha técnica -----------------------------------------------------
    # Um produto pode ser montado a partir de insumos (o hambúrguer duplo gasta
    # 2 discos). Quando tem ficha, o estoque dele deixa de ser um número à parte
    # e passa a sair do que os insumos comportam — assim duplos e triplos
    # dividem o mesmo pote de discos sem ninguém precisar atualizar os dois.

    def partes(self):
        """O que sai do estoque por unidade vendida: [(produto, quantidade)]."""
        componentes = list(self.componentes.all())
        if not componentes:
            return [(self, 1)]
        return [(c.insumo, c.quantidade) for c in componentes]

    @property
    def composto(self):
        return bool(self.componentes.all())

    @property
    def estoque_disponivel(self):
        """Quantas unidades dá para montar/vender agora."""
        componentes = list(self.componentes.all())
        if not componentes:
            return self.estoque
        return cabem({
            c.insumo.pk: (c.insumo, c.quantidade) for c in componentes if c.quantidade
        })

    @property
    def ficha_resumo(self):
        return " · ".join(f"{c.quantidade}× {c.insumo.nome}" for c in self.componentes.all())


class ProdutoComponente(models.Model):
    """Uma linha da ficha técnica: quanto de um insumo entra em um produto."""
    produto = models.ForeignKey(Produto, related_name="componentes", on_delete=models.CASCADE)
    insumo = models.ForeignKey(Produto, related_name="usado_em", on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        unique_together = [("produto", "insumo")]
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantidade} x {self.insumo.nome}"

    def clean(self):
        if self.insumo_id and self.produto_id and self.insumo_id == self.produto_id:
            raise ValidationError("Um produto não pode ser insumo dele mesmo.")
        # uma ficha só desce um nível: insumo com ficha própria viraria uma
        # corrente difícil de conferir na hora de dar baixa
        if self.insumo_id and ProdutoComponente.objects.filter(produto_id=self.insumo_id).exists():
            raise ValidationError(
                f"“{self.insumo.nome}” já é montado a partir de outros itens e "
                f"não pode ser usado como insumo."
            )


class Combo(models.Model):
    """Conjunto de produtos vendido por um preço fechado, menor que a soma."""
    nome = models.CharField(max_length=120, unique=True)
    descricao = models.CharField(max_length=200, blank=True)
    foto = models.ImageField(upload_to="combos/", blank=True, null=True)
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
        total = sum((i.produto.preco * i.quantidade for i in self.itens.all()), Decimal("0.00"))
        for escolha in self.escolhas.all():
            precos = [o.produto.preco for o in escolha.opcoes.all()]
            if precos:
                total += min(precos) * escolha.quantidade
        return total

    @property
    def economia(self):
        return self.preco_avulso - self.preco

    def necessidade_fixa(self):
        """{pk: (produto, qtd)} dos itens que vêm sempre, já abertos pela ficha."""
        necessidade = {}
        for item in self.itens.all():
            for produto, quantidade in item.produto.partes():
                somar_parte(necessidade, produto, quantidade * item.quantidade)
        return necessidade

    def necessidade(self, escolhas=None):
        """
        O que um combo consome com estas escolhas: {escolha_id: produto_id}.
        É isso que vale na hora de conferir e baixar o estoque.
        """
        necessidade = self.necessidade_fixa()
        escolhas = {int(k): int(v) for k, v in (escolhas or {}).items()}
        for escolha in self.escolhas.all():
            opcao = escolha.opcao(escolhas.get(escolha.pk))
            if not opcao:
                continue
            for produto, quantidade in opcao.produto.partes():
                somar_parte(necessidade, produto, quantidade * escolha.quantidade)
        return necessidade

    def quantos_cabem_com(self, escolhas=None):
        return cabem(self.necessidade(escolhas))

    @property
    def quantos_cabem(self):
        """
        Teto do cardápio: considera a opção mais farta de cada escolha, porque
        o cliente ainda vai decidir qual quer. A conta exata acontece quando
        ele escolhe, e de novo na confirmação do pedido.
        """
        teto = cabem(self.necessidade_fixa()) if self.itens.all() else None
        for escolha in self.escolhas.all():
            melhor = max((o.quantos_cabem for o in escolha.opcoes.all()), default=0)
            teto = melhor if teto is None else min(teto, melhor)
        return teto or 0

    @property
    def tem_escolhas(self):
        return bool(self.escolhas.all())

    @property
    def disponivel(self):
        return self.ativo and self.quantos_cabem > 0

    @property
    def montavel(self):
        """Combo sem nenhum conteúdo não deve aparecer para venda."""
        return bool(self.itens.all()) or bool(self.escolhas.all())


class ComboItem(models.Model):
    combo = models.ForeignKey(Combo, related_name="itens", on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = [("combo", "produto")]
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantidade} x {self.produto.nome}"


class ComboEscolha(models.Model):
    """
    Uma decisão que o cliente toma ao pedir o combo — “Bebida”, por exemplo —
    com as opções que valem para ela (Coca normal ou Coca Zero).
    """
    combo = models.ForeignKey(Combo, related_name="escolhas", on_delete=models.CASCADE)
    nome = models.CharField(max_length=60, help_text="ex: Bebida")
    quantidade = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)],
        help_text="Quantas unidades da opção escolhida entram no combo.",
    )
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["ordem", "id"]
        unique_together = [("combo", "nome")]
        verbose_name = "escolha do combo"
        verbose_name_plural = "escolhas do combo"

    def __str__(self):
        return f"{self.combo.nome} · {self.nome}"

    def opcao(self, produto_id):
        if not produto_id:
            return None
        return next((o for o in self.opcoes.all() if o.produto_id == int(produto_id)), None)

    def opcoes_disponiveis(self):
        return [o for o in self.opcoes.all() if o.quantos_cabem > 0]

    @property
    def resumo(self):
        return " ou ".join(o.produto.nome for o in self.opcoes.all())


class ComboEscolhaOpcao(models.Model):
    escolha = models.ForeignKey(ComboEscolha, related_name="opcoes", on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    adicional = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Quanto some no preço do combo se o cliente escolher esta opção.",
    )

    class Meta:
        unique_together = [("escolha", "produto")]
        ordering = ["produto__nome"]
        verbose_name = "opção"
        verbose_name_plural = "opções"

    def __str__(self):
        return self.produto.nome

    @property
    def quantos_cabem(self):
        return cabem({
            p.pk: (p, q * self.escolha.quantidade) for p, q in self.produto.partes()
        })


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
                "escolhas": [],
            })
        for pc in self.combos.select_related("combo").prefetch_related(
            "combo__itens__produto", "escolhas__produto"
        ):
            saida.append({
                "nome": pc.combo.nome,
                "qtd": pc.quantidade,
                "unit": pc.preco_unitario,
                "subtotal": pc.preco_unitario * pc.quantidade,
                "combo": pc.combo,
                "escolhas": list(pc.escolhas.all()),
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

    def clean(self):
        # quantidade vazia é erro de campo obrigatório; aqui ela ainda chega None
        if self.quantidade is not None and self.quantidade <= 0:
            raise ValidationError("Quantidade deve ser positiva.")

    def __str__(self):
        return f"{self.quantidade} x {self.combo.nome}"

    def necessidade(self):
        """O que sai do estoque por unidade deste combo, com o que foi escolhido."""
        necessidade = self.combo.necessidade_fixa()
        for escolhida in self.escolhas.all():
            for produto, quantidade in escolhida.produto.partes():
                somar_parte(necessidade, produto, quantidade * escolhida.quantidade)
        return necessidade

    @property
    def escolhas_resumo(self):
        return " · ".join(f"{e.rotulo}: {e.produto.nome}" for e in self.escolhas.all())


class PedidoComboEscolha(models.Model):
    """O que o cliente escolheu neste combo. Rótulo e preço ficam congelados."""
    pedido_combo = models.ForeignKey(PedidoCombo, related_name="escolhas", on_delete=models.CASCADE)
    escolha = models.ForeignKey(ComboEscolha, null=True, blank=True, on_delete=models.SET_NULL)
    rotulo = models.CharField(max_length=60)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.PositiveIntegerField(default=1)
    adicional = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.rotulo}: {self.produto.nome}"


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
