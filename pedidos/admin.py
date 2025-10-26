from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import ValidationError
from .models import Produto, Pedido, PedidoItem, MovimentoEstoque, ComandaCozinha
from .services import confirmar_pedido, cancelar_pedido

@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ("nome", "preco", "estoque", "ativo", "criado_em")
    list_filter = ("ativo",)
    search_fields = ("nome",)

class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 1
    autocomplete_fields = ("produto",)
    fields = ("produto", "quantidade", "preco_unitario")

@admin.action(description="Confirmar e Enviar à Cozinha")
def action_confirmar(modeladmin, request, queryset):
    ok, falhas = 0, 0
    for pedido in queryset:
        try:
            confirmar_pedido(pedido.id)
            ok += 1
        except ValidationError as e:
            falhas += 1
            messages.error(request, f"Pedido {pedido.numero}: {e}")
    if ok:
        messages.success(request, f"{ok} pedido(s) confirmado(s) e enviado(s) à cozinha.")
    if falhas:
        messages.warning(request, f"{falhas} pedido(s) falharam.")

@admin.action(description="Cancelar pedido (restaura estoque)")
def action_cancelar(modeladmin, request, queryset):
    for pedido in queryset:
        cancelar_pedido(pedido.id)
    messages.success(request, "Pedido(s) cancelado(s). Estoque restaurado.")

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("numero", "nome_cliente", "status", "total", "criado_em")
    list_filter = ("status", "criado_em")
    search_fields = ("numero", "nome_cliente")
    inlines = [PedidoItemInline]
    actions = [action_confirmar, action_cancelar]

@admin.register(MovimentoEstoque)
class MovimentoEstoqueAdmin(admin.ModelAdmin):
    list_display = ("produto", "tipo", "quantidade", "pedido", "criado_em")
    list_filter = ("tipo", "criado_em")
    search_fields = ("produto__nome", "pedido__numero")

@admin.register(ComandaCozinha)
class ComandaCozinhaAdmin(admin.ModelAdmin):
    list_display = ("pedido", "impresso_em")
