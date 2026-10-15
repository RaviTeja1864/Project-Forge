from django.urls import path

from backend.accounts import views

urlpatterns = [
    path("csrf/", views.csrf_token, name="csrf-token"),
    path("register/", views.register, name="register"),
    path("login/", views.sign_in, name="login"),
    path("logout/", views.sign_out, name="logout"),
    path("me/", views.current_user, name="current-user"),
]
