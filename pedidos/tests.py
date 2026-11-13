from decimal import Decimal

from django.test import TestCase

from .models import (
    Produto, ProdutoComponente, Combo, ComboItem, ComboEscolha, ComboEscolhaOpcao,
    Pedido, PedidoItem, PedidoCombo, MovimentoEstoque,
)
from .services import confirmar_pedido, cancelar_pedido, registrar_escolhas
from .utils import chave_combo, ler_chave_combo


class FichaTecnicaTest(TestCase):
    """Duplo e triplo saem do mesmo pote de discos."""

    def setUp(self):
        self.disco = Produto.objects.create(nome="Disco de hambúrguer", insumo=True, estoque=10)
        self.pao = Produto.objects.create(nome="Pão", insumo=True, estoque=10)

        self.duplo = Produto.objects.create(nome="Hambúrguer Duplo", preco=Decimal("17.00"))
        ProdutoComponente.objects.create(produto=self.duplo, insumo=self.disco, quantidade=2)
        ProdutoComponente.objects.create(produto=self.duplo, insumo=self.pao, quantidade=1)

        self.triplo = Produto.objects.create(nome="Hambúrguer Triplo", preco=Decimal("19.00"))
        ProdutoComponente.objects.create(produto=self.triplo, insumo=self.disco, quantidade=3)
        ProdutoComponente.objects.create(produto=self.triplo, insumo=self.pao, quantidade=1)

    def test_estoque_vem_do_insumo_mais_apertado(self):
        # 10 discos e 10 pães: o disco é quem limita
        self.assertEqual(self.duplo.estoque_disponivel, 5)
        self.assertEqual(self.triplo.estoque_disponivel, 3)

    def test_produto_simples_mantem_estoque_proprio(self):
        coca = Produto.objects.create(nome="Coca-Cola", preco=Decimal("6.00"), estoque=7)
        self.assertEqual(coca.estoque_disponivel, 7)

    def test_duplos_e_triplos_dividem_o_mesmo_estoque(self):
        pedido = Pedido.objects.create(nome_cliente="Ana")
        PedidoItem.objects.create(pedido=pedido, produto=self.duplo, quantidade=2,
                                  preco_unitario=self.duplo.preco)
        PedidoItem.objects.create(pedido=pedido, produto=self.triplo, quantidade=1,
                                  preco_unitario=self.triplo.preco)

        confirmar_pedido(pedido.id)

        self.disco.refresh_from_db()
        self.pao.refresh_from_db()
        self.assertEqual(self.disco.estoque, 10 - (2 * 2 + 3))   # 2 duplos + 1 triplo = 7 discos
        self.assertEqual(self.pao.estoque, 10 - 3)

        self.duplo.refresh_from_db()
        self.assertEqual(self.duplo.estoque, 0)  # montado não guarda estoque próprio

    def test_nao_vende_mais_do_que_os_discos_permitem(self):
        pedido = Pedido.objects.create(nome_cliente="Bia")
        PedidoItem.objects.create(pedido=pedido, produto=self.duplo, quantidade=4,
                                  preco_unitario=self.duplo.preco)  # 8 discos
        PedidoItem.objects.create(pedido=pedido, produto=self.triplo, quantidade=1,
                                  preco_unitario=self.triplo.preco)  # +3 = 11 > 10

        with self.assertRaises(Exception) as erro:
            confirmar_pedido(pedido.id)
        self.assertIn("Disco de hambúrguer", str(erro.exception))

        self.disco.refresh_from_db()
        self.assertEqual(self.disco.estoque, 10)  # nada foi baixado

    def test_cancelar_devolve_os_insumos(self):
        pedido = Pedido.objects.create(nome_cliente="Caio")
        PedidoItem.objects.create(pedido=pedido, produto=self.triplo, quantidade=2,
                                  preco_unitario=self.triplo.preco)
        confirmar_pedido(pedido.id)
        self.disco.refresh_from_db()
        self.assertEqual(self.disco.estoque, 4)

        cancelar_pedido(pedido.id)
        self.disco.refresh_from_db()
        self.assertEqual(self.disco.estoque, 10)


