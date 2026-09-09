def querystring_sem_pagina(request):
    """Filtros atuais da URL sem o 'page', já escapados (espaços, acentos, &)."""
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()
