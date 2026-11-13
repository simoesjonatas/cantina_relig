# views.py (ou forms.py se preferir separar)
from django.forms import ModelForm, inlineformset_factory
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import (
    Pedido, PedidoItem, Produto, ProdutoComponente, Combo, ComboItem,
    ComboEscolha, ComboEscolhaOpcao, PedidoCombo, Categoria,
)

class PedidoForm(ModelForm):
    class Meta:
        model = Pedido
        fields = ["nome_cliente", "consumo", "observacao"]
        labels = {"consumo": "Onde vai comer"}
        widgets = {
            "consumo": forms.RadioSelect,
            "observacao": forms.Textarea(attrs={"rows": 3, "placeholder": "Observações..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # o padrão é comer no local
        self.fields["consumo"].initial = Pedido.Consumo.LOCAL
        self.fields["consumo"].empty_label = None

class CategoriaForm(ModelForm):
    class Meta:
        model = Categoria
        fields = ["nome", "ordem"]
        labels = {"nome": "Nome da categoria", "ordem": "Ordem no cardápio"}
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "ex: Lanches"}),
            "ordem": forms.NumberInput(attrs={"min": "0"}),
        }


class ProdutoForm(ModelForm):
    class Meta:
        model = Produto
        fields = ["nome", "categoria", "descricao", "foto", "preco", "estoque", "insumo", "ativo"]
        labels = {
            "nome": "Nome do produto",
            "categoria": "Categoria",
            "descricao": "Descrição curta",
            "foto": "Foto",
            "preco": "Preço (R$)",
            "estoque": "Quantidade em estoque",
            "insumo": "É um insumo",
            "ativo": "Disponível para venda",
        }
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "ex: pastel de carne"}),
            "descricao": forms.TextInput(attrs={"placeholder": "ex: massa fina, recheio de carne moída"}),
            "preco": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "estoque": forms.NumberInput(attrs={"min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # insumo não tem preço de venda, e produto montado não tem estoque
        # próprio: os dois campos podem vir em branco e valem zero
        self.fields["preco"].required = False
        self.fields["estoque"].required = False

    def clean_preco(self):
        preco = self.cleaned_data.get("preco")
        if preco is None:
            return 0
        if preco < 0:
            raise forms.ValidationError("O preço não pode ser negativo.")
        return preco

    def clean_estoque(self):
        return self.cleaned_data.get("estoque") or 0

    def clean(self):
        dados = super().clean()
        if not dados.get("insumo") and not dados.get("preco"):
            self.add_error("preco", "Produto vendido precisa de preço. Marque “É um insumo” se ele só compõe outros.")
        return dados


class ProdutoComponenteForm(ModelForm):
    """Uma linha da ficha técnica: 2× disco de hambúrguer, por exemplo."""

    class Meta:
        model = ProdutoComponente
        fields = ["insumo", "quantidade"]
        labels = {"insumo": "Insumo", "quantidade": "Quantos entram"}
        widgets = {"quantidade": forms.NumberInput(attrs={"min": "1"})}

    def __init__(self, *args, produto=None, **kwargs):
        super().__init__(*args, **kwargs)
        # só itens que têm estoque próprio: quem já é montado por outros não
        # pode virar insumo, senão a baixa viraria uma corrente
        candidatos = Produto.objects.exclude(componentes__isnull=False)
        if produto and produto.pk:
            candidatos = candidatos.exclude(pk=produto.pk)
        self.fields["insumo"].queryset = candidatos.order_by("nome")
        # o __str__ do produto mostra o preço, que aqui não diz nada;
        # o que ajuda a escolher é quanto ainda tem na prateleira
        self.fields["insumo"].label_from_instance = (
            lambda p: f"{p.nome} — {p.estoque} em estoque"
        )
        self.fields["insumo"].required = False
        self.fields["quantidade"].required = False

    def has_changed(self):
        # a linha em branco já vem com um valor padrão no campo de número, e
        # o Django trataria isso como preenchida — aí tentaria salvar sem o
        # principal e estouraria no banco
        if not self.instance.pk and not self.data.get(self.add_prefix("insumo")):
            return False
        return super().has_changed()

    def clean(self):
        dados = super().clean()
        if dados.get("insumo") and not dados.get("quantidade"):
            dados["quantidade"] = 1
        return dados


class ProdutoComponenteBaseFormSet(forms.BaseInlineFormSet):
    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["produto"] = self.instance
        return kwargs

    def clean(self):
        super().clean()
        vistos = set()
        for form in self.forms:
            dados = getattr(form, "cleaned_data", None) or {}
            insumo = dados.get("insumo")
            if not insumo or dados.get("DELETE"):
                continue
            if insumo.pk in vistos:
                raise forms.ValidationError(f"“{insumo.nome}” aparece duas vezes na ficha.")
            vistos.add(insumo.pk)


ProdutoComponenteFormSet = inlineformset_factory(
    Produto, ProdutoComponente, form=ProdutoComponenteForm, fk_name="produto",
    formset=ProdutoComponenteBaseFormSet, extra=1, can_delete=True,
)


class PedidoItemForm(ModelForm):
    class Meta:
        model = PedidoItem
        # não exibimos preco_unitario
        fields = ["produto", "quantidade",]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # produto desativado (ou insumo) não deve aparecer para quem monta o pedido
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True, insumo=False)

    def has_changed(self):
        # a quantidade já vem com 1 na tela, o que faria o Django tratar uma
        # linha em branco como preenchida e exigir o produto — isso impedia
        # fechar um pedido que só tem combo
        if not self.instance.pk and not self.data.get(self.add_prefix("produto")):
            return False
        return super().has_changed()

PedidoItemFormSet = inlineformset_factory(
    Pedido, PedidoItem, form=PedidoItemForm, extra=1, can_delete=True
)


ROTULOS_USUARIO = {
    "username": "Usuário (login)",
    "first_name": "Nome",
    "email": "E-mail",
    "is_staff": "Administrador",
    "is_active": "Pode entrar no sistema",
}

AJUDAS_USUARIO = {
    "username": "Sem espaços. É o que a pessoa digita para entrar.",
    "is_staff": "Administrador também gerencia usuários.",
    "is_active": "Desmarcado, a pessoa não consegue mais entrar — mas o histórico fica.",
}


class UsuarioCriarForm(UserCreationForm):
    field_order = ["username", "first_name", "email", "password1", "password2", "is_staff", "is_active"]

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "first_name", "email", "is_staff", "is_active"]
        labels = ROTULOS_USUARIO
        help_texts = AJUDAS_USUARIO

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].initial = True
        self.fields["first_name"].required = True
        self.fields["username"].help_text = AJUDAS_USUARIO["username"]


