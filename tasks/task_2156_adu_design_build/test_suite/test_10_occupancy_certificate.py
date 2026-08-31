"""Issuing the certificate of occupancy and the rental-readiness check."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_occupancy_certificate, parse_instant,
    setup_permitted_project, setup_certificate_ready_project, setup_started_phase,
    energize_utility_connection, complete_phase, read_project, move_clock,
    PLAN_CHECKER,
)


def test_certificate_is_refused_while_a_utility_is_not_energized(api):
    """PRD §3.9: "Every utility record of the project must be `ENERGIZED`, or the answer is
    `ERR_UTILITY_NOT_ENERGIZED` (HTTP 409)."
    PRD §3.9: "Issuing the certificate of occupancy is a `PlanChecker` action, and it is the
    last thing that happens to a project. It requires the project to be in
    `UNDER_CONSTRUCTION`, or the answer is `ERR_PROJECT_PHASE_INVALID`, and then four gates
    are checked in order."

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_energized_utilities
    """
    ctx = setup_certificate_ready_project(api, energize=False)
    assert ctx["utility"]["status"] == "SHARED_APPROVED"
    assert ctx["phase"]["status"] == "COMPLETE"
    assert ctx["final_appointment"]["status"] == "PASSED"

    validate_error(api.issue_occupancy_certificate(ctx["project"]["id"], PLAN_CHECKER),
                   ApiErrorId.ERR_UTILITY_NOT_ENERGIZED)


def test_refused_certificate_leaves_the_project_under_construction(api):
    """PRD §3.9: "Issuing the certificate also moves the project `UNDER_CONSTRUCTION →
    FINALED` and raises the project's `version` by 1."
    PRD §3.9: "Certificate listings for a project return an empty array before issuance and a
    single-element array afterwards."

    Design: Difficulty/cross_entity_state_dependency/certificate_requires_energized_utilities
    """
    ctx = setup_certificate_ready_project(api, energize=False)

    validate_error(api.issue_occupancy_certificate(ctx["project"]["id"], PLAN_CHECKER),
                   ApiErrorId.ERR_UTILITY_NOT_ENERGIZED)

    project = read_project(api, ctx["project"]["id"])
    assert project["status"] == "UNDER_CONSTRUCTION"

    rows, meta = validate_paginated(
        api.list_occupancy_certificates(ctx["project"]["id"], PLAN_CHECKER))
    assert meta["total_count"] == 0
    assert rows == []


def test_certificate_is_refused_while_a_phase_is_still_running(api):
    """PRD §3.9: "Every construction phase of the project must be `COMPLETE`, or the answer is
    `ERR_PHASES_INCOMPLETE` (HTTP 409)."
    PRD §3.9: "And the project must carry at least one inspection appointment whose
    `inspection_type` is `FINAL` and whose status is `PASSED`, or the answer is
    `ERR_FINAL_INSPECTION_MISSING` (HTTP 409)."

    Design: Corner/errors/certificate_with_running_phase_returns_phases_incomplete
    """
    ctx = setup_permitted_project(api)
    energized = energize_utility_connection(api, ctx["utility"]["id"])
    assert energized["status"] == "ENERGIZED"
    setup_started_phase(api, ctx, "2026-09-01", "2026-09-05",
                        phase_code="FINISHES", disruption_class="NON_INVASIVE",
                        sequence_index=6)

    error = validate_error(api.issue_occupancy_certificate(ctx["project"]["id"], PLAN_CHECKER),
                           ApiErrorId.ERR_PHASES_INCOMPLETE)
    assert error["error_id"] != ApiErrorId.ERR_FINAL_INSPECTION_MISSING.value, (
        "the phase gate is checked before the final-inspection gate")
    assert read_project(api, ctx["project"]["id"])["status"] == "UNDER_CONSTRUCTION"


def test_certificate_is_refused_without_a_passed_final_inspection(api):
    """PRD §3.9: "And the project must carry at least one inspection appointment whose
    `inspection_type` is `FINAL` and whose status is `PASSED`, or the answer is
    `ERR_FINAL_INSPECTION_MISSING` (HTTP 409)."
    PRD §3.9: "Every construction phase of the project must be `COMPLETE`, or the answer is
    `ERR_PHASES_INCOMPLETE` (HTTP 409)."

    Design: Corner/errors/certificate_without_passed_final_inspection_returns_final_inspection_missing
    """
    ctx = setup_permitted_project(api)
    energize_utility_connection(api, ctx["utility"]["id"])
    phase = setup_started_phase(api, ctx, "2026-09-01", "2026-09-05",
                                phase_code="FINISHES", disruption_class="NON_INVASIVE",
                                sequence_index=6)
    closed = complete_phase(api, phase["id"])
    assert closed["status"] == "COMPLETE"

    validate_error(api.issue_occupancy_certificate(ctx["project"]["id"], PLAN_CHECKER),
                   ApiErrorId.ERR_FINAL_INSPECTION_MISSING)

    assert read_project(api, ctx["project"]["id"])["status"] == "UNDER_CONSTRUCTION"
    _, meta = validate_paginated(
        api.list_occupancy_certificates(ctx["project"]["id"], PLAN_CHECKER))
    assert meta["total_count"] == 0


def test_certificate_in_a_seven_day_jurisdiction_permits_short_term_rental(api):
    """PRD §3.9: "Otherwise, if the jurisdiction's `str_min_lease_days` is 7 days or fewer —
    a week or less being the practical definition of a short-term rental — the classification
    is `SHORT_TERM_PERMITTED` and `min_lease_days` is simply the jurisdiction's
    `str_min_lease_days`, without the statewide floor applied."
    PRD §3.9: "Its `certificate_number` is the governing jurisdiction's `code`, a hyphen, and
    an issue sequence within that jurisdiction: the count of certificates already issued to
    projects sitting in that same jurisdiction, plus one — so the first certificate issued in
    a jurisdiction whose `code` is `SNVL` reads `SNVL-1`, the second `SNVL-2`."
    PRD §2.4: "Two entities are exceptions and carry only `id` and `created_at`: a feasibility
    screening (`FeasibilityScreening`) and an occupancy certificate (`OccupancyCertificate`).
    Both are immutable records of a decision frozen at a moment in time, so neither has an
    `updated_at` and neither has a `version`."

    Design: Corner/calculations/issue_certificate_short_term_permitted_and_immutable
    """
    ctx = setup_certificate_ready_project(api)
    move_clock(api, "2026-09-08T15:00:00Z")

    certificate = validate_success(
        api.issue_occupancy_certificate(ctx["project"]["id"], PLAN_CHECKER), 201)

    assert_occupancy_certificate(certificate)
    assert certificate["certificate_number"] == "PLMD-1"
    assert certificate["rental_classification"] == "SHORT_TERM_PERMITTED"
    assert certificate["min_lease_days"] == 7
    assert certificate["rental_ready"] is True
    assert certificate["blocking_reasons"] == []
    assert certificate["issued_on_date"] == "2026-09-08"
    assert parse_instant(certificate["final_inspection_passed_at"]) == parse_instant(
        "2026-09-05T10:00:00Z"), "the slot_end of the qualifying final inspection"
    assert "version" not in certificate
    assert "updated_at" not in certificate
    assert read_project(api, ctx["project"]["id"])["status"] == "FINALED"


def test_unoccupied_jadu_is_classified_rental_prohibited(api):
    """PRD §3.9: "`JADU_OWNER_OCCUPANCY_REQUIRED` applies when the project's `unit_type` is
    `JADU` and the parcel's `occupied` flag is false, because a junior ADU is only lawful
    where the owner actually lives on the parcel."
    PRD §3.9: "If `JADU_OWNER_OCCUPANCY_REQUIRED` is among them, the classification is
    `RENTAL_PROHIBITED` and `min_lease_days` is whichever is larger of the statewide 30-day
    floor and the jurisdiction's `str_min_lease_days`."
    PRD §3.9: "Finally, `rental_ready` is true only when the classification is not
    `RENTAL_PROHIBITED` **and** `blocking_reasons` is completely empty."

    Design: Corner/calculations/rental_readiness_prohibited_for_unoccupied_jadu
    """
    ctx = setup_certificate_ready_project(
        api, service_type="WATER",
        property_overrides={"address_line": "5 Poppy Rd", "lot_sqft": 7_000,
                            "existing_dwelling_sqft": 1_300, "occupied": False,
                            "in_str_overlay": False, "pre_adu_value_cents": 70_000_000},
        project_overrides={"unit_type": "JADU", "proposed_sqft": 500,
                           "proposed_height_ft": 12.0, "rear_setback_ft": 4.0,
                           "side_setback_ft": 4.0, "bedrooms": 1,
                           "contract_base_price_cents": 15_000_000})

    certificate = validate_success(
        api.issue_occupancy_certificate(ctx["project"]["id"], PLAN_CHECKER), 201)

    assert certificate["blocking_reasons"] == ["JADU_OWNER_OCCUPANCY_REQUIRED"]
    assert certificate["rental_classification"] == "RENTAL_PROHIBITED"
    assert certificate["min_lease_days"] == 30, "max(30, the jurisdiction's 7 days)"
    assert certificate["rental_ready"] is False
    assert read_project(api, ctx["project"]["id"])["status"] == "FINALED"
