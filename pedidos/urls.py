from django.urls import path
from . import views
from . import views_estoque
from . import views_cliente

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


    # Cliente
    # Fluxo do cliente (sem login)
    path("cliente/pedido/novo/", views_cliente.pedido_novo_cliente, name="cliente_pedido_novo"),
    path("cliente/pedido/<int:pk>/", views_cliente.pedido_cliente_detalhe, name="cliente_pedido_detalhe"),
    path("cliente/pedido/<int:pk>/pagar/", views_cliente.pedido_cliente_enviar_pagamento, name="cliente_pedido_enviar_pagamento"),
    path("cliente/pedido/<int:pk>/pagamento/", 
     views_cliente.pedido_cliente_pagamento, 
     name="cliente_pedido_pagamento"),


    # Caixa
    path("caixa/pendentes/", views.caixa_pendentes, name="caixa_pendentes"),
    path("caixa/confirmar/<int:pedido_id>/", views.caixa_confirmar_pagamento, name="caixa_confirmar_pagamento"),
    path("caixa/buscar/", views.caixa_buscar_pedido, name="caixa_buscar_pedido"),



]