class ComboComEscolhaTest(TestCase):
    """A bebida do combo é decidida por quem pede."""

    def setUp(self):
        self.disco = Produto.objects.create(nome="Disco", insumo=True, estoque=20)
        self.duplo = Produto.objects.create(nome="Duplo", preco=Decimal("17.00"))
        ProdutoComponente.objects.create(produto=self.duplo, insumo=self.disco, quantidade=2)

        self.batata = Produto.objects.create(nome="Batata", preco=Decimal("8.00"), estoque=10)
        self.coca = Produto.objects.create(nome="Coca-Cola", preco=Decimal("6.00"), estoque=4)
        self.zero = Produto.objects.create(nome="Coca-Cola ZERO", preco=Decimal("6.00"), estoque=9)

        self.combo = Combo.objects.create(nome="Combo Duplo Completo", preco=Decimal("25.90"))
        ComboItem.objects.create(combo=self.combo, produto=self.duplo, quantidade=1)
        ComboItem.objects.create(combo=self.combo, produto=self.batata, quantidade=1)

        self.bebida = ComboEscolha.objects.create(combo=self.combo, nome="Bebida")
        ComboEscolhaOpcao.objects.create(escolha=self.bebida, produto=self.coca)
        self.opcao_zero = ComboEscolhaOpcao.objects.create(
            escolha=self.bebida, produto=self.zero, adicional=Decimal("1.00")
        )

    def test_quantos_cabem_usa_a_opcao_mais_farta(self):
        # 20 discos = 10 duplos; batata 10; bebida: 4 cocas ou 9 zeros -> 9
        self.assertEqual(self.combo.quantos_cabem, 9)

    def test_quantos_cabem_com_a_escolha_feita(self):
        self.assertEqual(self.combo.quantos_cabem_com({self.bebida.pk: self.coca.pk}), 4)
        self.assertEqual(self.combo.quantos_cabem_com({self.bebida.pk: self.zero.pk}), 9)

    def test_baixa_apenas_a_bebida_escolhida(self):
        pedido = Pedido.objects.create(nome_cliente="Dani")
        pc = PedidoCombo.objects.create(
            pedido=pedido, combo=self.combo, quantidade=2, preco_unitario=self.combo.preco
        )
        registrar_escolhas(pc, {self.bebida.pk: self.zero.pk})

        confirmar_pedido(pedido.id)

        for produto in (self.disco, self.batata, self.coca, self.zero):
            produto.refresh_from_db()
        self.assertEqual(self.disco.estoque, 20 - 4)   # 2 combos × 1 duplo × 2 discos
        self.assertEqual(self.batata.estoque, 8)
        self.assertEqual(self.coca.estoque, 4)         # a normal não foi tocada
        self.assertEqual(self.zero.estoque, 7)

    def test_dois_combos_iguais_com_bebidas_diferentes(self):
        pedido = Pedido.objects.create(nome_cliente="Edu")
        for bebida in (self.coca, self.zero):
            pc = PedidoCombo.objects.create(
                pedido=pedido, combo=self.combo, quantidade=1, preco_unitario=self.combo.preco
            )
            registrar_escolhas(pc, {self.bebida.pk: bebida.pk})

        confirmar_pedido(pedido.id)

        self.coca.refresh_from_db()
        self.zero.refresh_from_db()
        self.assertEqual(self.coca.estoque, 3)
        self.assertEqual(self.zero.estoque, 8)

    def test_adicional_da_opcao_entra_no_preco(self):
        pedido = Pedido.objects.create(nome_cliente="Fê")
        pc = PedidoCombo.objects.create(
            pedido=pedido, combo=self.combo, quantidade=1, preco_unitario=self.combo.preco
        )
        extra = registrar_escolhas(pc, {self.bebida.pk: self.zero.pk})
        self.assertEqual(extra, Decimal("1.00"))
        self.assertEqual(pc.escolhas.get().rotulo, "Bebida")

    def test_combo_e_avulso_somam_no_mesmo_insumo(self):
        pedido = Pedido.objects.create(nome_cliente="Gui")
        # 4 combos (8 discos) + 2 duplos avulsos (4 discos) = 12, mas só há 20...
        PedidoItem.objects.create(pedido=pedido, produto=self.duplo, quantidade=2,
                                  preco_unitario=self.duplo.preco)
        pc = PedidoCombo.objects.create(
            pedido=pedido, combo=self.combo, quantidade=4, preco_unitario=self.combo.preco
        )
        registrar_escolhas(pc, {self.bebida.pk: self.zero.pk})

        confirmar_pedido(pedido.id)
        self.disco.refresh_from_db()
        self.assertEqual(self.disco.estoque, 20 - 12)


class ChaveDoCarrinhoTest(TestCase):
    def test_vai_e_volta(self):
        chave = chave_combo(7, {3: 12, 1: 20})
        self.assertEqual(chave, "7|1=20,3=12")       # ordenada: a mesma escolha gera a mesma chave
        self.assertEqual(ler_chave_combo(chave), (7, {1: 20, 3: 12}))

    def test_combo_sem_escolha_fica_so_com_o_id(self):
        self.assertEqual(chave_combo(7), "7")
        self.assertEqual(ler_chave_combo("7"), (7, {}))


