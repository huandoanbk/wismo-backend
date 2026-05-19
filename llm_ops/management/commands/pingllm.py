"""Probe network reachability and HTTP latency for one configured LLM gateway."""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from statistics import mean
from time import perf_counter
from urllib.parse import urlparse

import requests
from django.core.management.base import BaseCommand, CommandError

from llm_ops.models import LLMGatewayConfig
from wismo.contracts.enums import LLMGatewayIntegrationKind


@dataclass(frozen=True)
class ProbeTarget:
    """Resolved URL + host metadata for one connectivity probe run."""

    url: str
    host: str
    port: int
    scheme: str


@dataclass(frozen=True)
class ProbeResult:
    """One probe attempt timing result."""

    dns_ms: float
    tcp_ms: float
    tls_ms: float
    http_ms: float
    http_status: int
    total_ms: float


def _build_probe_target(gateway: LLMGatewayConfig, *, api_probe: bool) -> ProbeTarget:
    """Build the probe URL and socket target from gateway config."""

    endpoint = gateway.endpoint_url.strip()
    if not endpoint:
        raise CommandError("Gateway endpoint_url is empty.")

    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise CommandError(f"Unsupported endpoint scheme: {parsed.scheme or 'missing'}")
    if not parsed.hostname:
        raise CommandError("Gateway endpoint_url has no host.")

    base = endpoint.rstrip("/")
    if api_probe:
        api_suffix = _default_api_suffix(gateway.integration_kind)
        probe_url = f"{base}{api_suffix}"
    else:
        probe_url = base

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return ProbeTarget(url=probe_url, host=parsed.hostname, port=port, scheme=parsed.scheme)


def _default_api_suffix(integration_kind: str) -> str:
    """Return a canonical API path suffix for active gateway integration kinds."""

    if integration_kind in {
        LLMGatewayIntegrationKind.OPENAI_COMPATIBLE.value,
        LLMGatewayIntegrationKind.OPENAI_NATIVE.value,
        LLMGatewayIntegrationKind.AZURE_OPENAI_V1.value,
    }:
        return "/chat/completions"
    if integration_kind == LLMGatewayIntegrationKind.ANTHROPIC_NATIVE.value:
        return "/messages"
    if integration_kind == LLMGatewayIntegrationKind.OPENAI_EMBEDDINGS_V1.value:
        return "/embeddings"
    return ""


def _probe_once(*, target: ProbeTarget, timeout_seconds: float) -> ProbeResult:
    """Run one DNS/TCP/TLS/HTTP probe attempt."""

    started_total = perf_counter()
    dns_started = perf_counter()
    addr_infos = socket.getaddrinfo(target.host, target.port, type=socket.SOCK_STREAM)
    dns_ms = (perf_counter() - dns_started) * 1000
    if not addr_infos:
        raise RuntimeError("No address records returned by DNS resolver.")

    family, socktype, proto, _, sockaddr = addr_infos[0]
    tcp_started = perf_counter()
    sock = socket.socket(family, socktype, proto)
    sock.settimeout(timeout_seconds)
    try:
        sock.connect(sockaddr)
        tcp_ms = (perf_counter() - tcp_started) * 1000

        tls_ms = 0.0
        if target.scheme == "https":
            tls_started = perf_counter()
            context = ssl.create_default_context()
            tls_sock = context.wrap_socket(sock, server_hostname=target.host)
            try:
                tls_ms = (perf_counter() - tls_started) * 1000
            finally:
                tls_sock.close()
    finally:
        sock.close()

    http_started = perf_counter()
    response = requests.get(
        target.url,
        timeout=(timeout_seconds, timeout_seconds),
        allow_redirects=False,
    )
    http_ms = (perf_counter() - http_started) * 1000
    total_ms = (perf_counter() - started_total) * 1000
    return ProbeResult(
        dns_ms=dns_ms,
        tcp_ms=tcp_ms,
        tls_ms=tls_ms,
        http_ms=http_ms,
        http_status=response.status_code,
        total_ms=total_ms,
    )


def _metric_summary(values: list[float]) -> str:
    """Render min/avg/max for one timing metric list."""

    if not values:
        return "n/a"
    return f"min={min(values):.1f} avg={mean(values):.1f} max={max(values):.1f}"


