"""Sale-window exclusivity: touching windows coexist, overlapping ones do not."""

from test_helpers import (
    PRICING_ANALYST_HEADERS,
    FILING_ACTIVE,
    FILING_FILED,
    FILING_SUSPENDED,
    ApiErrorId,
    factories as f,
    fixtures as fx,
    assert_instant_equals,
    validate_error,
    validate_success,
)

MARKET = {
    "fare_basis_code": "YMKT01",
    "origin": "FRA",
    "destination": "JFK",
    "cabin": "ECONOMY",
}

EARLY_FROM = "2026-07-01T00:00:00.000Z"
EARLY_TO = "2026-09-01T00:00:00.000Z"
LATE_FROM = "2026-09-01T00:00:00.000Z"
LATE_TO = "2026-11-01T00:00:00.000Z"
OVERLAPPING_FROM = "2026-08-15T00:00:00.000Z"
OVERLAPPING_TO = "2026-10-01T00:00:00.000Z"


def _filed(api, sale_from, sale_to, **overrides):
    return fx.create_filed_filing(
        api, sale_from=sale_from, sale_to=sale_to, **dict(MARKET, **overrides)
    )


def test_touching_sale_windows_may_both_be_active(api):
    """PRD §3.2: "Overlap is strict: two windows overlap when they share at least one
    instant of positive extent, which means windows that merely touch at their
    boundary — one filing's `sale_to` equal to another filing's `sale_from` — do
    **not** overlap and are both permitted."

    Design: Difficulty/resource_temporal_overlap/fare_sale_window_adjacency_allowed_but_strict_overlap_rejected
    """
    early = _filed(api, EARLY_FROM, EARLY_TO)
    early = fx.drive_filing(api, early["id"], FILING_ACTIVE)
    assert early["status"] == FILING_ACTIVE

    late = _filed(api, LATE_FROM, LATE_TO)
    activated = validate_success(
        api.set_fare_filing_state(
            late["id"],
            f.filing_state_payload(FILING_ACTIVE),
            headers=PRICING_ANALYST_HEADERS,
        )
    )
    assert activated["status"] == FILING_ACTIVE
    assert_instant_equals(activated["sale_from"], EARLY_TO)

    # Both remain ACTIVE on the same four-part market key.
    assert fx.read_filing(api, early["id"])["status"] == FILING_ACTIVE
    assert fx.read_filing(api, late["id"])["status"] == FILING_ACTIVE


def test_overlapping_sale_window_is_rejected_and_leaves_the_filing_filed(api):
    """PRD §3.2: "Before a filing is allowed into `ACTIVE`, the service compares its
    half-open sale window against the half-open sale window of every other filing
    already in `ACTIVE` on that same four-part market key."
    PRD §3.2: "A genuine overlap is rejected with `ERR_FARE_SALE_WINDOW_OVERLAP`, and
    the same check is applied again on the revert edge described next."

    Design: Difficulty/resource_temporal_overlap/fare_sale_window_adjacency_allowed_but_strict_overlap_rejected
    """
    early = _filed(api, EARLY_FROM, EARLY_TO)
    early = fx.drive_filing(api, early["id"], FILING_ACTIVE)
    early_version = early["version"]

    clashing = _filed(api, OVERLAPPING_FROM, OVERLAPPING_TO)
    response = api.set_fare_filing_state(
        clashing["id"],
        f.filing_state_payload(FILING_ACTIVE),
        headers=PRICING_ANALYST_HEADERS,
    )
    validate_error(response, ApiErrorId.FARE_SALE_WINDOW_OVERLAP)

    # The rejected filing is untouched and the incumbent is unaffected.
    still_filed = fx.read_filing(api, clashing["id"])
    assert still_filed["status"] == FILING_FILED
    assert still_filed["version"] == clashing["version"]
    incumbent = fx.read_filing(api, early["id"])
    assert incumbent["status"] == FILING_ACTIVE
    assert incumbent["version"] == early_version


def test_a_different_market_key_may_overlap_freely(api):
    """PRD §3.2: "Two filings that share the same `origin`, the same `destination`, the
    same `cabin` and the same `fare_basis_code` may not both be `ACTIVE` with
    overlapping sale windows."

    Design: Difficulty/resource_temporal_overlap/fare_sale_window_adjacency_allowed_but_strict_overlap_rejected
    """
    early = _filed(api, EARLY_FROM, EARLY_TO)
    fx.drive_filing(api, early["id"], FILING_ACTIVE)

    # Same fare basis, same city pair, different cabin: a different market key.
    other_cabin = _filed(api, OVERLAPPING_FROM, OVERLAPPING_TO, cabin="BUSINESS")
    activated = fx.drive_filing(api, other_cabin["id"], FILING_ACTIVE)
    assert activated["status"] == FILING_ACTIVE

    # Same cabin but a different fare basis code is likewise a different key.
    other_basis = _filed(api, OVERLAPPING_FROM, OVERLAPPING_TO, fare_basis_code="YMKT02")
    activated = fx.drive_filing(api, other_basis["id"], FILING_ACTIVE)
    assert activated["status"] == FILING_ACTIVE


def test_reactivation_reapplies_the_exclusivity_check(api):
    """PRD §3.2: "A suspended filing may return to sale, `SUSPENDED → ACTIVE`, but only
    a `PricingAnalyst` may reactivate it, the sale-window exclusivity check is
    re-applied in full, and — this is the asymmetry that matters commercially — the
    offers withdrawn during the suspension are **not** resurrected."

    Design: Difficulty/resource_temporal_overlap/fare_sale_window_adjacency_allowed_but_strict_overlap_rejected
    """
    early = _filed(api, EARLY_FROM, EARLY_TO)
    early = fx.drive_filing(api, early["id"], FILING_ACTIVE)

    # While the incumbent is suspended the overlapping window activates cleanly.
    suspended = fx.drive_filing(api, early["id"], FILING_SUSPENDED)
    assert suspended["status"] == FILING_SUSPENDED

    clashing = _filed(api, OVERLAPPING_FROM, OVERLAPPING_TO)
    clashing = fx.drive_filing(api, clashing["id"], FILING_ACTIVE)
    assert clashing["status"] == FILING_ACTIVE

    # The revert edge now runs into the very window it vacated.
    response = api.set_fare_filing_state(
        early["id"],
        f.filing_state_payload(FILING_ACTIVE),
        headers=PRICING_ANALYST_HEADERS,
    )
    validate_error(response, ApiErrorId.FARE_SALE_WINDOW_OVERLAP)
    assert fx.read_filing(api, early["id"])["status"] == FILING_SUSPENDED
