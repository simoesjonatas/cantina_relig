from django.urls import path
from . import views

app_name = "pedidos"

urlpatterns = [
    path("novo/", views.criar_pedido, name="criar"),
    path("<int:pk>/", views.detalhe_pedido, name="detalhe"),
    path("<int:pk>/confirmar/", views.confirmar_enviar, name="confirmar"),
    path("cozinha/", views.cozinha_painel, name="cozinha"),
    path("<int:pk>/concluir/", views.concluir_pedido_view, name="concluir"),
    path("<int:pk>/cancelar/", views.cancelar_pedido_view, name="cancelar"),


]