class Command(BaseCommand):
    """Probe one LLM gateway endpoint from current host."""

    help = "Network + HTTP probe for one LLMGatewayConfig id."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "gateway_id",
            nargs="?",
            help="UUID of LLMGatewayConfig to probe. Optional when exactly one active gateway exists.",
        )
        parser.add_argument(
            "--gateway-id",
            dest="gateway_id_flag",
            help="Deprecated alias for positional gateway_id.",
        )
        parser.add_argument(
            "--attempts",
            type=int,
            default=5,
            help="Number of probe attempts. Default: 5",
        )
        parser.add_argument(
            "--timeout-seconds",
            type=float,
            default=10.0,
            help="Timeout for TCP/TLS/HTTP probe stages. Default: 10.0",
        )
        parser.add_argument(
            "--api-probe",
            action="store_true",
            help="Probe a canonical API path based on integration kind.",
        )

    def handle(self, *args, **options):  # type: ignore[override]
        gateway_id = str(options.get("gateway_id") or "").strip()
        gateway_id_flag = str(options.get("gateway_id_flag") or "").strip()
        attempts = int(options["attempts"])
        timeout_seconds = float(options["timeout_seconds"])
        api_probe = bool(options["api_probe"])

        if attempts <= 0:
            raise CommandError("--attempts must be > 0.")
        if timeout_seconds <= 0:
            raise CommandError("--timeout-seconds must be > 0.")

        selected_gateway_id = gateway_id or gateway_id_flag
        gateway = self._resolve_gateway(selected_gateway_id)

        target = _build_probe_target(gateway, api_probe=api_probe)
        self.stdout.write(
            f"gateway_id={gateway.id} name={gateway.display_name} kind={gateway.integration_kind} active={gateway.is_active}"
        )
        self.stdout.write(f"endpoint_url={gateway.endpoint_url}")
        self.stdout.write(
            f"probe_url={target.url} host={target.host} port={target.port} attempts={attempts} timeout={timeout_seconds}s"
        )

        successes: list[ProbeResult] = []
        failures = 0
        for index in range(1, attempts + 1):
            try:
                result = _probe_once(target=target, timeout_seconds=timeout_seconds)
            except Exception as exc:  # pragma: no cover - runtime probe safety net
                failures += 1
                self.stdout.write(self.style.ERROR(f"[{index}] FAIL error={exc.__class__.__name__}: {exc}"))
                continue
            successes.append(result)
            self.stdout.write(
                f"[{index}] OK status={result.http_status} "
                f"dns_ms={result.dns_ms:.1f} tcp_ms={result.tcp_ms:.1f} tls_ms={result.tls_ms:.1f} "
                f"http_ms={result.http_ms:.1f} total_ms={result.total_ms:.1f}"
            )

        if not successes:
            raise CommandError("All probe attempts failed.")

        self.stdout.write("summary_ms:")
        self.stdout.write(f"  dns:  {_metric_summary([item.dns_ms for item in successes])}")
        self.stdout.write(f"  tcp:  {_metric_summary([item.tcp_ms for item in successes])}")
        self.stdout.write(f"  tls:  {_metric_summary([item.tls_ms for item in successes])}")
        self.stdout.write(f"  http: {_metric_summary([item.http_ms for item in successes])}")
        self.stdout.write(f"  total:{_metric_summary([item.total_ms for item in successes])}")
        self.stdout.write(f"success={len(successes)} failure={failures}")

    @staticmethod
    def _resolve_gateway(selected_gateway_id: str) -> LLMGatewayConfig:
        """Resolve one gateway from explicit id or infer from active-gateway set."""

        if selected_gateway_id:
            gateway = LLMGatewayConfig.objects.filter(id=selected_gateway_id).first()
            if gateway is None:
                raise CommandError(f"LLMGatewayConfig not found: {selected_gateway_id}")
            return gateway

        active_gateways = list(
            LLMGatewayConfig.objects.filter(is_active=True).order_by("display_name").only("id", "display_name")
        )
        if not active_gateways:
            raise CommandError("No active LLMGatewayConfig found. Pass explicit gateway id or activate one gateway.")
        if len(active_gateways) > 1:
            choices = ", ".join(f"{gateway.id} ({gateway.display_name})" for gateway in active_gateways)
            raise CommandError(f"Multiple active gateways found. Pass gateway id. Choices: {choices}")
        return active_gateways[0]
