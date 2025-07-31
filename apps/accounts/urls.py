from django.urls import include, path

from .views import *

urlpatterns = [
    path("accounts/", include("django.contrib.auth.urls")),
    path("", Login.as_view(), name="login"),
    path("logout/", Logout.as_view(), name="logout"),
]
