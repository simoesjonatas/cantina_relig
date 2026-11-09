from django.urls import path
from . import views
from . import views_estoque
from . import views_cliente
from . import views_cardapio
from . import views_painel
from . import views_produtos
from . import views_combos
from . import views_categorias
from . import views_usuarios

app_name = "pedidos"

urlpatterns = [
    path("novo/", views.criar_pedido, name="criar"),
    path("", views.pedido_lista, name="lista"),
    path("<int:pk>/", views.detalhe_pedido, name="detalhe"),
    path("<int:pk>/confirmar/", views.confirmar_enviar, name="confirmar"),
    path("cozinha/", views.cozinha_painel, name="cozinha"),

    # Painel público (TV da cantina): "Em preparo" x "Pronto"
    path("painel/", views_painel.painel, name="painel"),
    path("painel/dados/", views_painel.painel_dados, name="painel_dados"),
    path("<int:pk>/concluir/", views.concluir_pedido_view, name="concluir"),
    path("<int:pk>/cancelar/", views.cancelar_pedido_view, name="cancelar"),
    path("<int:pk>/retirado/", views.marcar_retirado_view, name="retirado"),

    # Balcão (quem entrega o pedido)
    path("balcao/", views.balcao_painel, name="balcao"),
    path("balcao/dados/", views.balcao_dados, name="balcao_dados"),

    # Usuários (só administradores)
    path("usuarios/", views_usuarios.usuario_lista, name="usuario_lista"),
    path("usuarios/novo/", views_usuarios.usuario_criar, name="usuario_criar"),
    path("usuarios/<int:pk>/editar/", views_usuarios.usuario_editar, name="usuario_editar"),
    path("usuarios/<int:pk>/senha/", views_usuarios.usuario_senha, name="usuario_senha"),
    path("usuarios/<int:pk>/acesso/", views_usuarios.usuario_alternar_ativo, name="usuario_alternar_ativo"),
    path("usuarios/<int:pk>/excluir/", views_usuarios.usuario_excluir, name="usuario_excluir"),

    # Categorias do cardápio
    path("categorias/", views_categorias.categoria_lista, name="categoria_lista"),
    path("categorias/<int:pk>/editar/", views_categorias.categoria_editar, name="categoria_editar"),
    path("categorias/<int:pk>/excluir/", views_categorias.categoria_excluir, name="categoria_excluir"),

    # Combos
    path("combos/", views_combos.combo_lista, name="combo_lista"),
    path("combos/novo/", views_combos.combo_criar, name="combo_criar"),
    path("combos/<int:pk>/editar/", views_combos.combo_editar, name="combo_editar"),
    path("combos/<int:pk>/situacao/", views_combos.combo_alternar_ativo, name="combo_alternar_ativo"),
    path("combos/<int:pk>/excluir/", views_combos.combo_excluir, name="combo_excluir"),

    # Produtos (CRUD próprio, fora do admin)
    path("produtos/", views_produtos.produto_lista, name="produto_lista"),
    path("produtos/novo/", views_produtos.produto_criar, name="produto_criar"),
    path("produtos/<int:pk>/editar/", views_produtos.produto_editar, name="produto_editar"),
    path("produtos/<int:pk>/situacao/", views_produtos.produto_alternar_ativo, name="produto_alternar_ativo"),
    path("produtos/<int:pk>/excluir/", views_produtos.produto_excluir, name="produto_excluir"),

    path("estoque/saidas/", views_estoque.saidas_por_produto, name="saidas-por-produto"),
    path("estoque/saidas/<int:produto_id>/", views_estoque.saidas_do_produto_detail, name="saidas-do-produto-detail"),


    # Cardápio público (cliente monta o carrinho sem login)
    path("cardapio/", views_cardapio.cardapio, name="cardapio"),
    path("cardapio/adicionar/", views_cardapio.cardapio_adicionar, name="cardapio_adicionar"),
    path("cardapio/carrinho/", views_cardapio.carrinho_ver, name="carrinho"),
    path("cardapio/finalizar/", views_cardapio.finalizar, name="cardapio_finalizar"),
    path("cardapio/meus-pedidos/", views_cardapio.meus_pedidos, name="meus_pedidos"),

    # Cliente
    # Fluxo do cliente (sem login)
    path("cliente/pedido/novo/", views_cliente.pedido_novo_cliente, name="cliente_pedido_novo"),
    path("cliente/pedido/<int:pk>/", views_cliente.pedido_cliente_detalhe, name="cliente_pedido_detalhe"),
    path("cliente/pedido/<int:pk>/status/", views_cliente.pedido_cliente_status, name="cliente_pedido_status"),
    path("cliente/pedido/<int:pk>/pagar/", views_cliente.pedido_cliente_enviar_pagamento, name="cliente_pedido_enviar_pagamento"),
    path("cliente/pedido/<int:pk>/pagamento/", 
     views_cliente.pedido_cliente_pagamento, 
     name="cliente_pedido_pagamento"),


    # Caixa
    path("caixa/pendentes/", views.caixa_pendentes, name="caixa_pendentes"),
    path("caixa/pendentes/dados/", views.caixa_pendentes_dados, name="caixa_pendentes_dados"),
    path("caixa/confirmar/<int:pedido_id>/", views.caixa_confirmar_pagamento, name="caixa_confirmar_pagamento"),
    path("caixa/buscar/", views.caixa_buscar_pedido, name="caixa_buscar_pedido"),



]
