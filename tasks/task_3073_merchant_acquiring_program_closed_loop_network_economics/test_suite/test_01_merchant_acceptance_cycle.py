"""Merchant acceptance cycle: listing, archiving, invalid transitions, and the
DORMANT → PROSPECT re-enrolment hop."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_industry_category,
    create_merchant,
    create_and_accept_merchant,
    create_and_activate_merchant,
    create_merchant_in_state,
    accept_merchant,
    activate_merchant,
    mark_merchant_dormant,
    archive_merchant,
    submit_declined_attempt,
    rollup_gap,
    stamp_sweep,
    get_merchant,
    list_merchants,
    set_clock,
)
from test_helpers.fixtures import ACQ, COMPLIANCE

WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-31T00:00:00Z"


# ═══ Corner: entities / merchant listing ═════════════════

def test_merchant_list_filtered_by_acceptance_status_returns_only_that_state(api):
    """PRD §2.3: "`total_count` counts the full filtered result set, not the
    page, and `has_more` is true exactly when `offset` plus the number of items
    returned is still below `total_count`."

    Design: Corner/entities/merchant_list_filter_by_acceptance_status_excludes_other_states
    """
    set_clock()
    category = create_industry_category()
    merchant_a = create_merchant(category["id"], merchant_name="List Merchant A")
    create_merchant(category["id"], merchant_name="List Merchant B")
    merchant_a = accept_merchant(merchant_a)
    assert merchant_a["acceptance_status"] == "ACCEPTED"

    res = api_client.list_merchants(ACQ, params={"acceptance_status": "PROSPECT"})
    data, meta = validate_paginated(res)
    assert len(data) == 1, f"expected only the PROSPECT outlet, got {len(data)}"
    assert data[0]["acceptance_status"] == "PROSPECT"
    assert data[0]["merchant_name"] == "List Merchant B"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_merchant_list_unfiltered_returns_every_state(api):
    """PRD §4: "| GET | `/network/merchants` | List merchants, filterable by
    acceptance status or industry | NetworkAcquirer, NetworkCompliance |"
    PRD §2.3: "Collection results are ordered by `created_at` ascending unless an
    endpoint's specification pins a different deterministic order."

    Design: Corner/entities/merchant_list_filter_by_acceptance_status_excludes_other_states
    """
    set_clock()
    category = create_industry_category()
    create_merchant(category["id"], merchant_name="List Merchant A")
    create_merchant(category["id"], merchant_name="List Merchant B")

    data, meta = validate_paginated(api_client.list_merchants(ACQ))
    names = {row["merchant_name"] for row in data}
    assert names == {"List Merchant A", "List Merchant B"}
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ═══ Corner: entities / operator archive ═════════════════

def test_merchant_archive_moves_to_terminal_suppressed_and_stays_readable(api):
    """PRD §3.2: "An operator archive is a softer route to the same terminal
    state, taking only the state precondition and imposing no risk-ceiling test,
    but it applies the same offer and settlement cascade and leaves the merchant
    row readable."

    Design: Corner/entities/merchant_delete_moves_to_terminal_suppressed_and_blocks_transitions
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"])
    assert merchant["acceptance_status"] == "PROSPECT"

    archived = validate_success(archive_merchant(merchant["id"]), 200)
    assert archived["acceptance_status"] == "SUPPRESSED"

    re_read = validate_success(
        api_client.get_merchant(merchant["id"], COMPLIANCE), 200)
    assert re_read["id"] == merchant["id"]
    assert re_read["acceptance_status"] == "SUPPRESSED"


def test_merchant_archive_blocks_subsequent_acceptance(api):
    """PRD §3.1: "Acceptance by an acquiring operator moves a `PROSPECT` outlet
    to `ACCEPTED`."
    PRD §2.10: "Eighth, a resource not in the state its transition requires
    yields `ERR_INVALID_STATE` (409)."

    Design: Corner/entities/merchant_delete_moves_to_terminal_suppressed_and_blocks_transitions
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"])
    archive_merchant(merchant["id"])

    current = get_merchant(merchant["id"], COMPLIANCE)
    res = api_client.accept_merchant(
        merchant["id"], {"expected_merchant_version": current["version"]}, ACQ)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


# ═══ Corner: state_machines / invalid transitions ════════

def test_merchant_accept_from_active_is_rejected(api):
    """PRD §3.1: "Acceptance by an acquiring operator moves a `PROSPECT` outlet
    to `ACCEPTED`."
    PRD §2.10: "Eighth, a resource not in the state its transition requires
    yields `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/merchant_accept_from_active_returns_invalid_state
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    assert merchant["acceptance_status"] == "ACTIVE"

    res = api_client.accept_merchant(
        merchant["id"], {"expected_merchant_version": merchant["version"]}, ACQ)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = get_merchant(merchant["id"])
    assert after["acceptance_status"] == "ACTIVE"


@pytest.mark.parametrize("endpoint_method", ["activate_merchant", "mark_merchant_dormant"])
def test_merchant_suppressed_state_blocks_every_acceptance_transition(api, endpoint_method):
    """PRD §3.2: "Exiting the program is the compliance officer's call, and it is
    terminal."
    PRD §2.10: "Eighth, a resource not in the state its transition requires
    yields `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/merchant_suppressed_state_blocks_every_acceptance_transition
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"])
    archive_merchant(merchant["id"])

    res = getattr(api_client, endpoint_method)(merchant["id"], ACQ)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = get_merchant(merchant["id"], COMPLIANCE)
    assert after["acceptance_status"] == "SUPPRESSED"


