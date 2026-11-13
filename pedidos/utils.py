def querystring_sem_pagina(request):
    """Filtros atuais da URL sem o 'page', já escapados (espaços, acentos, &)."""
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


# --- combos com escolha ----------------------------------------------------
# Dois "Combo Duplo" com bebidas diferentes são linhas diferentes no carrinho,
# então a identidade de uma linha é o combo mais o que foi escolhido. Isso
# vira um texto curto que cabe numa chave de sessão e num input hidden:
#   "7|3=12,4=20"  →  combo 7, escolha 3 = produto 12, escolha 4 = produto 20

def escolhas_para_texto(escolhas):
    """{escolha_id: produto_id} -> '3=12,4=20' (ordenado, para a chave ser estável)."""
    if not escolhas:
        return ""
    pares = sorted((int(e), int(p)) for e, p in escolhas.items() if p)
    return ",".join(f"{e}={p}" for e, p in pares)


def texto_para_escolhas(texto):
    """'3=12,4=20' -> {3: 12, 4: 20}. Ignora pedaço estranho em vez de quebrar."""
    escolhas = {}
    for parte in (texto or "").split(","):
        if "=" not in parte:
            continue
        esquerda, _, direita = parte.partition("=")
        try:
            escolhas[int(esquerda)] = int(direita)
        except ValueError:
            continue
    return escolhas


def chave_combo(combo_pk, escolhas=None):
    texto = escolhas_para_texto(escolhas)
    return f"{combo_pk}|{texto}" if texto else str(combo_pk)


def ler_chave_combo(chave):
    """Devolve (combo_pk, {escolha_id: produto_id}) a partir da chave da linha."""
    combo, _, texto = str(chave).partition("|")
    try:
        combo_pk = int(combo)
    except ValueError:
        return None, {}
    return combo_pk, texto_para_escolhas(texto)


def escolhas_do_post(post, prefixo="escolha_"):
    """Lê os selects de escolha de um formulário: escolha_3=12 -> {3: 12}."""
    escolhas = {}
    for chave, valor in post.items():
        if not chave.startswith(prefixo) or not valor:
            continue
        try:
            escolhas[int(chave[len(prefixo):])] = int(valor)
        except ValueError:
            continue
    return escolhas
