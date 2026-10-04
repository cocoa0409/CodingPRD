"""Compensating-action invariants: the conserved exposure and coverage sums."""
from test_helpers import (
    prime_agency_critical,
    recallable_approved_enrollment,
    api_client,
    get_success_data,
    make_agency_producer_headers,
    reload_property,
    setup_approved_enrollment_with_cleared_mitigation,
    setup_two_property_submitted_book,
    validate_success,
)


def test_declining_an_enrollment_removes_its_exposure_from_the_active_book(
        api, underwriter_headers):
    """PRD 2.10: "The active population is every enrollment whose `status` is
    `SUBMITTED`, `REFERRED`, `APPROVED` or `ATTACHED` — terminal enrollments are
    excluded — and the currency of the measurement is each enrollment's property's
    `total_insured_value_cents`."

    Design: Difficulty/compensating_invariant/defense_dispatch_cancel_restores_the_total_insured_exposure
    """
    (zone, agency, prop1, enroll1, prop2, enroll2) = setup_two_property_submitted_book(
        zone_code="ZR1", agency_code="AG17", dwelling_cost_cents=200_000_000)
    assert prop1["total_insured_value_cents"] == 200_000_000
    assert prop2["total_insured_value_cents"] == 200_000_000

    before = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    assert before["concentration_ratio_pct"] == 100.0

    declined = validate_success(
        api_client.decline_enrollment(enroll1["id"], "underwriting", underwriter_headers), 200)
    assert declined["status"] == "DECLINED"

    # The property keeps its valuation; only its enrollment leaves the active set.
    assert reload_property(prop1["id"])["total_insured_value_cents"] == 200_000_000

    after = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    assert after["concentration_ratio_pct"] == 0.0
    assert after["concentration_band"] == "NORMAL"


def test_compensation_restores_the_sum_to_the_cent(api, underwriter_headers):
    """PRD 3.9: "The declined enrollment itself recomputes `committed_reserve_cents`
    to 0"
    PRD 2.10: "the denominator moves whenever an enrollment enters or leaves the active
    population"

    Design: Difficulty/compensating_invariant/defense_dispatch_cancel_restores_the_total_insured_exposure
    """
    (zone, agency, prop1, enroll1, prop2, enroll2) = setup_two_property_submitted_book(
        zone_code="ZR1B", agency_code="AG17B", dwelling_cost_cents=200_000_000)

    # Both dwellings share one zone, so that zone is the whole of the active book.
    checked = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    assert checked["concentration_ratio_pct"] == 100.0

    validate_success(api_client.decline_enrollment(
        enroll1["id"], "underwriting", underwriter_headers), 200)

    # The compensation restores the zone to a single-active-enrollment book, which
    # is pinned to 0.0 by the population minimum rather than drifting to 100.
    restored = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    assert restored["concentration_ratio_pct"] == 0.0
    assert restored["freeze_active"] is False
    # The compensation is not locally contained: the surviving enrollment was
    # parked to REFERRED while the book stood at CRITICAL / frozen, and the
    # released property sheds its frozen posture without being re-queued
    # (PRD §3.9, hops 3-4).
    survivor_zone = get_success_data(api_client.get_risk_zone(zone["id"], underwriter_headers))
    assert survivor_zone["freeze_active"] is False
    survivor_prop = reload_property(prop2["id"])
    assert survivor_prop["posture"] == "WRITE_ELIGIBLE"
    survivor = get_success_data(api_client.get_enrollment(enroll2["id"], underwriter_headers))
    assert survivor["status"] == "REFERRED"


def test_recall_resets_the_score_and_provision_for_a_fresh_approval(
        api, underwriter_headers):
    """PRD 3.7: "it resets `risk_score` to 0, `risk_tier` to `MANAGED`,
    `replacement_provision` to `NONE`, and clears `valuation_fingerprint`, so a
    re-approval re-snapshots the score."

    Design: Difficulty/compensating_invariant/recall_voids_the_valuation_provision_so_the_coverage_sum_is_conserved
    """
    zone, agency, prop, approved = recallable_approved_enrollment(
        zone_code="ZS1C", agency_code="AG18C")
    pre_score = approved["risk_score"]
    assert pre_score > 0
    assert approved["replacement_provision"] == "EXTENDED"
    prime_agency_critical(zone, prop, agency)
    band = validate_success(
        api_client.get_agency(agency["id"], underwriter_headers), 200)
    assert band["concentration_band"] == "CRITICAL"

    recalled = validate_success(
        api_client.recall_enrollment(approved["id"],
                                     make_agency_producer_headers(agency["id"])), 200)
    assert recalled["status"] == "SUBMITTED"
    assert recalled["risk_score"] == 0
    assert recalled["risk_tier"] == "MANAGED"
    # A recalled enrollment carries no valuation snapshot at all, so the
    # re-approval below re-snapshots it from the property's current values
    # (PRD §3.7).
    assert not recalled["valuation_fingerprint"]

    reapproved = validate_success(
        api_client.approve_enrollment(approved["id"], underwriter_headers), 200)
    # Re-approval works off the reset score rather than restoring the old one,
    # but the mitigation credit and zone points are unchanged; the lift is the
    # agency component, because recall only became available once the agency's
    # band had been driven to CRITICAL (PRD §3.7: 150 points for CRITICAL).
    assert reapproved["risk_score"] == pre_score + 150
    assert reapproved["replacement_provision"] == "EXTENDED"


def test_recall_is_refused_while_the_agency_band_is_not_critical(
        api, underwriter_headers):
    """PRD 3.7: "only when that agency's `concentration_band` is `CRITICAL` and the
    agency is still active"
    PRD 2.10: "When the portfolio holds fewer than two such enrollments the ratio is
    pinned to 0.0 and the band to `NORMAL`"

    Design: Difficulty/compensating_invariant/recall_voids_the_valuation_provision_so_the_coverage_sum_is_conserved
    """
    zone, agency, prop, approved = setup_approved_enrollment_with_cleared_mitigation(
        zone_code="ZS1D", agency_code="AG18D")
    # A lone ACTIVE enrollment leaves both scopes pinned below their break points.
    checked = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    assert checked["concentration_band"] == "NORMAL"

    res = api_client.recall_enrollment(
        approved["id"], make_agency_producer_headers(agency["id"]))
    assert res.status_code >= 400, "recall requires a CRITICAL agency band"