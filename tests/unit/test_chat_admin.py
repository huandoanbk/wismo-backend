"""Admin behavior tests for chat models."""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory

from chat.models import ChatTurn

pytestmark = pytest.mark.django_db


def test_chat_turn_admin_allows_delete_for_superuser() -> None:
    """ChatTurn admin should allow deleting turns for privileged admins."""

    user_model = get_user_model()
    admin_user = user_model.objects.create_superuser(
        email="admin-chatturn@example.com",
        password="StrongPass123!",
    )
    request = APIRequestFactory().get("/admin/chat/chatturn/")
    request.user = admin_user

    model_admin = site._registry[ChatTurn]
    assert model_admin.has_delete_permission(request) is True
