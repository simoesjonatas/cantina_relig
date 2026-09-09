# views.py (ou forms.py se preferir separar)
from django.forms import ModelForm, inlineformset_factory
from django import forms
from .models import Pedido, PedidoItem, Produto

class PedidoForm(ModelForm):
    class Meta:
        model = Pedido
        fields = ["nome_cliente", "observacao"]
        widgets = {
            "observacao": forms.Textarea(attrs={"rows": 3, "placeholder": "Observações..."}),
        }

class ProdutoForm(ModelForm):
    class Meta:
        model = Produto
        fields = ["nome", "preco", "estoque", "ativo"]
        labels = {
            "nome": "Nome do produto",
            "preco": "Preço (R$)",
            "estoque": "Quantidade em estoque",
            "ativo": "Disponível para venda",
        }
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "ex: pastel de carne"}),
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

PedidoItemFormSet = inlineformset_factory(
    Pedido, PedidoItem, form=PedidoItemForm, extra=1, can_delete=True
)
