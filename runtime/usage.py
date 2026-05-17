"""Pure usage aggregation helpers for Step 12 finalization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class UsageLike(Protocol):
    """Protocol for objects carrying provider token usage."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cache_write_tokens: int


@dataclass(frozen=True)
class UsageTotals:
    """Aggregated usage totals for one turn."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    total_billable_tokens: int
    total_observed_tokens: int


def aggregate_usage_events(events: Iterable[UsageLike]) -> UsageTotals:
    """Aggregate LLM usage events using the MVP billable token rule."""

    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    cache_write_tokens = 0

    for event in events:
        input_tokens += event.input_tokens
        cached_input_tokens += event.cached_input_tokens
        output_tokens += event.output_tokens
        cache_write_tokens += event.cache_write_tokens

    total_billable_tokens = input_tokens + cached_input_tokens + output_tokens + cache_write_tokens
    return UsageTotals(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=cache_write_tokens,
        total_billable_tokens=total_billable_tokens,
        total_observed_tokens=total_billable_tokens,
    )
