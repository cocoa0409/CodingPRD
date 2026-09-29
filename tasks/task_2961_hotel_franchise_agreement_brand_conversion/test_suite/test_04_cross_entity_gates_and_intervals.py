"""Gates whose answer lives on another entity, and the two interval rules."""

from test_helpers import (
    BSD_HEADERS,
    FDM_DECIDER_HEADERS,
    FDM_HEADERS,
    QA_HEADERS,
    QA_SECOND_HEADERS,
    ApiErrorId,
    assert_instant,
    assert_integer,
    assert_money,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated_list,
)

ON_RING_UNIT = {
    "unit_name": "Solaris Ridgeview",
    "market_code": "SEADT",
    "x_miles": 3.00,
    "y_miles": 4.00,
    "room_count": 150,
    "adr_amount": 240.00,
    "occupancy_pct": 68.00,
    "territory_start_date": "2018-04-01",
    "territory_end_date": "2026-09-30",
}
NEARBY_UNIT = {
    "unit_name": "Solaris Lakeside",
    "market_code": "SEADT",
    "x_miles": 1.20,
    "y_miles": 1.60,
    "room_count": 100,
    "adr_amount": 310.00,
    "occupancy_pct": 72.00,
    "territory_start_date": "2016-06-01",
    "territory_end_date": "2026-09-30",
}


# ─── An open claim on another entity blocks the approval (PRD §3.5) ────

def _open_claim_world(api):
    """A CLEAR application with one FILED encroachment claim standing against
    it, brought to the approval gate."""
    world = fixtures.setup_reviewable_application(
        api,
        existing_units=[ON_RING_UNIT],
        application_overrides={
            "property_name": "Origin Point Hotel",
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 16,
        },
    )
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_financial_review(api, world["application_id"], "PORTFOLIO_ADJUSTED")
    fixtures.run_impact_analysis(api, world["application_id"])
    fixtures.set_clock(api, "2026-08-10T00:00:00Z")
    world["claim"] = fixtures.file_claim(
        api,
        world["application_id"],
        world["units"][0]["id"],
        narrative="Ridgeview projects a shift of transient demand to the converted property.",
    )
    world["claim_id"] = world["claim"]["id"]
    fixtures.finalize_impact(api, world["application_id"])
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    return world


def test_approval_is_refused_while_a_claim_the_application_does_not_own_is_filed(api):
    """PRD §3.5: the approval gate refuses while any encroachment claim on the
    application is still FILED, a condition that lives entirely on the claim
    row.  The refusal leaves the application UNDER_REVIEW with no decision
    recorded.

    Design: Difficulty/cross_entity_state_dependency/approval_gated_by_encroachment_claim_status_until_overruled
    """
    world = _open_claim_world(api)
    response = api.decide_application(
        world["application_id"],
        factories.build_decision_payload("APPROVE", decision_notes="First attempt, claim still open."),
        FDM_DECIDER_HEADERS,
    )
    validate_error(response, ApiErrorId.OPEN_ENCROACHMENT_CLAIMS)
    assert response.status_code == 409, (
        f"an open claim is a 409 at the gate, got {response.status_code}"
    )

    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert application["status"] == "UNDER_REVIEW"
    assert application["decision_outcome"] is None
    assert application["decided_at"] is None


def test_overruling_the_claim_admits_the_identical_approval_without_touching_the_study(api):
    """PRD §3.4 and §3.5: an OVERRULE closes the claim with no penalty points
    and no recomputation, so the study stays FINAL, the verdict stays CLEAR and
    the sustained-claim counter stays at zero - yet the identical approval that
    was just refused now succeeds and releases the brand's open-application
    counter.

    Design: Difficulty/cross_entity_state_dependency/approval_gated_by_encroachment_claim_status_until_overruled
    """
    world = _open_claim_world(api)
    api.decide_application(
        world["application_id"], factories.build_decision_payload("APPROVE"), FDM_DECIDER_HEADERS
    )
    claim = fixtures.resolve_claim(
        api,
        world["claim_id"],
        "OVERRULE",
        resolution_notes="Ridgeview's demand overlap is inside tolerance; claim overruled.",
    )
    assert claim["status"] == "OVERRULED"
    assert_money(claim["penalty_points_applied"], 0.00, "penalty_points_applied")

    application = fixtures.decide_application(
        api, world["application_id"], "APPROVE",
        decision_notes="Second attempt, claim overruled.",
    )
    assert application["status"] == "APPROVED"
    assert application["decision_outcome"] == "APPROVE"
    assert_instant(application["decided_at"], "2026-09-01T00:00:00.000Z", "decided_at")
    assert_integer(application["sustained_claim_count"], 0, "sustained_claim_count")
    assert application["impact_study_status"] == "FINAL"
    assert_money(application["final_impact_score"], 0.00, "final_impact_score")
    assert application["encroachment_verdict"] == "CLEAR"

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 0, "open_application_count")


