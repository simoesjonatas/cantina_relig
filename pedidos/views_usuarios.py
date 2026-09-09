# views_usuarios.py
# Gerência de usuários fora do admin. Só administradores entram aqui:
# sem essa trava, qualquer pessoa com login poderia criar uma conta de administrador.
from functools import wraps

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from .forms import UsuarioCriarForm, UsuarioEditarForm


def somente_admin(view):
    @wraps(view)
    @login_required
    def _protegida(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "Só administradores podem gerenciar usuários.")
            return redirect("home")
        return view(request, *args, **kwargs)
    return _protegida


def _e_o_ultimo_admin(usuario):
    """Sobrou algum outro administrador ativo além deste?"""
    return not User.objects.filter(
        is_staff=True, is_active=True
    ).exclude(pk=usuario.pk).exists()


@somente_admin
def usuario_lista(request):
    usuarios = User.objects.all()

    busca = request.GET.get("q", "").strip()
    if busca:
        usuarios = usuarios.filter(
            Q(username__icontains=busca)
            | Q(first_name__icontains=busca)
            | Q(email__icontains=busca)
        )

    return render(request, "usuarios/lista.html", {
        "usuarios": usuarios.order_by("-is_active", "username"),
        "busca": busca,
        "resumo": {
            "total": User.objects.count(),
            "ativos": User.objects.filter(is_active=True).count(),
            "admins": User.objects.filter(is_staff=True, is_active=True).count(),
        },
    })


@somente_admin
def usuario_criar(request):
    if request.method == "POST":
        form = UsuarioCriarForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            messages.success(request, f"Usuário “{usuario.username}” criado.")
            return redirect("pedidos:usuario_lista")
    else:
        form = UsuarioCriarForm()

    return render(request, "usuarios/form.html", {"form": form, "usuario": None})


@somente_admin
def usuario_editar(request, pk):
    usuario = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = UsuarioEditarForm(request.POST, instance=usuario)
        if form.is_valid():
            perde_acesso = not form.cleaned_data["is_staff"] or not form.cleaned_data["is_active"]

            if usuario == request.user and perde_acesso:
                messages.error(
                    request,
                    "Você não pode tirar o próprio acesso de administrador — ficaria trancado para fora."
                )
                return redirect("pedidos:usuario_editar", pk=pk)

            if usuario.is_staff and usuario.is_active and perde_acesso and _e_o_ultimo_admin(usuario):
                messages.error(
                    request,
                    f"“{usuario.username}” é o único administrador ativo. "
                    "Promova outra pessoa antes de mudar este."
                )
                return redirect("pedidos:usuario_editar", pk=pk)

            form.save()
            messages.success(request, f"Usuário “{usuario.username}” atualizado.")
            return redirect("pedidos:usuario_lista")
    else:
        form = UsuarioEditarForm(instance=usuario)

    return render(request, "usuarios/form.html", {"form": form, "usuario": usuario})


@somente_admin
def usuario_senha(request, pk):
    usuario = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        form = SetPasswordForm(usuario, request.POST)
        if form.is_valid():
            form.save()
            # trocar a própria senha invalidaria a sessão atual
            if usuario == request.user:
                update_session_auth_hash(request, usuario)
            messages.success(request, f"Senha de “{usuario.username}” alterada.")
            return redirect("pedidos:usuario_lista")
    else:
        form = SetPasswordForm(usuario)

    return render(request, "usuarios/senha.html", {"form": form, "usuario": usuario})


@somente_admin
@require_POST
def usuario_alternar_ativo(request, pk):
    usuario = get_object_or_404(User, pk=pk)

    if usuario == request.user:
        messages.error(request, "Você não pode desativar a própria conta.")
    elif usuario.is_active and usuario.is_staff and _e_o_ultimo_admin(usuario):
        messages.error(request, f"“{usuario.username}” é o único administrador ativo.")
    else:
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=["is_active"])
        estado = "liberado" if usuario.is_active else "bloqueado"
        messages.success(request, f"Acesso de “{usuario.username}” {estado}.")

    return redirect("pedidos:usuario_lista")


@somente_admin
def usuario_excluir(request, pk):
    usuario = get_object_or_404(User, pk=pk)
    e_voce = usuario == request.user
    ultimo_admin = usuario.is_staff and _e_o_ultimo_admin(usuario)

    if request.method == "POST":
        if e_voce:
            messages.error(request, "Você não pode excluir a própria conta.")
        elif ultimo_admin:
            messages.error(request, f"“{usuario.username}” é o único administrador.")
        else:
            nome = usuario.username
            usuario.delete()
            messages.success(request, f"Usuário “{nome}” excluído.")
        return redirect("pedidos:usuario_lista")

    return render(request, "usuarios/excluir.html", {
        "usuario": usuario,
        "e_voce": e_voce,
        "ultimo_admin": ultimo_admin,
    })
