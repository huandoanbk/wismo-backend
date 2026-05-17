"""Seed canonical LLM gateway config for local development and tests."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from llm_ops.bootstrap import bootstrap_default_llm_gateway_config


class Command(BaseCommand):
    """Bootstrap canonical LLM gateway config."""

    help = "Seed deterministic local LLM gateway configuration."

    def handle(self, *args, **options):  # type: ignore[override]
        """Create canonical local gateway records if missing."""

        result = bootstrap_default_llm_gateway_config()
        self.stdout.write(
            self.style.SUCCESS(
                "Seeded llm_ops bootstrap: "
                f"gateways_created={result.gateways_created}, "
                f"operations_created={result.operations_created}, "
                f"operations_bound={result.operations_bound}, "
                f"operations_activated={result.operations_activated}"
            )
        )