# ─── A suspended claimant may not file (PRD §3.4) ────────────────────

def _suspended_claimant_world(api):
    """A nearby incumbent scored into the preliminary study, then suspended for
    a renovation before it tries to file its protest."""
    world = fixtures.setup_reviewable_application(api, existing_units=[NEARBY_UNIT])
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    world["application"] = fixtures.run_impact_analysis(api, world["application_id"])
    fixtures.set_clock(api, "2026-08-06T00:00:00Z")
    fixtures.change_unit_status(
        api, world["units"][0]["id"], "SUSPENDED", "Guestroom tower renovation."
    )
    return world


def test_claim_filing_is_refused_while_the_complaining_hotel_is_suspended(api):
    """PRD §3.4: the unit named in the body must be OPERATING to file, so a
    hotel suspended for renovation is refused with 422 even though it was
    inside the preliminary input set and scored 32.73 before the suspension -
    the two gates read the unit's status at different instants and are
    independent.

    Design: Difficulty/cross_entity_state_dependency/encroachment_claim_filing_gated_by_existing_unit_operating_status
    """
    world = _suspended_claimant_world(api)
    response = api.file_encroachment_claim(
        world["application_id"],
        factories.build_encroachment_claim_payload(
            world["units"][0]["id"],
            claimed_revenue_loss_pct=11.25,
            narrative="Filed while the complaining hotel is suspended.",
        ),
        BSD_HEADERS,
    )
    validate_error(response, ApiErrorId.UNIT_NOT_OPERATING)
    assert response.status_code == 422, (
        f"a non-operating claimant is a 422, got {response.status_code}"
    )

    application = world["application"]
    assert application["impact_study_status"] == "PRELIMINARY"
    assert_money(application["preliminary_impact_score"], 32.73, "preliminary_impact_score")
    assert_integer(
        application["impact_unit_count_preliminary"], 1, "impact_unit_count_preliminary"
    )


def test_restoring_the_hotel_to_operating_admits_the_refiled_claim_only_once(api):
    """PRD §3.1 and §3.4: returning the unit to OPERATING restores it as an
    eligible claimant, so the identical filing succeeds; the refused attempt
    left no row behind, so exactly one claim exists, FILED, with no penalty
    points yet and the application's own state unchanged.

    Design: Difficulty/cross_entity_state_dependency/encroachment_claim_filing_gated_by_existing_unit_operating_status
    """
    world = _suspended_claimant_world(api)
    unit_id = world["units"][0]["id"]
    api.file_encroachment_claim(
        world["application_id"],
        factories.build_encroachment_claim_payload(unit_id, claimed_revenue_loss_pct=11.25),
        BSD_HEADERS,
    )
    unit = fixtures.change_unit_status(
        api, unit_id, "OPERATING", "Renovation complete, hotel reopened."
    )
    assert unit["status"] == "OPERATING"

    claim = fixtures.file_claim(
        api, world["application_id"], unit_id,
        claimed_revenue_loss_pct=11.25,
        narrative="Refiled after the hotel reopened.",
    )
    assert claim["status"] == "FILED"
    assert claim["existing_unit_id"] == unit_id
    assert_money(claim["penalty_points_applied"], 0.00, "penalty_points_applied")

    rows, meta = validate_paginated_list(
        api.list_encroachment_claims(BSD_HEADERS, {"application_id": world["application_id"]})
    )
    assert_integer(meta["total_count"], 1, "total_count")
    assert len(rows) == 1, f"the refused filing must create no row, got {len(rows)}"

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["operating_unit_count"], 1, "operating_unit_count")
    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert application["status"] == "UNDER_REVIEW"
    assert_integer(application["sustained_claim_count"], 0, "sustained_claim_count")