# ═══ Difficulty: the closed acceptance cycle ══════════════

def test_dormant_merchant_re_enters_prospect_when_decline_matches_sweep(api):
    """PRD §3.2: "When a `MERCHANT_NOT_ACCEPTED` decline is recorded against a
    merchant that is currently `DORMANT`, the outlet returns to `PROSPECT` if and
    only if three conditions hold together: an `AcceptanceGap` exists for the
    merchant's region and industry with a `qualified_status` of `PROSPECTING`;
    the latest stamped sweep generation's `sweep_index` equals the merchant's
    `status_version`; and the merchant is in `DORMANT`."

    Design: Difficulty/non_linear_state_machine/merchant_acceptance_cycle_closes_on_declined_attempt_plus_sweep
    """
    set_clock()
    from test_helpers.fixtures import setup_merchant_in_prospect_after_sweep_cycle
    _, merchant, _, stamped_index = setup_merchant_in_prospect_after_sweep_cycle()

    assert stamped_index == 2, "two activations (accept + activate) set status_version to 2"
    current = get_merchant(merchant["id"])
    assert current["acceptance_status"] == "PROSPECT", (
        f"cycle should have closed back to PROSPECT, got {current['acceptance_status']}")


def test_dormant_merchant_stays_dormant_when_sweep_index_does_not_match(api):
    """PRD §3.2: "When no stamped generation matches the merchant's
    `status_version`, the outlet stays `DORMANT` and the declined attempt only
    increments the gap counters"

    Design: Difficulty/non_linear_state_machine/merchant_acceptance_cycle_closes_on_declined_attempt_plus_sweep
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    merchant = mark_merchant_dormant(merchant)

    # No rollup is performed here.  A rollup that qualifies a gap as PROSPECTING
# re-enters the covered dormant outlets on its own (PRD §3.2 / §3.8), which
# would close the cycle before the sweep-generation guard could be exercised.
# The mismatch is therefore isolated: declines are recorded, a generation whose
# index does not equal `status_version` is stamped, and the outlet must stay put.
    for day in (10, 11, 12):
        submit_declined_attempt(
            merchant["id"], attempted_amount_cents=100000,
            decline_reason="MERCHANT_NOT_ACCEPTED",
            occurred_at=f"2026-08-{day:02d}T00:00:00Z")

    current = get_merchant(merchant["id"])
    mismatched = current["status_version"] + 7
    stamp_sweep(mismatched, rolled_at="2026-09-01T00:00:00Z")

    submit_declined_attempt(
        merchant["id"], attempted_amount_cents=250000,
        decline_reason="MERCHANT_NOT_ACCEPTED",
        occurred_at="2026-08-13T00:00:00Z")

    after = get_merchant(merchant["id"])
    assert after["acceptance_status"] == "DORMANT", (
        "a sweep generation whose index does not equal status_version must not "
        f"re-enrol the outlet, got {after['acceptance_status']}")


def test_closed_cycle_gap_counts_every_decline(api):
    """PRD §3.2: "Counting walks the declines whose reason is
    `MERCHANT_NOT_ACCEPTED` and whose originating merchant trades in the rolled-up
    region and industry and whose `occurred_at` falls inside the half-open window;
    `decline_count` is how many such attempts there were and
    `declined_volume_cents` is the sum of their `attempted_amount_cents`."

    Design: Difficulty/non_linear_state_machine/merchant_acceptance_cycle_closes_on_declined_attempt_plus_sweep
    """
    set_clock()
    from test_helpers.fixtures import setup_merchant_in_prospect_after_sweep_cycle, list_acceptance_gaps
    _, _, _, _ = setup_merchant_in_prospect_after_sweep_cycle()

    gaps = list_acceptance_gaps(params={"region_code": "US-NE"})
    assert len(gaps) == 1, f"expected one regional gap, got {len(gaps)}"
    gap = gaps[0]
    assert gap["decline_count"] == 4, (
        f"all four in-window MERCHANT_NOT_ACCEPTED declines count, got {gap['decline_count']}")
    assert gap["declined_volume_cents"] == 400000, (
        "the four 100000-cent attempts sum to 400000")
    assert gap["qualified_status"] == "PROSPECTING"


# ═══ Corner: entities / required fields ══════════════════

def test_merchant_create_missing_required_name_is_invalid_request(api):
    """PRD §2.10: "any malformed body, unknown field, missing required field, or
    enum or range violation yields `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/merchant_create_missing_required_name_returns_invalid_request
    """
    set_clock()
    category = create_industry_category()
    payload = {
        "industry_category_id": category["id"],
        "region_code": "US-NE",
        "acquisition_channel": "DIRECT",
    }
    res = api_client.create_merchant(payload, ACQ)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)

    assert list_merchants() == [], "a rejected create must not mint a merchant row"