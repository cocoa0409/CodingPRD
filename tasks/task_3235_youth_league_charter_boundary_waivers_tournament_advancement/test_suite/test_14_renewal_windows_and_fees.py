"""Renewal window classification edges and the approval gates: insurance
containment and the late fee."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    get_success_data, ApiErrorId,
    set_clock, create_league_raw, add_insurance, submit_renewal,
    approve_renewal, get_league,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]


def test_window_classification_at_edges_and_outside(api):
    """PRD §3.2: "The submission is classified `ON_TIME` when D falls anywhere
    from October 1 of year S−1 through December 31 of year S−1, inclusive on
    both ends. It is classified `LATE` when D falls anywhere from January 1 of
    year S through March 31 of year S, inclusive on both ends. Any other
    submission date is rejected outright with `ERR_RENEWAL_WINDOW_CLOSED`
    (HTTP 422)."

    Design: Corner/calculations/renewal_window_classification_on_time_late_outside
    """
    set_clock("2026-10-01T00:00:00Z")
    lg1, _ = create_league_raw(league_name="Early Bird LL")
    lg2, _ = create_league_raw(league_name="Late Bird LL")
    lg3, _ = create_league_raw(league_name="Too Late LL")

    # First instant of the ON_TIME window for season 2027.
    r1 = get_success_data(api.create_charter_renewal(
        lg1["id"], {"season_year": 2027}, LA))
    assert r1["window_classification"] == "ON_TIME"

    # Last instant of the LATE window for season 2027.
    set_clock("2027-03-31T00:00:00Z")
    r2 = get_success_data(api.create_charter_renewal(
        lg2["id"], {"season_year": 2027}, LA))
    assert r2["window_classification"] == "LATE"

    # One day past the LATE window close: rejected outright.
    set_clock("2027-04-01T00:00:00Z")
    err = validate_error(api.create_charter_renewal(
        lg3["id"], {"season_year": 2027}, LA),
        ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)
    assert err["error_id"] == "ERR_RENEWAL_WINDOW_CLOSED"


def test_approval_requires_insurance_containing_the_season_window(api):
    """PRD §3.2: "First, insurance containment: the league must hold an `ACTIVE`
    insurance certificate whose coverage window fully contains the season
    window — that is, coverage from March 1 of the season year through
    October 31 of the season year, inclusive — and without one the decision is
    rejected with `ERR_INSURANCE_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/calculations/renewal_approve_requires_insurance_containment
    """
    set_clock("2026-10-15T00:00:00Z")
    league, _ = create_league_raw(league_name="Coverage LL")
    # Misses the season start (2027-03-01).
    add_insurance(league["id"], coverage_start="2027-06-01",
                  coverage_end="2027-12-31")
    renewal = submit_renewal(league["id"])

    err = validate_error(api.decide_charter_renewal(
        league["id"], renewal["id"],
        {"action": "APPROVE", "late_fee_paid": False}, DA),
        ApiErrorId.ERR_INSURANCE_NOT_ACTIVE)
    assert err["error_id"] == "ERR_INSURANCE_NOT_ACTIVE"

    # Adding a containing certificate unblocks the approval.
    add_insurance(league["id"], coverage_start="2027-01-01",
                  coverage_end="2027-12-31")
    decided = validate_success(api.decide_charter_renewal(
        league["id"], renewal["id"],
        {"action": "APPROVE", "late_fee_paid": False}, DA), 200)
    assert decided["status"] == "APPROVED"
    assert get_league(league["id"])["charter_status"] == "CHARTERED"


def test_late_renewal_requires_late_fee_paid(api):
    """PRD §3.2: "Second, the late fee: when the renewal's
    `window_classification` is `LATE`, the decision payload's `late_fee_paid`
    must be true, or the approval is rejected with `ERR_LATE_FEE_UNPAID`
    (HTTP 402). The `late_fee_paid` flag is recorded onto the renewal from the
    decide payload at approval; for `ON_TIME` approvals it is recorded as
    false."

    Design: Corner/calculations/late_fee_gate_on_late_renewal
    """
    set_clock("2026-10-15T00:00:00Z")
    league, _ = create_league_raw(league_name="Late Payer LL")
    add_insurance(league["id"])
    set_clock("2027-02-01T00:00:00Z")
    renewal = submit_renewal(league["id"])
    assert renewal["window_classification"] == "LATE"

    err = validate_error(api.decide_charter_renewal(
        league["id"], renewal["id"],
        {"action": "APPROVE", "late_fee_paid": False}, DA),
        ApiErrorId.ERR_LATE_FEE_UNPAID)
    assert err["error_id"] == "ERR_LATE_FEE_UNPAID"

    decided = validate_success(api.decide_charter_renewal(
        league["id"], renewal["id"],
        {"action": "APPROVE", "late_fee_paid": True}, DA), 200)
    assert decided["status"] == "APPROVED"
    assert decided["late_fee_paid"] is True
    # All team counts 0: base line 50000 * 1.175 = 58750.
    assert decided["final_fee_cents"] == 58750