# ─── Closed territory intervals conflict on one touching day (PRD §3.5) ─

_TOUCHING_UNIT = dict(ON_RING_UNIT, territory_end_date="2026-10-01")
_CLEAR_UNIT = {
    "unit_name": "Polaris Northgate",
    "market_code": "SEANE",
    "x_miles": 0.00,
    "y_miles": 5.00,
    "room_count": 150,
    "adr_amount": 190.00,
    "occupancy_pct": 70.00,
    "territory_start_date": "2018-04-01",
    "territory_end_date": "2026-09-30",
}


def _territory_arm(api, brand_overrides, unit, property_name, market_code):
    """One brand, one incumbent and one fully reviewed CLEAR application ready
    for the approval gate."""
    world = fixtures.setup_reviewable_application(
        api,
        brand_overrides=brand_overrides,
        existing_units=[unit],
        application_overrides={
            "property_name": property_name,
            "market_code": market_code,
            "current_affiliation": "INDEPENDENT",
            "building_age_years": 16,
        },
    )
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    fixtures.run_financial_review(api, world["application_id"], "PORTFOLIO_ADJUSTED")
    fixtures.run_impact_analysis(api, world["application_id"])
    world["application"] = fixtures.finalize_impact(api, world["application_id"])
    return world


def test_incumbent_territory_ending_on_the_conversion_date_blocks_the_approval(api):
    """PRD §3.1 and §3.5: both the incumbent's area-of-protection term and the
    requested license term are closed intervals, so an incumbent inside the
    protected radius whose territory ends on exactly the requested conversion
    date shares one calendar day with the request and conflicts.  The refusal
    is temporal, not score-driven: the study is CLEAR at 0.00.

    Design: Difficulty/resource_temporal_overlap/territory_term_closed_interval_conflicts_on_a_single_touching_day
    """
    world = _territory_arm(
        api,
        {"code": "SOLARIS", "name": "Solaris Collection"},
        _TOUCHING_UNIT,
        "Touching Term Hotel",
        "SEADT",
    )
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    response = api.decide_application(
        world["application_id"],
        factories.build_decision_payload(
            "APPROVE", decision_notes="Incumbent territory ends on the conversion date itself."
        ),
        FDM_DECIDER_HEADERS,
    )
    validate_error(response, ApiErrorId.TERRITORY_TERM_CONFLICT)
    assert response.status_code == 409, (
        f"a territory conflict is a 409, got {response.status_code}"
    )

    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))
    assert application["status"] == "UNDER_REVIEW"
    assert application["decision_outcome"] is None
    assert application["decided_at"] is None
    assert_money(application["final_impact_score"], 0.00, "final_impact_score")
    assert application["encroachment_verdict"] == "CLEAR"

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 1, "open_application_count")


def test_incumbent_territory_ending_the_day_before_admits_the_approval(api):
    """PRD §3.5: one day earlier the two closed intervals share nothing, so the
    same request against the same geometry is approved - the incumbent is still
    counted in the study, which still scores 0.00, and the brand's
    open-application counter is released.

    Design: Difficulty/resource_temporal_overlap/territory_term_closed_interval_conflicts_on_a_single_touching_day
    """
    world = _territory_arm(
        api,
        {"code": "POLARIS", "name": "Polaris Select", "tier": "MIDSCALE"},
        _CLEAR_UNIT,
        "Clear Term Hotel",
        "SEANE",
    )
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    application = fixtures.decide_application(
        api, world["application_id"], "APPROVE",
        decision_notes="Incumbent territory expired the day before.",
    )

    assert application["status"] == "APPROVED"
    assert application["decision_outcome"] == "APPROVE"
    assert_integer(application["impact_unit_count_final"], 1, "impact_unit_count_final")
    assert_money(application["final_impact_score"], 0.00, "final_impact_score")

    brand = get_success_data(api.get_brand(world["brand_id"], BSD_HEADERS))
    assert_integer(brand["open_application_count"], 0, "open_application_count")


# ─── The inspection cadence window is half-open (PRD §3.8) ────────────

