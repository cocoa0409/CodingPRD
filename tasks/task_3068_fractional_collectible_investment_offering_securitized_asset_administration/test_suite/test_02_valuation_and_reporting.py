"""Appraisal cadence, the two valuation readings, and investor reporting.

The logical clock drives every cadence comparison here, so each test moves the
clock explicitly rather than relying on wall time.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_artwork, assert_appraisal, assert_offering_report,
    TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, file_appraisal, file_verified_authentication,
    file_verified_provenance, allocate_offering, get_artwork, get_offering,
    offering_version, setup_authenticated_artwork, setup_filed_offering,
)

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _authenticated_artwork_with_offer():
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"], acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=2_000,
                               liquidity_ratio_bps=1_000, hold_period_days=182)
    return get_artwork(artwork["id"]), offering


# ── Appraisal cadence ────────────────────────────────────────────────────────

def test_a_second_appraisal_in_the_same_tick_is_refused_by_cadence(api):
    """PRD 3.2: "A new appraisal is refused with `ERR_APPRAISAL_CADENCE` when a sibling
    selected appraisal was filed within the preceding 90 days".

    Design: Corner/calculations/appraisal_immediately_after_another_is_refused_by_the_cadence_rule
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-15T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 80_000_000), 201)

    res = file_appraisal(artwork["id"], 81_000_000, appraisal_method="MARKET_INDEX")
    validate_error(res, "ERR_APPRAISAL_CADENCE", expected_status=409)

    after = get_artwork(artwork["id"])
    assert after["last_appraised_value_cents"] == 80_000_000
    assert after["last_appraisal_at"] == "2026-09-15T00:00:00Z"
    rows = get_success_data(api_client.list_appraisals(artwork["id"], ISSUER))
    assert len(rows) == 1


