"""Root URL configuration for the WISMO MVP backend foundation."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/accounts/", include("accounts.urls")),
    path("api/consents/", include("consents.urls")),
    path("api/chat/", include("chat.urls")),
]
