"""Retail agreement signing gates: window elapsed, half-open exclusivity
overlap, and the litigation gate's priority over the temporal gate
(PRD §2.10, §3.6, §3.9).
"""
import pytest

from test_helpers import (
    RETAIL,
    ApiErrorId,
    api_client,
    create_retail_agreement,
    file_case,
    get_retail_agreement,
    get_season,
    record_judgment,
    run_review,
    set_clock,
    setup_season_with_category,
    setup_signed_agreement,
    sign_agreement,
    validate_error,
    validate_ok,
)


def test_sign_elapsed_window_rejected(api):
    """PRD §3.6: "Finally the window must still be live: a `window_end` at or
    before the current logical clock is rejected with `ERR_WINDOW_ELAPSED`."

    Design: Corner/validations/sign_elapsed_window_rejected
    """
    base = setup_season_with_category()
    agreement = create_retail_agreement(
        base["category"]["id"],
        exclusive=False,
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-05T00:00:00Z",
    )
    set_clock("2026-09-10T00:00:00Z")
    resp = api_client.sign_retail_agreement(agreement["id"], RETAIL)
    validate_error(resp, ApiErrorId.ERR_WINDOW_ELAPSED)
    assert get_retail_agreement(agreement["id"])["status"] == "DRAFT"


def test_agreement_expires_exactly_at_window_end(api):
    """PRD §3.9: "Step 7 expires agreements: every RetailAgreement `SIGNED` on
    a linked category whose `window_end` is at or before the current clock
    becomes `EXPIRED`."

    Design: Corner/state_machines/agreement_expires_exactly_at_window_end
    """
    base = setup_season_with_category()
    agreement = create_retail_agreement(
        base["category"]["id"],
        exclusive=False,
        window_start="2026-09-05T00:00:00Z",
        window_end="2026-11-01T00:00:00Z",
    )
    sign_agreement(agreement["id"])
    set_clock("2026-11-01T00:00:00Z")
    run_review(base["season"]["id"])
    assert get_retail_agreement(agreement["id"])["status"] == "EXPIRED"


def test_exclusive_window_strict_overlap_rejected(api):
    """PRD §3.6: "Exclusivity must not collide: no other `SIGNED` agreement
    with `exclusive` true on the same category may have a half-open window
    intersecting this one, else `ERR_EXCLUSIVE_WINDOW_CONFLICT`".

    Design: Difficulty/resource_temporal_overlap/exclusive_windows_half_open_overlap_but_adjacency_allowed
    """
    base = setup_season_with_category()
    setup_signed_agreement(
        base["category"]["id"],
        retailer_name="BigBoxCo",
        window_start="2026-10-01T00:00:00Z",
        window_end="2027-01-01T00:00:00Z",
    )
    overlapping = create_retail_agreement(
        base["category"]["id"],
        retailer_name="ClubWarehouse",
        exclusive=True,
        window_start="2026-12-01T00:00:00Z",
        window_end="2027-02-01T00:00:00Z",
        min_launch_units=200,
    )
    resp = api_client.sign_retail_agreement(overlapping["id"], RETAIL)
    validate_error(resp, ApiErrorId.ERR_EXCLUSIVE_WINDOW_CONFLICT)
    assert get_retail_agreement(overlapping["id"])["status"] == "DRAFT"