def test_appraisal_cadence_refuses_a_filing_at_eighty_nine_days(api):
    """PRD 3.2: "Cadence is enforced at filing time. A new appraisal is refused with
    `ERR_APPRAISAL_CADENCE` when a sibling selected appraisal was filed within the
    preceding 90 days; equivalently, a filing is admissible only when its `filed_at`
    is at least 90 days after the artwork's previous selected appraisal."

    Design: Difficulty/boundary_precision_check/appraisal_cadence_boundary_is_exclusive_at_ninety_days
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-15T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 80_000_000), 201)

    set_clock("2026-12-13T00:00:00Z")
    res = file_appraisal(artwork["id"], 85_000_000)
    validate_error(res, "ERR_APPRAISAL_CADENCE", expected_status=409)

    after = get_artwork(artwork["id"])
    assert after["last_appraised_value_cents"] == 80_000_000
    assert len(get_success_data(api_client.list_appraisals(artwork["id"], ISSUER))) == 1


def test_appraisal_cadence_admits_a_filing_at_exactly_ninety_days(api):
    """PRD 3.2: "equivalently, a filing is admissible only when its `filed_at` is at
    least 90 days after the artwork's previous selected appraisal."

    Design: Difficulty/boundary_precision_check/appraisal_cadence_boundary_is_exclusive_at_ninety_days
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-15T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 80_000_000), 201)

    set_clock("2026-12-14T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 85_000_000), 201)

    selected = get_success_data(api_client.list_appraisals(
        artwork["id"], ISSUER, params={"is_selected": "true"}))
    assert len(selected) == 1
    assert selected[0]["appraised_value_cents"] == 85_000_000
    assert selected[0]["is_selected"] is True
    assert len(get_success_data(api_client.list_appraisals(artwork["id"], ISSUER))) == 2


def test_filing_an_appraisal_advances_selection_and_the_filing_dimension(api):
    """PRD 3.2: "the new row becomes the selected appraisal — its `is_selected` set
    true — and every sibling appraisal of that artwork is recomputed to `is_selected`
    false. Exactly one appraisal per artwork is selected at any moment. The filing also
    pushes `Artwork.last_appraised_value_cents` to the new figure, sets the artwork's
    `last_appraisal_at` to the new `filed_at`, and sets `next_appraisal_due_at` to that
    instant plus 90 days."

    Design: Difficulty/non_linear_state_machine/appraisal_parallel_dimensions_selection_advances_while_filings_accumulate
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-15T00:00:00Z")
    first = validate_success(file_appraisal(artwork["id"], 80_000_000), 201)

    set_clock("2027-01-05T00:00:00Z")
    second = validate_success(file_appraisal(artwork["id"], 90_000_000), 201)

    assert second["is_selected"] is True
    first_after = validate_success(
        api_client.list_appraisals(artwork["id"], ISSUER), 200)
    by_id = {row["id"]: row for row in first_after}
    assert by_id[first["id"]]["is_selected"] is False
    assert by_id[second["id"]]["is_selected"] is True


def test_appraisal_filings_accumulate_while_exactly_one_stays_selected(api):
    """PRD 3.2: "The filing dimension and the selection dimension evolve independently
    on the same row set — the append-only `filed_at` history only ever moves forward,
    while the single-true selection flag can be moved onto a newer row at any
    admissible moment."

    Design: Difficulty/non_linear_state_machine/appraisal_parallel_dimensions_selection_advances_while_filings_accumulate
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-15T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 80_000_000), 201)

    set_clock("2027-01-05T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)

    rows = get_success_data(api_client.list_appraisals(artwork["id"], ISSUER))
    assert len(rows) == 2, "the append-only filing history keeps both rows"
    assert sum(1 for r in rows if r["is_selected"]) == 1

    after = get_artwork(artwork["id"])
    assert after["last_appraised_value_cents"] == 90_000_000
    assert after["next_appraisal_due_at"] == "2027-04-05T00:00:00Z"


# ── Valuation surface ────────────────────────────────────────────────────────

def test_valuation_reports_both_readings_and_their_difference(api):
    """PRD 3.2: "The valuation surface reports the legacy value, the restated value,
    their signed difference, and the filing instant of the basis it used." PRD 3.2:
    "In both readings the per-share value is that basis divided by the offering's
    `total_shares` with the quotient floored to whole cents; the figure is never
    rounded up."

    Design: Corner/endpoints/opportunity_valuation_returns_both_variants_side_by_side
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-15T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 80_000_000), 201)

    res = api_client.get_valuation(offering["id"], TEST_USERS["investor_headers"])
    valuation = validate_success(res, 200)

    assert valuation["legacy_value_per_share_cents"] == 80_000_000 // 40_000
    assert valuation["restated_value_per_share_cents"] == 80_000_000 // 40_000
    assert valuation["valuation_delta_cents"] == 0
    assert valuation["valuation_basis_filed_at"] == "2026-09-15T00:00:00Z"


def test_valuation_per_share_is_floored_not_rounded(api):
    """PRD 3.2: "In both readings the per-share value is that basis divided by the
    offering's `total_shares` with the quotient floored to whole cents; the figure is
    never rounded up."

    Design: Corner/endpoints/opportunity_valuation_returns_both_variants_side_by_side
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-15T00:00:00Z")
    # 80_000_001 / 40_000 == 2000.000025 -- a faithful server floors to 2000.
    validate_success(file_appraisal(artwork["id"], 80_000_001), 201)

    valuation = validate_success(api_client.get_valuation(
        offering["id"], TEST_USERS["investor_headers"]), 200)
    assert valuation["legacy_value_per_share_cents"] == 2000
    assert valuation["restated_value_per_share_cents"] == 2000


# ── Investor reporting ───────────────────────────────────────────────────────

def test_shareholder_count_ignores_waitlisted_holdings(api):
    """PRD 3.2: "the server stamps `filed_at` and computes `shareholder_count` as the
    number of distinct investors holding at least one accepted share as of
    `as_of_date`."

    Design: Corner/calculations/current_holder_count_counts_only_nonzero_accepted_holdings
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(
        start_clock="2026-09-01T00:00:00Z", total_shares=10_000,
        price_per_share_cents=2_000, registration_cap_pct=2_000,
        exemption_type="REG_A_TIER2")
    holders = [create_investor(email=f"holder{i}@x.com", legal_name=f"Holder {i}")
               for i in (1, 2)]
    for investor in holders:
        create_screened_subscription(offering["id"], investor["id"],
                                     requested_shares=2000)
    # A further subscription by an investor already at its registration cap: the
    # clamp leaves it with zero accepted shares, so it is WAITLISTED and its
    # investor is not a distinct holder.
    waiter_sub = create_screened_subscription(offering["id"], holders[0]["id"],
                                              requested_shares=4000)
    validate_success(allocate_offering(offering["id"]), 200)

    set_clock("2026-09-20T00:00:00Z")
    report = validate_success(api_client.create_offering_report(
        offering["id"],
        {"report_kind": "QUARTERLY", "as_of_date": "2026-09-20T00:00:00Z",
         "value_per_share_cents": 2200},
        ISSUER), 201)

    assert report["shareholder_count"] == 2
    assert report["value_per_share_cents"] == 2200
    assert_offering_report(report)

    waiter_after = validate_success(
        api_client.get_subscription(waiter_sub["id"], COMPLIANCE), 200)
    assert waiter_after["accepted_shares"] == 0
    assert waiter_after["status"] == "WAITLISTED"

    after = get_offering(offering["id"])
    assert after["accepted_shares"] == 4000
    assert after["reserved_shares"] == 4000


def test_offering_report_window_rejects_an_as_of_date_after_the_clock(api):
    """PRD 3.2: "Report filing is windowed in both directions: an `as_of_date` that
    precedes the offering's most recent report is refused, and so is one that
    post-dates the current clock, both with `ERR_REPORT_WINDOW_FORECLOSED`."

    Design: Corner/calculations/current_holder_count_counts_only_nonzero_accepted_holdings
    """
    artwork, offering = _authenticated_artwork_with_offer()
    set_clock("2026-09-20T00:00:00Z")
    res = api_client.create_offering_report(
        offering["id"],
        {"report_kind": "APPRAISAL", "as_of_date": "2026-10-20T00:00:00Z"},
        ISSUER)
    validate_error(res, "ERR_REPORT_WINDOW_FORECLOSED", expected_status=409)


# ── Declared numeric ranges ──────────────────────────────────────────────────

def test_offering_total_shares_outside_its_declared_range_is_refused(api):
    """PRD 3.3: "`total_shares`, into which the object is fractionalised and which must
    be at least 1". PRD 2.4: "A request whose required body field is missing, or whose
    numeric field falls outside its declared range, is refused with
    `ERR_INVALID_REQUEST` (HTTP 400) as soon as the payload is parsed."

    Design: Corner/errors/a_numeric_field_outside_its_declared_range_is_refused
    """
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist(legal_name="Ines Calderon", attribution_status="CONFIRMED",
                           nationality_country_code="ES")
    artwork = create_artwork(artist["id"], title="Cuadro Rojo", creation_year=1963,
                             acquisition_cost_cents=12_000_000,
                             reserve_price_cents=20_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])

    res = api_client.create_offering(artwork["id"], {
        "total_shares": 0, "price_per_share_cents": 1_500,
        "exemption_type": "REG_D_506C", "registration_cap_pct": 2_000,
        "liquidity_ratio_bps": 1_000, "hold_period_days": 182,
        "management_fee_bps": 150, "profit_participation_bps": 2_000,
        "cost_pass_through_bps": 10_000, "preferred_return_bps": 800,
    }, ISSUER)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
    assert get_success_data(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork["id"]})) == []