"""Temporal window overlap: match campaigns use half-open arithmetic while
equity funds use closed-interval arithmetic, so adjacency is allowed for one
and conflicts for the other."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers import factories as f


# ── Match campaigns: half-open [starts_at, ends_at) ────────────────────────


def test_campaign_adjacent_window_allowed_straddling_window_rejected(api):
    """Touching at an endpoint is not an overlap under half-open arithmetic;
    straddling the boundary is.

    PRD: "Its window must not overlap any `ACTIVE` campaign sharing the same `sponsor_name`, `target_type`, and `target_value`, judged with half-open arithmetic — the existing campaign's `starts_at` strictly before the new campaign's `ends_at`, and the new campaign's `starts_at` strictly before the existing campaign's `ends_at`; two windows that merely touch at an endpoint are allowed. An overlap fails with `ERR_CAMPAIGN_WINDOW_OVERLAP`."
    Design: Difficulty/resource_temporal_overlap/match_campaign_adjacent_half_open_windows
    """
    fixtures.set_clock(api)
    c1 = fixtures.create_match_campaign(
        api, ends_at="2026-10-01T00:00:00Z"
    )  # Acme / STATE / TX [2026-09-01, 2026-10-01)

    # Adjacent: starts exactly at the existing window's end -> allowed.
    c2 = fixtures.create_match_campaign(
        api, match_ratio=0.5, budget_cents=50000,
        starts_at="2026-10-01T00:00:00Z", ends_at="2026-11-01T00:00:00Z",
    )
    assert c2["status"] == "ACTIVE"

    # Straddling: overlaps the interior of c1's window -> rejected.
    res = api.create_match_campaign(
        f.match_campaign_payload(
            match_ratio=2.0, budget_cents=50000,
            starts_at="2026-09-15T00:00:00Z", ends_at="2026-10-15T00:00:00Z",
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_WINDOW_OVERLAP, 409)

    assert fixtures.read_match_campaign(api, c1["id"])["status"] == "ACTIVE"
    assert fixtures.read_match_campaign(api, c2["id"])["status"] == "ACTIVE"


def test_campaign_overlap_only_counts_within_the_same_target_key(api):
    """The conflict key is sponsor + target type + target value: a different
    target over the same dates is a different key and never conflicts.

    PRD: "Its window must not overlap any `ACTIVE` campaign sharing the same `sponsor_name`, `target_type`, and `target_value`"
    Design: Difficulty/resource_temporal_overlap/match_campaign_adjacent_half_open_windows
    """
    fixtures.set_clock(api)
    fixtures.create_match_campaign(api, ends_at="2026-10-01T00:00:00Z")  # Acme STATE TX

    # Same sponsor, same dates, different target type -> allowed.
    other_type = fixtures.create_match_campaign(
        api, budget_cents=50000, target_type="SUBJECT", target_value="MATH",
        starts_at="2026-09-15T00:00:00Z", ends_at="2026-10-15T00:00:00Z",
    )
    assert other_type["status"] == "ACTIVE"

    # Same sponsor, same type, different target value -> allowed.
    other_value = fixtures.create_match_campaign(
        api, budget_cents=60000, target_type="STATE", target_value="NM",
        starts_at="2026-09-15T00:00:00Z", ends_at="2026-10-15T00:00:00Z",
    )
    assert other_value["status"] == "ACTIVE"


# ── Equity funds: closed [window_start, window_end] ────────────────────────


def test_equity_fund_touching_windows_conflict(api):
    """A new fund starting on the day the sibling fund ends shares that day
    with it, and closed intervals count a shared day as a conflict.

    PRD: "The overlap rule is stricter than the campaign rule: a new fund's window must not overlap *or touch* any `ACTIVE` fund with the same `state_code` — closed-interval arithmetic, meaning the existing fund's `window_start` is at or before the new fund's `window_end` and the new fund's `window_start` is at or before the existing fund's `window_end` — so an adjacent window sharing a boundary day already conflicts, and fails with `ERR_EQUITY_WINDOW_OVERLAP`."
    Design: Difficulty/resource_temporal_overlap/equity_fund_touching_closed_windows_conflict
    """
    fixtures.set_clock(api)
    fund = fixtures.create_equity_fund(
        api, name="TX September Fund", window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
    )

    touching = api.create_equity_fund(
        f.equity_fund_payload(
            name="TX Follow-on Fund", min_poverty_pct=60.0, budget_cents=80000,
            window_start="2026-09-30T00:00:00Z", window_end="2026-10-30T00:00:00Z",
        ),
        fixtures.ADMIN_HEADERS,
    )
    validate_error(touching, ApiErrorId.ERR_EQUITY_WINDOW_OVERLAP, 409)

    assert fixtures.read_equity_fund(api, fund["id"])["status"] == "ACTIVE"


def test_equity_fund_starting_after_the_boundary_day_is_allowed(api):
    """Starting the day after the existing window's end leaves no shared day.

    PRD: "The overlap rule is stricter than the campaign rule: a new fund's window must not overlap *or touch* any `ACTIVE` fund with the same `state_code`"
    Design: Difficulty/resource_temporal_overlap/equity_fund_touching_closed_windows_conflict
    """
    fixtures.set_clock(api)
    fund = fixtures.create_equity_fund(
        api, name="TX September Fund", window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-30T00:00:00Z",
    )

    # 2026-10-01 is past the shared boundary day: no conflict.
    follow = fixtures.create_equity_fund(
        api, name="TX October Fund", min_poverty_pct=60.0, budget_cents=80000,
        window_start="2026-10-01T00:00:00Z", window_end="2026-10-31T00:00:00Z",
    )
    assert follow["status"] == "ACTIVE"

    # A touching window in a different state_code is also a different key.
    other_state = fixtures.create_equity_fund(
        api, name="NV September Twin", state_code="NV", min_poverty_pct=60.0,
        budget_cents=80000, window_start="2026-09-15T00:00:00Z",
        window_end="2026-10-15T00:00:00Z",
    )
    assert other_state["status"] == "ACTIVE"

    assert fixtures.read_equity_fund(api, fund["id"])["status"] == "ACTIVE"
