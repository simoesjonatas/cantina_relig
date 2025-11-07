from django.urls import path
from . import views
from . import views_estoque

app_name = "pedidos"

urlpatterns = [
    path("novo/", views.criar_pedido, name="criar"),
    path("<int:pk>/", views.detalhe_pedido, name="detalhe"),
    path("<int:pk>/confirmar/", views.confirmar_enviar, name="confirmar"),
    path("cozinha/", views.cozinha_painel, name="cozinha"),
    path("<int:pk>/concluir/", views.concluir_pedido_view, name="concluir"),
    path("<int:pk>/cancelar/", views.cancelar_pedido_view, name="cancelar"),

    path("estoque/saidas/", views_estoque.saidas_por_produto, name="saidas-por-produto"),
    path("estoque/saidas/<int:produto_id>/", views_estoque.saidas_do_produto_detail, name="saidas-do-produto-detail"),



]
