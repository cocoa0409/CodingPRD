"""Cross-entity state dependencies: the refusal lives on the collaborator.

Every test in this module translates exactly one non-stub instance of the
``cross_entity_state_dependency`` rule of ``SCAFFOLD_DIFFICULTY_DESIGN.yaml``.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    CLOCK_START,
    ApiErrorId,
    add_workstation,
    apply_action,
    assert_cents,
    assert_instants_equal,
    assert_points,
    citation_payload,
    create_establishment,
    create_licensed_practitioner,
    create_school,
    create_violation_code,
    license_action_payload,
    post_licence,
    propose_rental,
    refresh_booth_rental,
    refresh_establishment,
    refresh_inspection,
    refresh_workstation,
    setup_finalized_inspection,
    setup_submitted_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)


# --- cross_entity_state_dependency / booth rental x practitioner licence ------
def _rental_proposed_for_a_practitioner_on_probation(api):
    """A perfectly legal ``PROPOSED`` rental whose occupant slips to PROBATION.

    PRD 3.2 says ``PLACE_ON_PROBATION`` "moves ``ACTIVE -> PROBATION`` and does
    nothing else", so the rental and the posting are left exactly as they were.
    """
    school = create_school(api, required_clock_hours=16.00)
    practitioner = create_licensed_practitioner(
        api, school_id=school["id"], full_name="Noor Haddad"
    )
    establishment = create_establishment(
        api, station_capacity=3, legal_name="Cedar Studio"
    )
    station = add_workstation(
        api, establishment["id"], station_number=1, station_type="STYLING_CHAIR"
    )
    rental = propose_rental(
        api,
        station["id"],
        practitioner["id"],
        term_start_at=CLOCK_START,
        monthly_rent_cents=70000,
    )
    post_licence(api, station["id"], practitioner["id"])
    apply_action(
        api,
        practitioner["id"],
        "PLACE_ON_PROBATION",
        reason="unsanitised implements observed during a spot check",
    )
    return {
        "practitioner": practitioner,
        "establishment": establishment,
        "workstation": station,
        "booth_rental": rental,
    }


def test_activation_refused_while_the_occupant_is_on_probation_then_succeeds_after_reinstate(
    api,
):
    """PRD 3.3: activation requires the occupant's `license_status` to be exactly
    `ACTIVE` -- "`PROBATION` is explicitly not sufficient to activate a rental" --
    and PRD 3.2 refuses such a caller with `ERR_PRACTITIONER_LICENSE_NOT_ACTIVE`
    (409) even though the rental itself is a legal `PROPOSED` throughout.

    Design: Difficulty/cross_entity_state_dependency/booth_rental_activation_gated_on_practitioner_license_status
    """
    world = _rental_proposed_for_a_practitioner_on_probation(api)
    rental_id = world["booth_rental"]["id"]
    station_id = world["workstation"]["id"]
    practitioner_id = world["practitioner"]["id"]

    refused = api.activate_booth_rental(rental_id, BOARD_ADMIN_HEADERS)
    validate_error(refused, ApiErrorId.ERR_PRACTITIONER_LICENSE_NOT_ACTIVE, 409)

    # Nothing about the rental explains the refusal: it is still PROPOSED.
    assert refresh_booth_rental(api, rental_id)["status"] == "PROPOSED"
    station = refresh_workstation(api, station_id)
    # PRD 3.3: probation keeps the posting on the station but invalidates it, so
    # the derived verdict falls to STALE_POSTING rather than MISSING_POSTING.
    assert station["posted_practitioner_id"] == practitioner_id
    assert station["posting_status"] == "STALE_POSTING"

    reinstated = validate_success(
        api.apply_license_action(
            practitioner_id,
            license_action_payload("REINSTATE", reason="corrective training completed"),
            BOARD_ADMIN_HEADERS,
        )
    )
    assert reinstated["license_status"] == "ACTIVE"
    # PRD 3.2: a REINSTATE from PROBATION carries a null suspension_cause_points,
    # so it posts no reversal and leaves sanction_points where it was.
    assert_points(reinstated["sanction_points"], 0.00, "sanction_points")
    assert reinstated["suspension_cause_points"] is None

    activated = validate_success(
        api.activate_booth_rental(rental_id, BOARD_ADMIN_HEADERS)
    )
    assert activated["status"] == "ACTIVE"
    assert refresh_workstation(api, station_id)["posting_status"] == "COMPLIANT"


def test_probation_licence_gate_outranks_the_posting_compliance_check(api):
    """PRD 2.9 evaluates the referenced practitioner's licence at step 11
    (`ERR_PRACTITIONER_LICENSE_NOT_ACTIVE`) before the posting-compliance rule at
    step 13 (`ERR_WORKSTATION_POSTING_NONCOMPLIANT`), so an unposted station whose
    occupant is on probation reports the collaborating entity's state, while the
    identical call for an `ACTIVE` occupant reports the posting defect.

    Design: Difficulty/cross_entity_state_dependency/booth_rental_activation_gated_on_practitioner_license_status
    """
    school = create_school(api, required_clock_hours=16.00)
    on_probation = create_licensed_practitioner(
        api, school_id=school["id"], full_name="Noor Haddad"
    )
    still_active = create_licensed_practitioner(
        api, school_id=school["id"], full_name="Rhea Vance"
    )
    establishment = create_establishment(
        api, station_capacity=3, legal_name="Cedar Studio"
    )
    first_station = add_workstation(api, establishment["id"], station_number=1)
    second_station = add_workstation(api, establishment["id"], station_number=2)
    probation_rental = propose_rental(
        api, first_station["id"], on_probation["id"], term_start_at=CLOCK_START
    )
    active_rental = propose_rental(
        api, second_station["id"], still_active["id"], term_start_at=CLOCK_START
    )
    apply_action(
        api,
        on_probation["id"],
        "PLACE_ON_PROBATION",
        reason="unsanitised implements observed during a spot check",
    )

    # Neither station carries a posting, so step 13 is unhappy on both calls.
    validate_error(
        api.activate_booth_rental(probation_rental["id"], BOARD_ADMIN_HEADERS),
        ApiErrorId.ERR_PRACTITIONER_LICENSE_NOT_ACTIVE,
        409,
    )
    validate_error(
        api.activate_booth_rental(active_rental["id"], BOARD_ADMIN_HEADERS),
        ApiErrorId.ERR_WORKSTATION_POSTING_NONCOMPLIANT,
        409,
    )
    assert refresh_booth_rental(api, probation_rental["id"])["status"] == "PROPOSED"
    assert refresh_booth_rental(api, active_rental["id"])["status"] == "PROPOSED"


# --- cross_entity_state_dependency / citation x inspection lifecycle ----------
def _submitted_visit_with_one_minor_finding(api):
    """PRD 3.5: one MINOR SAN-100 finding observed twice, submitted for review."""
    code = create_violation_code(
        api,
        severity="MINOR",
        base_points=5.00,
        fine_cents_base=4000,
        category="SANITATION",
        code="SAN-100",
    )
    establishment = create_establishment(
        api, station_capacity=4, legal_name="Willow Salon"
    )
    findings = [
        {
            "violation_code_id": code["id"],
            "observed_count": 2,
            "corrected_on_site": False,
        }
    ]
    return {"violation_code": code, "establishment": establishment, "findings": findings}


def test_citation_on_a_pending_review_inspection_reports_not_finalized_over_the_version_token(
    api,
):
    """PRD 3.7: "An inspection that is not `FINALIZED` is refused with
    `ERR_INSPECTION_NOT_FINALIZED` (409)", and PRD 2.9 puts that state gate at step
    11, ahead of the optimistic-concurrency token at step 12, so a stale
    `expected_inspection_version` never surfaces while the parent is `PENDING_REVIEW`.

    Design: Difficulty/cross_entity_state_dependency/citation_creation_gated_on_inspection_finalized_state_over_version_check
    """
    world = _submitted_visit_with_one_minor_finding(api)
    submitted = setup_submitted_inspection(
        api, world["establishment"]["id"], findings=world["findings"]
    )["inspection"]
    assert submitted["status"] == "PENDING_REVIEW"

    stale_token = submitted["version"] - 1
    assert stale_token >= 1
    refused = api.create_citation(
        citation_payload(
            inspection_id=submitted["id"],
            expected_inspection_version=stale_token,
            subject_type="ESTABLISHMENT",
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(refused, ApiErrorId.ERR_INSPECTION_NOT_FINALIZED, 409)

    unchanged = refresh_inspection(api, submitted["id"])
    assert unchanged["status"] == "PENDING_REVIEW"
    assert unchanged["citation_count"] == 0
    rows, meta = validate_paginated(
        api.list_citations(BOARD_ADMIN_HEADERS, {"inspection_id": submitted["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_finalized_inspection_reports_the_stale_version_then_accepts_a_fresh_token(api):
    """PRD 2.8: once the parent is `FINALIZED` the step-11 gate is satisfied and the
    step-12 token is what fires -- `ERR_STALE_INSPECTION_VERSION` (412) -- while the
    identical body succeeds on a freshly read `version`, with the fine clamped up to
    PRD 3.7's 5000-cent statutory floor.

    Design: Difficulty/cross_entity_state_dependency/citation_creation_gated_on_inspection_finalized_state_over_version_check
    """
    world = _submitted_visit_with_one_minor_finding(api)
    establishment_id = world["establishment"]["id"]
    finalized = setup_finalized_inspection(
        api, establishment_id, findings=world["findings"]
    )["inspection"]
    # 5.00 base * 1.0 MINOR weight * 2 observed * 1.0 repeat * (1 - 0.00) = 10.00,
    # which is not strictly greater than 10.00, so PRD 3.5 bands it as PASS.
    assert_points(finalized["final_adjusted_score"], 10.00, "final_adjusted_score")
    assert finalized["final_outcome"] == "PASS"
    # PRD 3.7 hop four promotes PENDING_INSPECTION -> ACTIVE on a PASS.
    assert refresh_establishment(api, establishment_id)["license_status"] == "ACTIVE"

    stale = api.create_citation(
        citation_payload(
            inspection_id=finalized["id"],
            expected_inspection_version=finalized["version"] - 1,
            subject_type="ESTABLISHMENT",
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_INSPECTION_VERSION, 412)

    fresh = refresh_inspection(api, finalized["id"])
    citation = validate_success(
        api.create_citation(
            citation_payload(
                inspection_id=finalized["id"],
                expected_inspection_version=fresh["version"],
                subject_type="ESTABLISHMENT",
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    assert citation["max_finding_severity"] == "MINOR"
    # Snapshot demerit_balance_before_finalize is 0.00, so the tier stays at 1.00.
    assert_points(citation["demerit_tier_multiplier"], 1.00, "demerit_tier_multiplier")
    # Raw 4000 * 1.00 * 1.00 with no surcharge (10.00 < 30.00 tolerance) clamps up.
    assert_cents(citation["assessed_fine_cents"], 5000, "assessed_fine_cents")
    assert_cents(citation["administrative_fee_cents"], 250, "administrative_fee_cents")
    assert_cents(citation["total_due_cents"], 5250, "total_due_cents")
    assert_cents(citation["outstanding_fine_cents"], 5250, "outstanding_fine_cents")
    assert_instants_equal(citation["due_at"], "2026-08-31T00:00:00.000Z", "due_at")
    assert_instants_equal(
        citation["contest_deadline_at"], "2026-08-21T00:00:00.000Z", "contest_deadline_at"
    )
    assert refresh_inspection(api, finalized["id"])["citation_count"] == 1
