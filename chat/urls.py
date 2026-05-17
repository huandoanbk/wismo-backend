"""Chat API routes for the MVP foundation."""

from django.urls import path

from chat.views import ChatBootstrapView, ChatDetailView, ChatSendView

urlpatterns = [
    path("", ChatBootstrapView.as_view(), name="chat-bootstrap"),
    path("message/", ChatSendView.as_view(), name="chat-message"),
    path("<str:chat_id>/", ChatDetailView.as_view(), name="chat-detail"),
]
