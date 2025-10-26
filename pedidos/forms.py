# views.py (ou forms.py se preferir separar)
from django.forms import ModelForm, inlineformset_factory
from .models import Pedido, PedidoItem

class PedidoForm(ModelForm):
    class Meta:
        model = Pedido
        fields = ["nome_cliente"]

class PedidoItemForm(ModelForm):
    class Meta:
        model = PedidoItem
        # não exibimos preco_unitario
        fields = ["produto", "quantidade"]

PedidoItemFormSet = inlineformset_factory(
    Pedido, PedidoItem, form=PedidoItemForm, extra=1, can_delete=True
)
