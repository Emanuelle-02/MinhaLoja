from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.views import View
from .models import User


class Login(View):
    def get(self, request):
        return render(request, "login/login.html")

    def post(self, request):
        context = {"data": request.POST}
        username = request.POST.get("username")
        password = request.POST.get("password")

        if username and password:
            user = authenticate(username=username, password=password)
            if user:
                login(request, user)
                if user.is_admin or user.is_staff:
                    return redirect("index")
                else:
                    messages.add_message(
                        request,
                        messages.ERROR,
                        "Conta inativa ou sem permissões adequadas!",
                    )
                    return render(request, "login/login.html", context, status=401)

            messages.add_message(
                request,
                messages.ERROR,
                "Nome de usuário ou senha incorreta, por favor tente novamente",
            )
            return render(request, "login/login.html", context, status=401)

        messages.add_message(
            request,
            messages.ERROR,
            "Por favor, preencha todos os campos!",
        )
        return render(request, "login/login.html", context, status=400)


class Logout(View):
    def post(self, request):
        logout(request)
        return redirect("login")