class UsuarioEditarForm(forms.ModelForm):
    """Sem senha: trocar senha é uma tela à parte."""

    class Meta:
        model = User
        fields = ["username", "first_name", "email", "is_staff", "is_active"]
        labels = ROTULOS_USUARIO
        help_texts = AJUDAS_USUARIO

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True


class ComboForm(ModelForm):
    class Meta:
        model = Combo
        fields = ["nome", "descricao", "foto", "preco", "ativo"]
        labels = {
            "nome": "Nome do combo",
            "descricao": "Descrição curta",
            "foto": "Foto",
            "preco": "Preço do combo (R$)",
            "ativo": "Disponível para venda",
        }
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "ex: Combo Bacon"}),
            "descricao": forms.TextInput(attrs={"placeholder": "ex: o clássico da casa"}),
            "preco": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def clean_preco(self):
        preco = self.cleaned_data["preco"]
        if preco < 0:
            raise forms.ValidationError("O preço não pode ser negativo.")
        return preco


class ComboItemForm(ModelForm):
    class Meta:
        model = ComboItem
        fields = ["produto", "quantidade"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True, insumo=False)


ComboItemFormSet = inlineformset_factory(
    Combo, ComboItem, form=ComboItemForm, extra=1, can_delete=True
)


class ComboEscolhaForm(ModelForm):
    """Uma pergunta que o combo faz ao cliente: “Bebida”, “Acompanhamento”."""

    class Meta:
        model = ComboEscolha
        fields = ["nome", "quantidade", "ordem"]
        labels = {
            "nome": "O que o cliente escolhe",
            "quantidade": "Quantas unidades entram",
            "ordem": "Ordem na tela",
        }
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "ex: Bebida"}),
            "quantidade": forms.NumberInput(attrs={"min": "1"}),
            "ordem": forms.NumberInput(attrs={"min": "0"}),
        }


class ComboEscolhaOpcaoForm(ModelForm):
    class Meta:
        model = ComboEscolhaOpcao
        fields = ["produto", "adicional"]
        labels = {"produto": "Opção", "adicional": "Cobra a mais (R$)"}
        widgets = {"adicional": forms.NumberInput(attrs={"step": "0.01", "min": "0"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True, insumo=False).order_by("nome")
        self.fields["produto"].required = False
        self.fields["adicional"].required = False

    def has_changed(self):
        # a linha em branco já vem com um valor padrão no campo de número, e
        # o Django trataria isso como preenchida — aí tentaria salvar sem o
        # principal e estouraria no banco
        if not self.instance.pk and not self.data.get(self.add_prefix("produto")):
            return False
        return super().has_changed()

    def clean_adicional(self):
        return self.cleaned_data.get("adicional") or 0


class ComboEscolhaOpcaoBaseFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        validas = [
            f.cleaned_data
            for f in self.forms
            if (getattr(f, "cleaned_data", None) or {}).get("produto")
            and not f.cleaned_data.get("DELETE")
        ]
        if not validas:
            raise forms.ValidationError("Cadastre pelo menos uma opção para o cliente escolher.")
        produtos = [d["produto"].pk for d in validas]
        if len(produtos) != len(set(produtos)):
            raise forms.ValidationError("A mesma opção aparece duas vezes.")


ComboEscolhaOpcaoFormSet = inlineformset_factory(
    ComboEscolha, ComboEscolhaOpcao, form=ComboEscolhaOpcaoForm,
    formset=ComboEscolhaOpcaoBaseFormSet, extra=2, can_delete=True,
)


class PedidoComboForm(ModelForm):
    class Meta:
        model = PedidoCombo
        fields = ["combo", "quantidade"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["combo"].queryset = Combo.objects.filter(ativo=True).prefetch_related("itens")
        self.fields["combo"].required = False
        self.fields["combo"].required = False
        self.fields["quantidade"].required = False


PedidoComboFormSet = inlineformset_factory(
    Pedido, PedidoCombo, form=PedidoComboForm, extra=0, can_delete=True
)
