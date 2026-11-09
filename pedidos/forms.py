# views.py (ou forms.py se preferir separar)
from django.forms import ModelForm, inlineformset_factory
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Pedido, PedidoItem, Produto, Combo, ComboItem, PedidoCombo

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

class ProdutoForm(ModelForm):
    class Meta:
        model = Produto
        fields = ["nome", "descricao", "foto", "preco", "estoque", "ativo"]
        labels = {
            "nome": "Nome do produto",
            "descricao": "Descrição curta",
            "foto": "Foto",
            "preco": "Preço (R$)",
            "estoque": "Quantidade em estoque",
            "ativo": "Disponível para venda",
        }
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "ex: pastel de carne"}),
            "descricao": forms.TextInput(attrs={"placeholder": "ex: massa fina, recheio de carne moída"}),
            "preco": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "estoque": forms.NumberInput(attrs={"min": "0"}),
        }

    def clean_preco(self):
        preco = self.cleaned_data["preco"]
        if preco < 0:
            raise forms.ValidationError("O preço não pode ser negativo.")
        return preco


class PedidoItemForm(ModelForm):
    class Meta:
        model = PedidoItem
        # não exibimos preco_unitario
        fields = ["produto", "quantidade",]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # produto desativado não deve aparecer para quem monta o pedido
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True)

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
        self.fields["produto"].queryset = Produto.objects.filter(ativo=True)


ComboItemFormSet = inlineformset_factory(
    Combo, ComboItem, form=ComboItemForm, extra=1, can_delete=True, min_num=1, validate_min=True
)


class PedidoComboForm(ModelForm):
    class Meta:
        model = PedidoCombo
        fields = ["combo", "quantidade"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["combo"].queryset = Combo.objects.filter(ativo=True).prefetch_related("itens")
        self.fields["combo"].required = False
        self.fields["quantidade"].required = False


PedidoComboFormSet = inlineformset_factory(
    Pedido, PedidoCombo, form=PedidoComboForm, extra=0, can_delete=True
)
