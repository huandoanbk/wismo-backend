"""URL routes for account foundation endpoints."""

from django.urls import path

from accounts.views import (
    AccountMeView,
    AddPasswordView,
    ChangePasswordView,
    ContactFormView,
    DeleteAllChatView,
    GoogleLoginView,
    GuestInitView,
    LoginView,
    LogoutView,
    RegisterView,
    ResendOtpView,
    SessionStatusView,
    VerifyEmailView,
)

urlpatterns = [
    path("guest/init/", GuestInitView.as_view(), name="guest-init"),
    path("session/", SessionStatusView.as_view(), name="session-status"),
    path("register/", RegisterView.as_view(), name="register"),
    path("verify-email/", VerifyEmailView.as_view(), name="verify-email"),
    path("resend-otp/", ResendOtpView.as_view(), name="resend-otp"),
    path("login/", LoginView.as_view(), name="login"),
    path("google/login/", GoogleLoginView.as_view(), name="google-login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", AccountMeView.as_view(), name="account-me"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("add-password/", AddPasswordView.as_view(), name="add-password"),
    path("delete-all-chat/", DeleteAllChatView.as_view(), name="delete-all-chat"),
    path("contact/", ContactFormView.as_view(), name="contact-form"),
]