_SECOND_SCORES = {
    "cleanliness_score": 88,
    "condition_score": 72,
    "brand_standard_score": 90,
    "guest_experience_score": 80,
    "critical_defect_count": 2,
    "life_safety_defect": False,
}


def _first_inspection_world(api):
    """An OPEN hotel with one PASS inspection recorded on 2027-02-01."""
    world = fixtures.setup_open_agreement(api)
    fixtures.set_clock(api, "2027-02-01T00:00:00Z")
    world["first_inspection"] = fixtures.score_inspection(
        api, world["agreement_id"], QA_HEADERS,
        cleanliness_score=85, condition_score=85,
        brand_standard_score=85, guest_experience_score=85,
    )
    return world


def test_inspection_one_millisecond_before_the_ninety_day_mark_is_refused(api):
    """PRD §3.8: the cadence window opens 90 days after last_inspection_at and
    the instant before it is refused, so 2027-05-01T23:59:59.999Z is a 409.
    The first inspection stands closed at exactly 85.00 PASS with no cure
    deadline, which is what stamped the cadence in the first place.

    Design: Difficulty/resource_temporal_overlap/qa_inspection_minimum_gap_window_is_half_open
    """
    world = _first_inspection_world(api)
    first = world["first_inspection"]
    assert_money(first["total_score"], 85.00, "total_score")
    assert first["grade"] == "PASS"
    assert first["status"] == "CLOSED"
    assert first["cure_deadline"] is None

    fixtures.set_clock(api, "2027-05-01T23:59:59.999Z")
    response = api.create_qa_inspection(
        world["agreement_id"],
        factories.build_qa_inspection_payload(**_SECOND_SCORES),
        QA_SECOND_HEADERS,
    )
    validate_error(response, ApiErrorId.INSPECTION_TOO_SOON)
    assert response.status_code == 409, (
        f"a premature inspection is a 409, got {response.status_code}"
    )

    _, meta = validate_paginated_list(
        api.list_agreement_qa_inspections(world["agreement_id"], QA_HEADERS)
    )
    assert_integer(meta["total_count"], 1, "total_count")


def test_inspection_exactly_ninety_days_later_is_admitted_and_scored(api):
    """PRD §3.8: the boundary instant itself is permitted, so the same
    inspection succeeds at 2027-05-02T00:00:00Z.  The weighted sections give
    83.40, two critical defects deduct ten points for 73.40, which grades
    CONDITIONAL with a sixty-day cure deadline and moves the compliance axis to
    CURE_PERIOD - while the refused attempt left no row behind.

    Design: Difficulty/resource_temporal_overlap/qa_inspection_minimum_gap_window_is_half_open
    """
    world = _first_inspection_world(api)
    fixtures.set_clock(api, "2027-05-01T23:59:59.999Z")
    api.create_qa_inspection(
        world["agreement_id"],
        factories.build_qa_inspection_payload(**_SECOND_SCORES),
        QA_SECOND_HEADERS,
    )
    fixtures.set_clock(api, "2027-05-02T00:00:00Z")
    response = api.create_qa_inspection(
        world["agreement_id"],
        factories.build_qa_inspection_payload(**_SECOND_SCORES),
        QA_SECOND_HEADERS,
    )
    inspection = get_success_data(response, 201)

    assert_money(inspection["weighted_score"], 83.40, "weighted_score")
    assert_money(inspection["total_score"], 73.40, "total_score")
    assert inspection["grade"] == "CONDITIONAL"
    assert_instant(inspection["inspection_at"], "2027-05-02T00:00:00.000Z", "inspection_at")
    assert_instant(inspection["cure_deadline"], "2027-07-01T00:00:00.000Z", "cure_deadline")

    agreement = get_success_data(api.get_agreement(world["agreement_id"], FDM_HEADERS))
    assert_instant(
        agreement["last_inspection_at"], "2027-05-02T00:00:00.000Z", "last_inspection_at"
    )
    assert agreement["compliance_status"] == "CURE_PERIOD"
    assert_integer(
        agreement["consecutive_qa_failure_count"], 0, "consecutive_qa_failure_count"
    )

    _, meta = validate_paginated_list(
        api.list_agreement_qa_inspections(world["agreement_id"], QA_HEADERS)
    )
    assert_integer(meta["total_count"], 2, "total_count")
