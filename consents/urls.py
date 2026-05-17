"""Consent API routes."""

from django.urls import path

from consents.views import ConsentAcceptView, ConsentStatusView, ConsentWithdrawView

urlpatterns = [
    path("accept/", ConsentAcceptView.as_view(), name="consent-accept"),
    path("withdraw/", ConsentWithdrawView.as_view(), name="consent-withdraw"),
    path("status/", ConsentStatusView.as_view(), name="consent-status"),
]
