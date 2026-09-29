"""Worker classification: the declared packet against the observed audit."""

from test_helpers import (
    COMPLIANCE_AUDITOR,
    COMPLIANCE_SCREENER,
    api_client,
    factories,
    fixtures,
    validate_success,
)

NIGHT_WINDOWS = [
    ("2026-09-01", "2026-09-01T18:00:00.000Z", "2026-09-02T04:00:00.000Z"),
    ("2026-09-02", "2026-09-02T18:00:00.000Z", "2026-09-03T04:00:00.000Z"),
    ("2026-09-03", "2026-09-03T18:00:00.000Z", "2026-09-04T04:00:00.000Z"),
]


def _contractor_with_three_completed_ten_hour_routes():
    """Build the audit fixture: one community, three completed 10-hour routes.

    The declared packet is deliberately weak — the company supplies the
    equipment but the valet picks their own nights, works for others and
    committed to only 20 hours — while the route history tells a different
    story.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    prop = fixtures.create_property(name="Cedar Walk", unit_count=4)
    contract = fixtures.draft_contract(prop["id"])
    fixtures.activate_contract(contract["id"])
    contractor = fixtures.create_eligible_contractor(
        legal_name="Dana Vale",
        equipment_provided_by_company=True,
        sets_own_schedule=True,
        works_exclusively=False,
        weekly_committed_hours=20,
    )
    for service_date, window_start, window_end in NIGHT_WINDOWS:
        night = fixtures.schedule_night(
            contract["id"],
            service_date,
            service_window_start=window_start,
            service_window_end=window_end,
        )
        route = fixtures.assign_and_accept_route(
            night["id"], contractor["id"], 101, 104
        )
        fixtures.complete_route(route["id"], contractor["id"])
    fixtures.set_clock("2026-09-03T23:00:00Z")
    return {"property": prop, "contract": contract, "contractor": contractor}


def test_declared_basis_scores_the_packet_at_face_value():
    """The packet alone scores 30 points and classifies the valet as a 1099.

    PRD 3.3: "Under `DECLARED`, the packet is taken at face value. **Full-time
    hours** contributes 25 points when `weekly_committed_hours` is at least 30,
    and 0 otherwise. **Exclusivity** contributes 20 points when
    `works_exclusively` is true, and 0 otherwise."

    Design: Difficulty/dual_variant_calc/contractor_classification_declared_vs_observed_flip_worker_status
    """
    world = _contractor_with_three_completed_ten_hour_routes()

    declared = validate_success(
        api_client.run_classification(
            world["contractor"]["id"],
            factories.classification_payload("DECLARED"),
            COMPLIANCE_SCREENER,
        )
    )

    assert declared["control_score"] == 30
    assert declared["classification"] == "CONTRACTOR_1099"
    assert declared["classification_basis"] == "DECLARED"
    assert declared["onboarding_status"] == "CLEARED"


def test_observed_basis_reclassifies_the_same_packet_as_an_employee():
    """The audit adds 25 hours points and 20 exclusivity points, reaching 75.

    PRD 3.3: "**Exclusivity** contributes 20 points only when both conditions
    hold: the audited set contains at least 3 routes, and every audited route's
    night belongs to the same community."

    Design: Difficulty/dual_variant_calc/contractor_classification_declared_vs_observed_flip_worker_status
    """
    world = _contractor_with_three_completed_ten_hour_routes()
    declared = fixtures.classify_contractor(world["contractor"]["id"], "DECLARED")

    observed = validate_success(
        api_client.run_classification(
            world["contractor"]["id"],
            factories.classification_payload("OBSERVED"),
            COMPLIANCE_AUDITOR,
        )
    )

    assert observed["control_score"] == 75
    assert observed["classification"] == "EMPLOYEE_W2"
    assert observed["classification_basis"] == "OBSERVED"
    assert float(observed["observed_weekly_hours"]) == 30.0
    assert observed["control_score"] - declared["control_score"] == 45, (
        "the delta is the 25-point hours weight plus the 20-point exclusivity weight"
    )


def test_classification_never_moves_the_onboarding_dimension():
    """Re-screening is a self-loop: the contractor stays CLEARED throughout.

    PRD 3.3: "This is a self-loop: a cleared contractor stays `CLEARED` and may
    be re-screened any number of times, and the `OBSERVED` run is the periodic
    reclassification audit."

    Design: Difficulty/dual_variant_calc/contractor_classification_declared_vs_observed_flip_worker_status
    """
    world = _contractor_with_three_completed_ten_hour_routes()

    fixtures.classify_contractor(world["contractor"]["id"], "DECLARED")
    fixtures.classify_contractor(world["contractor"]["id"], "OBSERVED")

    final = fixtures.read_contractor(world["contractor"]["id"])
    assert final["onboarding_status"] == "CLEARED"
    assert final["classification"] == "EMPLOYEE_W2"
