"""Step 12 usage aggregation tests."""

from dataclasses import dataclass

from runtime.usage import aggregate_usage_events


@dataclass(frozen=True)
class Usage:
    """Small usage event fixture."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cache_write_tokens: int


def test_aggregate_usage_events_counts_all_billable_token_kinds() -> None:
    """Billable token total follows the MVP quota accounting rule."""

    totals = aggregate_usage_events(
        [
            Usage(input_tokens=10, cached_input_tokens=2, output_tokens=5, cache_write_tokens=3),
            Usage(input_tokens=1, cached_input_tokens=0, output_tokens=4, cache_write_tokens=0),
        ]
    )

    assert totals.input_tokens == 11
    assert totals.cached_input_tokens == 2
    assert totals.output_tokens == 9
    assert totals.cache_write_tokens == 3
    assert totals.total_billable_tokens == 25
    assert totals.total_observed_tokens == 25
