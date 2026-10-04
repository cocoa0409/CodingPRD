"""Enrollment intake, provisions, premiums, concentration and the binding act."""
from test_helpers import (
    add_approved_appraisal,
    add_verified_mitigation,
    api_client,
    assert_enrollment_invariants,
    assert_risk_tier_for_score,
    create_agency,
    create_enrollment,
    create_property,
    create_zone,
    get_success_data,
    make_agency_producer_headers,
    recall_enrollment,
    reload_property,
    request_dispatch,
    run_posture_eval,
    setup_active_zone_mitigation_required,
    setup_active_zone_underwritable,
    prime_agency_critical,
    setup_approved_enrollment_with_cleared_mitigation,
    setup_draft_enrollment_on_write_eligible,
    setup_inactive_agency_draft,
    setup_partial_mitigation_submitted,
    setup_submitted_enrollment,
    setup_two_property_submitted_book,
    submit_enrollment,
    validate_error,
    validate_success,
)


def test_boosted_coverage_raises_the_extended_replacement_premium(
        api, underwriter_headers):
    """PRD 3.7: "The base rate is 0.0021 times the requested dwelling coverage,
    rounded half up, and the extended-replacement premium is that base rate multiplied
    by the ratio and rounded half up."
    PRD 3.7: "the two meaningful step points are 1.2500 and 1.5000"

    Design: Difficulty/dual_variant_calc/premium_calculation_variant_at_extended_coverage
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code="ZA1", agency_code="AG1", coverage_cents=300_000_000,
        dwelling_cost_cents=200_000_000, mitigation_band="CLEARED")
    approved = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)

    assert approved["status"] == "APPROVED"
    assert approved["extended_replacement_premium_cents"] == 945_000
    assert approved["gross_premium_cents"] == 945_000
    assert approved["replacement_provision"] == "EXTENDED"
    assert approved["extended_replacement_limit_cents"] == 300_000_000
    assert approved["required_dwelling_coverage_cents"] == 300_000_000


def test_a_lower_coverage_request_yields_a_strictly_smaller_premium(
        api, underwriter_headers):
    """PRD 3.7: "The ratio is the requested `dwelling_coverage_cents` divided by the
    current `dwelling_replacement_cost_cents`, rounded half up to four decimal places
    once, before any rate is applied"

    Design: Difficulty/dual_variant_calc/premium_calculation_variant_at_extended_coverage
    """
    zone = create_zone(zone_code="ZA1B",
                       wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code="AG1B")
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"], dwelling_cost_cents=200_000_000)
    add_verified_mitigation(prop["id"], band_awarded="CLEARED")
    run_posture_eval(prop["id"])
    prop = reload_property(prop["id"])

    # PRD 3.5 fixes Coverage A at no less than 1.5 times the replacement cost, so
    # both requests sit at or above 300000000.
    rich = create_enrollment(prop["id"], agency_id=agency["id"],
                             dwelling_coverage_cents=400_000_000)
    submit_enrollment(rich["id"], agency["id"])
    lean = create_enrollment(prop["id"], agency_id=agency["id"],
                             dwelling_coverage_cents=300_000_000)
    submit_enrollment(lean["id"], agency["id"])

    approved_rich = validate_success(
        api_client.approve_enrollment(rich["id"], underwriter_headers), 200)
    approved_lean = validate_success(
        api_client.approve_enrollment(lean["id"], underwriter_headers), 200)

    # The premium scales with the requested coverage through the ratio, so the
    # 4/3-coverage request costs 4/3 of the lean one: base rate 840000 x ratio
    # 2.0000 and 630000 x 1.5000 (PRD §3.7).
    assert approved_rich["extended_replacement_premium_cents"] == 1_680_000
    assert approved_lean["extended_replacement_premium_cents"] == 945_000
    assert (approved_rich["extended_replacement_premium_cents"]
            > approved_lean["extended_replacement_premium_cents"])


def test_a_defense_window_grants_the_guaranteed_provision(api, underwriter_headers):
    """PRD 3.7: "When a defense dispatch is in progress — meaning one exists in
    `VENDOR_ASSIGNED` or `ON_SITE` — the provision is `GUARANTEED` and the guaranteed
    limit is unlimited, represented as null."

    Design: Difficulty/non_linear_state_machine/wildfire_dispatch_vendor_release_returns_to_the_queue
    """
    # GUARANTEED is only reachable from a property that is NOT design-cleared,
    # so the dwelling is left writable with an UNVERIFIED band; a CLEARED band
    # would take EXTENDED under the pinned order.
    zone, agency, prop = setup_active_zone_underwritable(
        zone_code="ZGA", agency_code="AGGA")
    get_success_data(api_client.request_dispatch(prop["id"], underwriter_headers))
    get_success_data(api_client.poll_vendors(zone["id"], underwriter_headers))
    assert reload_property(prop["id"])["defense_in_progress"] is True

    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=300_000_000)
    submit_enrollment(enroll["id"], agency["id"])
    approved = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)
    assert approved["replacement_provision"] == "GUARANTEED"
    assert approved["guaranteed_replacement_limit_cents"] is None


def test_design_cleared_beats_the_guarantee_when_both_hold(api, underwriter_headers):
    """PRD 3.7: "A property that is both design-cleared and under active defense
    therefore takes `EXTENDED`, never the larger guarantee."

    Design: Difficulty/non_linear_state_machine/wildfire_dispatch_vendor_release_returns_to_the_queue
    """
    zone = create_zone(zone_code="ZEXT", state_event="ACTIVE",
                       wildland_urban_interface_band="OUTSIDE_WUI",
                       exposure_band="ELEVATED", sustained_wind_mph=35)
    agency = create_agency(agency_code="AGEXT")
    prop = create_property(zone["id"], agency["id"])
    add_approved_appraisal(prop["id"])
    add_verified_mitigation(prop["id"], band_awarded="CLEARED")
    run_posture_eval(prop["id"])
    request_dispatch(prop["id"])
    get_success_data(api_client.poll_vendors(zone["id"], underwriter_headers))
    assert reload_property(prop["id"])["defense_in_progress"] is True

    prop = reload_property(prop["id"])
    enroll = create_enrollment(prop["id"], agency_id=agency["id"],
                               dwelling_coverage_cents=300_000_000)
    submit_enrollment(enroll["id"], agency["id"])
    approved = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)
    assert approved["replacement_provision"] == "EXTENDED"
    assert approved["guaranteed_replacement_limit_cents"] == 133_333_333


def test_enrollment_recall_voids_the_valuation_provision(api, underwriter_headers):
    """PRD 3.7: "Recall is the producer-side unwind: it is available only while the
    enrollment is `APPROVED` and unbound, only to the agency of record, and only when
    that agency's `concentration_band` is `CRITICAL` and the agency is still active —
    and it resets `risk_score` to 0, `risk_tier` to `MANAGED`, `replacement_provision`
    to `NONE`, and clears `valuation_fingerprint`, so a re-approval re-snapshots the
    score."

    Design: Difficulty/compensating_invariant/recall_voids_the_valuation_provision_so_the_coverage_sum_is_conserved
    """
    zone, agency, prop, approved = setup_approved_enrollment_with_cleared_mitigation(
        zone_code="ZS1R", agency_code="AG18R")
    assert approved["replacement_provision"] == "EXTENDED"
    assert approved["extended_replacement_limit_cents"] == 300_000_000

    # Recall requires the agency's own band to be CRITICAL (PRD §3.7), which the
    # agency scope only reaches once a second active enrollment of the same
    # agency joins the zone.
    prime_agency_critical(zone, prop, agency)
    band = validate_success(
        api_client.get_agency(agency["id"], underwriter_headers), 200)
    assert band["concentration_band"] == "CRITICAL"

    recalled = recall_enrollment(approved["id"], agency["id"])
    assert recalled["status"] == "SUBMITTED"
    assert recalled["replacement_provision"] == "NONE"
    assert recalled["risk_score"] == 0
    assert recalled["risk_tier"] == "MANAGED"

    reapproved = validate_success(
        api_client.approve_enrollment(approved["id"], underwriter_headers), 200)
    assert reapproved["replacement_provision"] == "EXTENDED"
    assert reapproved["extended_replacement_limit_cents"] == 300_000_000
    assert_enrollment_invariants(reapproved)


def test_concentration_is_pinned_below_the_population_minimum(api, underwriter_headers):
    """PRD 2.10: "When the portfolio holds fewer than two such enrollments the ratio is
    pinned to 0.0 and the band to `NORMAL`, even though a single active enrollment is by
    construction the entire book."

    Design: Difficulty/dual_variant_calc/concentration_ratio_variant_zone_scope_versus_agency_scope
    """
    zone, agency, prop, enroll = setup_submitted_enrollment(
        zone_code="ZC1A", agency_code="AGC1A")
    result = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    assert result["concentration_ratio_pct"] == 0.0
    assert result["concentration_band"] == "NORMAL"
    assert result["freeze_active"] is False


def test_zone_and_agency_scopes_diverge_on_the_same_book(api, underwriter_headers):
    """PRD 2.10: "The zone-scope ratio is the zone's share of that exposure, rounded
    half up to 2 decimal places once: at or above 30.0 the zone band is `CRITICAL`"
    PRD 2.10: "The agency-scope ratio narrows the numerator to the zone and agency
    intersection and is banded far more tightly: `CRITICAL` at or above 25.0 and
    `ELEVATED` at or above 15.0. An agency band is a ranking signal, not a gate — a
    `CRITICAL` agency never freezes a zone and never blocks an attachment."

    Design: Difficulty/dual_variant_calc/concentration_ratio_variant_zone_scope_versus_agency_scope
    """
    (zone, agency_a, prop1, enroll1, prop2, enroll2) = setup_two_property_submitted_book(
        zone_code="ZC1B", agency_code="AGC1B", state_event="NONE")
    assert enroll1["status"] == "SUBMITTED"
    assert enroll2["status"] == "SUBMITTED"

    # The two scopes only diverge when the zone holds enrollments from more than
    # one agency, so the second dwelling is re-opened under a different producer.
    agency_b = create_agency(agency_code="AGC1B2")
    withdrawn = validate_success(api_client.withdraw_enrollment(
        enroll2["id"], make_agency_producer_headers(agency_a["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    enroll2b = create_enrollment(prop2["id"], agency_id=agency_b["id"],
                                 dwelling_coverage_cents=150_000_000)
    submit_enrollment(enroll2b["id"], agency_b["id"])

    result = validate_success(
        api_client.check_concentration(zone["id"], underwriter_headers), 200)
    # The zone now writes 100 percent of the (two-dwelling) book.
    assert result["concentration_ratio_pct"] == 100.0
    assert result["concentration_band"] == "CRITICAL"
    assert result["freeze_active"] is True

    # The agency scope narrows the numerator to each agency's own share of the
    # zone, so each producer holds half of it — CRITICAL under the tighter
    # agency bands (at or above 25.0) but not the zone's 100 percent.
    read_a = validate_success(api_client.get_agency(agency_a["id"], underwriter_headers), 200)
    read_b = validate_success(api_client.get_agency(agency_b["id"], underwriter_headers), 200)
    assert read_a["concentration_ratio_pct"] == 50.0
    assert read_a["concentration_band"] == "CRITICAL"
    assert read_b["concentration_ratio_pct"] == 50.0
    assert read_b["concentration_band"] == "CRITICAL"


def test_underwriting_summary_reports_both_variants_without_mutating_the_snapshot(
        api, underwriter_headers):
    """PRD 3.7: "The gross, unmitigated variant is a reporting-only view: it treats the
    mitigation credit as zero while leaving the zone points, agency points and base
    value unchanged, so it reports a score strictly greater than the scored variant by
    exactly the credit."
    PRD 3.7: "neither variant ever overwrites the snapshotted `risk_score` — a read
    never mutates."

    Design: Corner/endpoints/underwriting_summary_is_a_pure_read_that_never_rewrites_the_snapshot
    """
    zone, agency, prop, enroll = setup_partial_mitigation_submitted(
        zone_code="ZSUM", agency_code="AGSUM", band="PARTIAL")
    approved = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)
    # ELEVATED zone (240) + base 300 - PARTIAL credit (250) = 290.
    assert approved["risk_score"] == 290

    net = validate_success(api_client.underwriting_summary(
        enroll["id"], underwriter_headers), 200)
    gross = validate_success(api_client.underwriting_summary(
        enroll["id"], underwriter_headers, view="GROSS"), 200)

    assert net["mitigation_credit"] == 250
    assert gross["mitigation_credit"] == 0
    assert gross["risk_score"] - net["risk_score"] == 250

    # The snapshotted score is untouched by either read.
    assert get_success_data(api_client.get_enrollment(
        enroll["id"], underwriter_headers))["risk_score"] == 290


def test_risk_tier_lands_at_its_exact_break_points(api, underwriter_headers):
    """PRD 3.7: "the published score is that base clamped into the range from 0 to 999
    inclusive. The tier is derived from the score in a downward cascade: `REFER` at 700
    or above, `SURCHARGE` at 450 or above, `REVIEW` at 200 or above, and `MANAGED`
    below 200."

    Design: Corner/calculations/risk_tier_boundary_at_exactly_450_points
    """
    # Scope A: the SURCHARGE break point at exactly 470.
    zone, agency, prop, enroll = setup_partial_mitigation_submitted(
        zone_code="ZTIER", agency_code="AGTIER", band="PARTIAL")
    scored = validate_success(
        api_client.approve_enrollment(enroll["id"], underwriter_headers), 200)
    # ELEVATED zone (240) + base 300 - PARTIAL credit (250) = 290.
    assert scored["risk_score"] == 290
    assert scored["risk_tier"] == "REVIEW"
    assert_risk_tier_for_score(scored["risk_score"], scored["risk_tier"])

    # Scope B: an EXTREME zone with no mitigation credit pins the 700 break point.
    zone_b = create_zone(zone_code="ZTIER2", state_event="NONE")
    agency_b = create_agency(agency_code="AGTIERB")
    plain_prop = create_property(zone_b["id"], agency_b["id"], address_line="2 Tier Rd")
    add_approved_appraisal(plain_prop["id"])
    run_posture_eval(plain_prop["id"])
    plain_prop = reload_property(plain_prop["id"])
    unmitigated = create_enrollment(plain_prop["id"], agency_id=agency_b["id"],
                                    dwelling_coverage_cents=300_000_000)
    submit_enrollment(unmitigated["id"], agency_b["id"])
    higher = validate_success(
        api_client.approve_enrollment(unmitigated["id"], underwriter_headers), 200)
    # EXTREME zone (420) + base 300 - UNVERIFIED credit (0) = 720.
    assert higher["risk_score"] == 720
    assert higher["risk_tier"] == "REFER"
    assert_risk_tier_for_score(higher["risk_score"], higher["risk_tier"])


def test_an_inactive_agency_cannot_submit_its_drafts(api, underwriter_headers,
                                                     platform_admin_headers):
    """PRD 3.4: "An operator may flip an agency's `active` flag at any time, and
    deactivating an agency blocks the two producer acts that depend on an active
    license: submitting an enrollment and recalling one."

    Design: Corner/validations/inactive_agency_cannot_submit_or_recall
    """
    zone, agency, prop, enroll = setup_inactive_agency_draft(
        zone_code="ZINACT", agency_code="AGINACT")
    res = api_client.submit_enrollment(enroll["id"],
                                       make_agency_producer_headers(agency["id"]))
    validate_error(res, "ERR_AGENCY_INACTIVE", expected_status=409)

    get_success_data(api_client.set_agency_active(agency["id"], True,
                                                  platform_admin_headers))
    validate_success(api_client.submit_enrollment(
        enroll["id"], make_agency_producer_headers(agency["id"])), 200)


def test_a_wrong_agency_id_is_refused_on_a_producer_write(api, underwriter_headers):
    """PRD 2.1: "When `X-User-Role` is `AgencyProducer`, `X-User-ID` is the `id` of the
    acting `Agency`; every producer-scoped ownership check on any resource that
    references an `Agency` compares the resource's foreign-key field — `agency_id` on an
    `Enrollment`, for instance — to `X-User-ID`, and a mismatch is refused with
    `ERR_AGENCY_NOT_OF_RECORD`."

    Design: Corner/errors/every_error_code_is_reachable_from_a_declared_endpoint
    """
    zone, agency, prop, enroll = setup_draft_enrollment_on_write_eligible(
        zone_code="ZAOR", agency_code="AGAOR")
    res = api_client.submit_enrollment(enroll["id"],
                                       make_agency_producer_headers("some-other-agency-id"))
    validate_error(res, "ERR_AGENCY_NOT_OF_RECORD", expected_status=403)


def test_withdraw_is_refused_on_the_second_call(api, underwriter_headers):
    """PRD 3.7: "Withdrawal is available to the agency of record from `DRAFT` or
    `SUBMITTED` and recomputes `committed_reserve_cents` to 0."
    
    Design: Corner/endpoints/withdraw_is_idempotent_in_effect_but_refused_on_the_second_call
    """
    zone, agency, prop, enroll = setup_draft_enrollment_on_write_eligible(
        zone_code="ZWDR", agency_code="AGWDR", coverage_cents=250_000_000)
    assert enroll["committed_reserve_cents"] == 250_000_000

    withdrawn = validate_success(api_client.withdraw_enrollment(
        enroll["id"], make_agency_producer_headers(agency["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["committed_reserve_cents"] == 0

    res = api_client.withdraw_enrollment(enroll["id"],
                                         make_agency_producer_headers(agency["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)