def test_exclusive_window_adjacency_is_not_intersection(api):
    """PRD §3.6: "and note that adjacency is not intersection, so one
    agreement's `window_end` landing exactly on another's `window_start` does
    not conflict."

    Design: Difficulty/resource_temporal_overlap/exclusive_windows_half_open_overlap_but_adjacency_allowed
    """
    base = setup_season_with_category()
    first = setup_signed_agreement(
        base["category"]["id"],
        retailer_name="BigBoxCo",
        window_start="2026-10-01T00:00:00Z",
        window_end="2027-01-01T00:00:00Z",
    )
    create_retail_agreement(  # overlapping but never signed: not in the conflict set
        base["category"]["id"],
        retailer_name="ClubWarehouse",
        exclusive=True,
        window_start="2026-12-01T00:00:00Z",
        window_end="2027-02-01T00:00:00Z",
        min_launch_units=200,
    )
    adjacent = create_retail_agreement(
        base["category"]["id"],
        retailer_name="SpecialtyCo",
        exclusive=True,
        window_start="2027-01-01T00:00:00Z",
        window_end="2027-04-01T00:00:00Z",
        min_launch_units=50,
    )
    data = validate_ok(api_client.sign_retail_agreement(adjacent["id"], RETAIL))
    assert data["status"] == "SIGNED"
    assert data["signed_at"] is not None
    assert get_retail_agreement(first["id"])["status"] == "SIGNED"


def test_litigation_block_beats_window_conflict_on_agreement_sign(api):
    """PRD §2.10: "When a single request violates several rules at once, the
    failure reported is the one with the lowest priority number" and "Seventh
    (priority 7), the compliance gates: ... category exposure before signing
    (`ERR_CATEGORY_LITIGATION_BLOCKED`). Eighth (priority 8), the
    temporal-window rules: exclusive-window overlap
    (`ERR_EXCLUSIVE_WINDOW_CONFLICT`) ...".

    Design: Difficulty/priority_pair_validation_conflict/litigation_block_beats_window_conflict_on_agreement_sign
    """
    base = setup_season_with_category()
    setup_signed_agreement(
        base["category"]["id"],
        retailer_name="BigBoxCo",
        window_start="2026-10-01T00:00:00Z",
        window_end="2027-01-01T00:00:00Z",
    )
    case = file_case(base["category"]["id"], "PT-3001", 2_000_000, "HIGH")
    run_review(base["season"]["id"])  # FILED -> ACTIVE
    record_judgment(case["id"], "ADVERSE", 800_000)  # exposure 6 + 9*3 = 33 SEVERE
    assert get_season(base["season"]["id"])["posture"] == "SEASON_GUARDED"
    overlapping = create_retail_agreement(
        base["category"]["id"],
        retailer_name="ClubWarehouse",
        exclusive=True,
        window_start="2026-12-01T00:00:00Z",
        window_end="2027-03-01T00:00:00Z",
        min_launch_units=200,
    )
    resp = api_client.sign_retail_agreement(overlapping["id"], RETAIL)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_LITIGATION_BLOCKED)


def test_litigation_block_fires_even_without_window_conflict(api):
    """PRD §3.6: "The category's `exposure_level` must not be `SEVERE`, else
    `ERR_CATEGORY_LITIGATION_BLOCKED`: litigation exposure blocks the retail
    signature even when the season's posture would otherwise allow it."

    Design: Difficulty/priority_pair_validation_conflict/litigation_block_beats_window_conflict_on_agreement_sign
    """
    base = setup_season_with_category()
    setup_signed_agreement(
        base["category"]["id"],
        retailer_name="BigBoxCo",
        window_start="2026-10-01T00:00:00Z",
        window_end="2027-01-01T00:00:00Z",
    )
    case = file_case(base["category"]["id"], "PT-3001", 2_000_000, "HIGH")
    run_review(base["season"]["id"])
    record_judgment(case["id"], "ADVERSE", 800_000)
    assert get_season(base["season"]["id"])["posture"] == "SEASON_GUARDED"
    clean_window = create_retail_agreement(
        base["category"]["id"],
        retailer_name="SpecialtyCo",
        exclusive=True,
        window_start="2027-02-01T00:00:00Z",
        window_end="2027-05-01T00:00:00Z",
        min_launch_units=50,
    )
    resp = api_client.sign_retail_agreement(clean_window["id"], RETAIL)
    validate_error(resp, ApiErrorId.ERR_CATEGORY_LITIGATION_BLOCKED)
    assert get_retail_agreement(clean_window["id"])["status"] == "DRAFT"