class TelasTest(TestCase):
    """Percorre o caminho do cliente e as telas de cadastro."""

    def setUp(self):
        from django.contrib.auth.models import User
        self.staff = User.objects.create_user("atendente", password="x", is_staff=True)

        self.disco = Produto.objects.create(nome="Disco", insumo=True, estoque=20)
        self.duplo = Produto.objects.create(nome="Duplo", preco=Decimal("17.00"))
        ProdutoComponente.objects.create(produto=self.duplo, insumo=self.disco, quantidade=2)
        self.coca = Produto.objects.create(nome="Coca-Cola", preco=Decimal("6.00"), estoque=5)
        self.zero = Produto.objects.create(nome="Coca ZERO", preco=Decimal("6.00"), estoque=5)

        self.combo = Combo.objects.create(nome="Combo Duplo", preco=Decimal("21.90"))
        ComboItem.objects.create(combo=self.combo, produto=self.duplo, quantidade=1)
        self.bebida = ComboEscolha.objects.create(combo=self.combo, nome="Bebida")
        ComboEscolhaOpcao.objects.create(escolha=self.bebida, produto=self.coca)
        ComboEscolhaOpcao.objects.create(escolha=self.bebida, produto=self.zero,
                                         adicional=Decimal("1.00"))

    def test_cardapio_nao_mostra_insumo(self):
        resposta = self.client.get("/pedidos/cardapio/")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Duplo")
        self.assertNotContains(resposta, ">Disco<")
        self.assertContains(resposta, f'name="escolha_{self.bebida.pk}"')

    def test_caminho_do_cliente_com_escolha(self):
        resposta = self.client.post("/pedidos/cardapio/adicionar/", {
            "tipo": "combos", "pk": self.combo.pk,
            f"escolha_{self.bebida.pk}": self.zero.pk,
        })
        self.assertEqual(resposta.status_code, 302)

        # o mesmo combo com a outra bebida é uma segunda linha
        self.client.post("/pedidos/cardapio/adicionar/", {
            "tipo": "combos", "pk": self.combo.pk,
            f"escolha_{self.bebida.pk}": self.coca.pk,
        })

        carrinho = self.client.get("/pedidos/cardapio/carrinho/")
        self.assertContains(carrinho, "Coca ZERO")
        self.assertContains(carrinho, "Coca-Cola")

        # o adicional de R$ 1,00 da ZERO entra no preço
        self.assertContains(carrinho, "22,90")
        self.assertContains(carrinho, "21,90")

        enviado = self.client.post("/pedidos/cardapio/finalizar/", {
            "nome_cliente": "Hugo", "consumo": "LOCAL",
        })
        self.assertEqual(enviado.status_code, 302)

        pedido = Pedido.objects.get(nome_cliente="Hugo")
        self.assertEqual(pedido.combos.count(), 2)
        self.assertEqual(pedido.total, Decimal("44.80"))
        escolhidos = sorted(e.produto.nome for pc in pedido.combos.all() for e in pc.escolhas.all())
        self.assertEqual(escolhidos, ["Coca ZERO", "Coca-Cola"])

        confirmar_pedido(pedido.id)
        self.coca.refresh_from_db()
        self.zero.refresh_from_db()
        self.disco.refresh_from_db()
        self.assertEqual(self.coca.estoque, 4)
        self.assertEqual(self.zero.estoque, 4)
        self.assertEqual(self.disco.estoque, 16)

    def test_combo_sem_escolher_a_bebida_nao_entra(self):
        self.client.post("/pedidos/cardapio/adicionar/", {
            "tipo": "combos", "pk": self.combo.pk,
        })
        carrinho = self.client.get("/pedidos/cardapio/carrinho/")
        self.assertContains(carrinho, "carrinho está vazio")

    def test_telas_de_cadastro_abrem(self):
        self.client.force_login(self.staff)
        for url in [
            "/pedidos/produtos/", "/pedidos/produtos/novo/",
            f"/pedidos/produtos/{self.duplo.pk}/editar/",
            "/pedidos/combos/", f"/pedidos/combos/{self.combo.pk}/editar/",
            f"/pedidos/combos/{self.combo.pk}/escolhas/nova/",
            f"/pedidos/combos/escolhas/{self.bebida.pk}/editar/",
            "/pedidos/novo/", "/pedidos/caixa/pendentes/", "/pedidos/cozinha/",
            "/pedidos/balcao/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_cadastrar_produto_com_ficha(self):
        self.client.force_login(self.staff)
        resposta = self.client.post("/pedidos/produtos/novo/", {
            "nome": "Hambúrguer Triplo", "preco": "19.00", "estoque": "99",
            "ativo": "on",
            "componentes-TOTAL_FORMS": "1", "componentes-INITIAL_FORMS": "0",
            "componentes-MIN_NUM_FORMS": "0", "componentes-MAX_NUM_FORMS": "1000",
            "componentes-0-insumo": str(self.disco.pk), "componentes-0-quantidade": "3",
        })
        self.assertEqual(resposta.status_code, 302)
        triplo = Produto.objects.get(nome="Hambúrguer Triplo")
        self.assertEqual(triplo.estoque, 0)              # não guarda estoque próprio
        self.assertEqual(triplo.estoque_disponivel, 6)   # 20 discos / 3
        self.assertFalse(MovimentoEstoque.objects.filter(produto=triplo).exists())

    def test_cadastrar_escolha_no_combo(self):
        self.client.force_login(self.staff)
        resposta = self.client.post(f"/pedidos/combos/{self.combo.pk}/escolhas/nova/", {
            "nome": "Acompanhamento", "quantidade": "1", "ordem": "1",
            "opcoes-TOTAL_FORMS": "2", "opcoes-INITIAL_FORMS": "0",
            "opcoes-MIN_NUM_FORMS": "0", "opcoes-MAX_NUM_FORMS": "1000",
            "opcoes-0-produto": str(self.coca.pk), "opcoes-0-adicional": "",
            "opcoes-1-produto": "", "opcoes-1-adicional": "",
        })
        self.assertEqual(resposta.status_code, 302)
        escolha = ComboEscolha.objects.get(nome="Acompanhamento")
        self.assertEqual(escolha.opcoes.count(), 1)

    def test_pedido_pelo_balcao_com_escolha(self):
        self.client.force_login(self.staff)
        resposta = self.client.post("/pedidos/novo/", {
            "nome_cliente": "Iris", "consumo": "LOCAL", "observacao": "",
            "itens-TOTAL_FORMS": "0", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "combos-TOTAL_FORMS": "1", "combos-INITIAL_FORMS": "0",
            "combos-MIN_NUM_FORMS": "0", "combos-MAX_NUM_FORMS": "1000",
            "combos-0-combo": str(self.combo.pk), "combos-0-quantidade": "2",
            "combos-0-escolhas": f"{self.bebida.pk}={self.zero.pk}",
        })
        self.assertEqual(resposta.status_code, 302)
        pedido = Pedido.objects.get(nome_cliente="Iris")
        pc = pedido.combos.get()
        self.assertEqual(pc.escolhas.get().produto, self.zero)
        self.assertEqual(pc.preco_unitario, Decimal("22.90"))  # 21,90 + 1,00 da ZERO

    def test_balcao_manda_duas_bebidas_no_mesmo_combo(self):
        """Dois combos iguais no balcão, cada um com a sua bebida."""
        self.client.force_login(self.staff)
        resposta = self.client.post("/pedidos/novo/", {
            "nome_cliente": "Lia", "consumo": "LOCAL", "observacao": "",
            "itens-TOTAL_FORMS": "0", "itens-INITIAL_FORMS": "0",
            "itens-MIN_NUM_FORMS": "0", "itens-MAX_NUM_FORMS": "1000",
            "combos-TOTAL_FORMS": "2", "combos-INITIAL_FORMS": "0",
            "combos-MIN_NUM_FORMS": "0", "combos-MAX_NUM_FORMS": "1000",
            "combos-0-combo": str(self.combo.pk), "combos-0-quantidade": "2",
            "combos-0-escolhas": f"{self.bebida.pk}={self.coca.pk}",
            "combos-1-combo": str(self.combo.pk), "combos-1-quantidade": "1",
            "combos-1-escolhas": f"{self.bebida.pk}={self.zero.pk}",
        })
        self.assertEqual(resposta.status_code, 302)

        pedido = Pedido.objects.get(nome_cliente="Lia")
        self.assertEqual(pedido.combos.count(), 2)
        escolhido = {pc.quantidade: pc.escolhas.get().produto.nome for pc in pedido.combos.all()}
        self.assertEqual(escolhido, {2: "Coca-Cola", 1: "Coca ZERO"})
        # 2 × 21,90 + 1 × 22,90 (a ZERO cobra R$ 1,00 a mais)
        self.assertEqual(pedido.total, Decimal("66.70"))

        confirmar_pedido(pedido.id)
        self.coca.refresh_from_db()
        self.zero.refresh_from_db()
        self.disco.refresh_from_db()
        self.assertEqual(self.coca.estoque, 3)
        self.assertEqual(self.zero.estoque, 4)
        self.assertEqual(self.disco.estoque, 20 - 6)   # 3 combos × 1 duplo × 2 discos
