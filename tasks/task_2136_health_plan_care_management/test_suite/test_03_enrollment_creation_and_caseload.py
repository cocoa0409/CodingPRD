"""Enrolment eligibility gates, caseload arithmetic and the auto-assignment selector."""
import pytest

from test_helpers import (
    ApiErrorId, PROGRAM_ADMIN, assert_care_manager, assert_caseload_points,
    assert_enrollment, create_care_manager, create_care_manager_payload,
    create_enrollment_payload, create_member, create_program, enroll,
    read_care_manager, setup_program_and_managers, stratify, validate_error,
    validate_paginated, validate_success,
)


def _capacity_edge_setting():
    program = create_program(name="Capacity Edge Program", min_risk_tier="LOW")
    care_manager = create_care_manager(full_name="Rita Nolan", capacity_points=6.0)
    rising = create_member(external_member_id="MBR-1501", full_name="Rho Vance",
                           birth_date="1959-07-07", chronic_condition_count=10)
    moderate = create_member(external_member_id="MBR-1502", full_name="Mo Quinn",
                             birth_date="1964-08-08", chronic_condition_count=6)
    low = create_member(external_member_id="MBR-1503", full_name="Lee Ash",
                        birth_date="1977-09-09", chronic_condition_count=3)
    tiers = {
        "rising": stratify(rising["id"], "CONCURRENT")["tier"],
        "moderate": stratify(moderate["id"], "CONCURRENT")["tier"],
        "low": stratify(low["id"], "CONCURRENT")["tier"],
    }
    assert tiers == {"rising": "RISING", "moderate": "MODERATE", "low": "LOW"}
    return program, care_manager, rising, moderate, low


def test_caseload_exactly_at_capacity_leaves_the_manager_open(api):
    """PRD §3.3: "The tier contributes 1 point for `LOW`, 2 for `MODERATE`, 4 for
    `RISING` and 7 for `HIGH`."
    PRD §2.9: "Immediately after every recomputation of `assigned_caseload_points`,
    the manager's `capacity_status` is refreshed: it becomes `OVER_CAPACITY` when
    `assigned_caseload_points` is strictly greater than `capacity_points`, and
    `OPEN` otherwise."
    PRD §2.9: "Equality is `OPEN` — a manager loaded exactly to their ceiling is
    still open for business."

    Design: Difficulty/boundary_precision_check/caseload_equal_to_capacity_stays_open_and_one_point_more_is_rejected
    """
    program, care_manager, rising, moderate, _ = _capacity_edge_setting()

    first = enroll(rising["id"], program["id"], care_manager["id"])
    assert_caseload_points(first["acuity_weight_points"], 4.0)

    second = validate_success(
        api.create_enrollment(
            create_enrollment_payload(moderate["id"], program["id"],
                                      care_manager["id"]),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_enrollment(second)
    assert_caseload_points(second["acuity_weight_points"], 2.0)

    ledger = read_care_manager(care_manager["id"])
    assert_caseload_points(ledger["assigned_caseload_points"], 6.0)
    assert ledger["capacity_status"] == "OPEN"
    assert_care_manager(ledger)


def test_enrollment_that_would_overshoot_capacity_is_rejected(api):
    """PRD §3.3: "And the manager's current `assigned_caseload_points` plus the
    weight this new enrollment would consume must not exceed their
    `capacity_points`; equality is accepted, and only a strict overshoot is
    refused, with `ERR_CASELOAD_WOULD_EXCEED_CAPACITY`."

    Design: Difficulty/boundary_precision_check/caseload_equal_to_capacity_stays_open_and_one_point_more_is_rejected
    """
    program, care_manager, rising, moderate, low = _capacity_edge_setting()
    enroll(rising["id"], program["id"], care_manager["id"])
    enroll(moderate["id"], program["id"], care_manager["id"])

    response = api.create_enrollment(
        create_enrollment_payload(low["id"], program["id"], care_manager["id"]),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CASELOAD_WOULD_EXCEED_CAPACITY.value)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api.list_enrollments(PROGRAM_ADMIN, params={"member_id": low["id"]})
    )
    assert meta["total_count"] == 0, "the rejected create must persist no enrollment"

    ledger = read_care_manager(care_manager["id"])
    assert_caseload_points(ledger["assigned_caseload_points"], 6.0)
    assert ledger["capacity_status"] == "OPEN"


def test_new_care_manager_starts_with_an_empty_caseload_ledger(api):
    """PRD §3.3: "A new care manager starts with `assigned_caseload_points` at
    0.0, `capacity_status` at `OPEN`, and `active_enrollment_count` at 0."

    Design: Corner/entities/care_manager_create_rejects_computed_caseload_field
    """
    response = api.create_care_manager(
        create_care_manager_payload(full_name="Clean Create", capacity_points=8.0),
        PROGRAM_ADMIN,
    )
    data = validate_success(response, 201)
    assert_care_manager(data)
    assert_caseload_points(data["assigned_caseload_points"], 0.0)
    assert data["capacity_status"] == "OPEN"
    assert data["active_enrollment_count"] == 0


def test_new_enrollment_starts_pending_and_unreached(api):
    """PRD §3.3: "The new enrollment begins with `enrollment_status` `PENDING` and
    `engagement_status` `UNREACHED` — two dimensions that advance on entirely
    disjoint triggers, so an enrollment's engagement state is never a function of
    its lifecycle state and vice versa, with the single proviso that engagement
    transitions are only recorded while `enrollment_status` is `ACTIVE`."
    PRD §3.3: "An enrollment created this way records `assignment_reason` as
    `EXPLICIT`."
    PRD §2.9: "The manager's `active_enrollment_count` is a separate counter,
    tracking only enrollments whose `enrollment_status` is `ACTIVE`."

    Design: Corner/state_machines/enrollment_starts_pending_and_unreached_with_no_cadence_clock
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "Init State Program", "min_risk_tier": "LOW"},
        with_reviewer=False,
    )
    member = create_member(external_member_id="MBR-4001", full_name="Init Ivy",
                           birth_date="1972-02-02", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")

    data = validate_success(
        api.create_enrollment(
            create_enrollment_payload(member["id"], setting["program"]["id"],
                                      setting["care_manager"]["id"]),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_enrollment(data)
    assert data["enrollment_status"] == "PENDING"
    assert data["engagement_status"] == "UNREACHED"
    assert data.get("activated_at") is None
    assert data.get("next_touch_due_at") is None
    assert data.get("toc_due_at") is None
    assert data["assignment_reason"] == "EXPLICIT"
    assert data["risk_tier_at_enrollment"] == "LOW"
    assert_caseload_points(data["acuity_weight_points"], 1.0)

    ledger = read_care_manager(setting["care_manager"]["id"])
    assert_caseload_points(ledger["assigned_caseload_points"], 1.0)
    assert ledger["active_enrollment_count"] == 0


def test_auto_assignment_ranks_by_headroom_then_creation_order(api):
    """PRD §3.3: "Surviving candidates are then ranked by headroom —
    `capacity_points` minus `assigned_caseload_points`, compared at one decimal
    place — from largest headroom to smallest. Where two candidates have identical
    headroom, the one with the earlier `created_at` wins. The first-ranked
    candidate becomes the enrollment's `care_manager_id` and `assignment_reason`
    is recorded as `AUTO_SELECTED`."

    Design: Corner/calculations/auto_assignment_ranks_by_headroom_then_created_at_ascending
    """
    program = create_program(name="Selector Program", min_risk_tier="LOW")
    first = create_care_manager(full_name="One Nolan", capacity_points=10.0)
    second = create_care_manager(full_name="Two Ruiz", capacity_points=8.0)
    third = create_care_manager(full_name="Three Vale", capacity_points=8.0)

    loaded_member = create_member(external_member_id="MBR-5501",
                                  full_name="Load Lena", birth_date="1957-07-17",
                                  chronic_condition_count=10)
    picked_member = create_member(external_member_id="MBR-5502",
                                  full_name="Pick Pete", birth_date="1981-08-18",
                                  chronic_condition_count=0)
    stratify(loaded_member["id"], "CONCURRENT")
    stratify(picked_member["id"], "CONCURRENT")

    enroll(loaded_member["id"], program["id"], first["id"])
    assert_caseload_points(
        read_care_manager(first["id"])["assigned_caseload_points"], 4.0
    )

    data = validate_success(
        api.create_enrollment(
            create_enrollment_payload(picked_member["id"], program["id"]),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert data["care_manager_id"] == second["id"], (
        "headroom 8.0 beats 6.0, and the earlier-created of the tied pair wins"
    )
    assert data["care_manager_id"] != first["id"]
    assert data["care_manager_id"] != third["id"]
    assert data["assignment_reason"] == "AUTO_SELECTED"
    assert_caseload_points(
        read_care_manager(second["id"])["assigned_caseload_points"], 1.0
    )
    assert_caseload_points(
        read_care_manager(third["id"])["assigned_caseload_points"], 0.0
    )


def test_second_enrollment_in_the_same_program_is_rejected(api):
    """PRD §3.3: "The member may not already hold another enrollment in the same
    program whose `enrollment_status` is `PENDING` or `ACTIVE`; a second one is
    refused with `ERR_DUPLICATE_ACTIVE_ENROLLMENT`."

    Design: Corner/validations/second_enrollment_in_same_program_returns_duplicate_active_enrollment
    """
    setting = setup_program_and_managers(
        program_overrides={"name": "Dup Program"}, with_reviewer=False
    )
    member = create_member(external_member_id="MBR-6301", full_name="Dup Dan",
                           birth_date="1970-01-01", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")
    enroll(member["id"], setting["program"]["id"], setting["care_manager"]["id"])

    response = api.create_enrollment(
        create_enrollment_payload(member["id"], setting["program"]["id"],
                                  setting["care_manager"]["id"]),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ACTIVE_ENROLLMENT.value)
    assert response.status_code == 409

    _, meta = validate_paginated(
        api.list_enrollments(
            PROGRAM_ADMIN,
            params={"member_id": member["id"],
                    "program_id": setting["program"]["id"]},
        )
    )
    assert meta["total_count"] == 1
    assert_caseload_points(
        read_care_manager(setting["care_manager"]["id"])["assigned_caseload_points"],
        1.0,
    )


def test_enrollment_without_the_programs_variant_is_rejected(api):
    """PRD §3.3: "The member must have at least one stratification whose `variant`
    equals the program's `stratification_variant`, or the request fails with
    `ERR_STRATIFICATION_REQUIRED`."
    PRD §3.3: "However the manager is chosen, creation freezes two snapshots that
    never move again: `risk_tier_at_enrollment` takes the `tier` and
    `risk_score_at_enrollment` takes the `score` of the member's latest
    stratification under the program's `stratification_variant`."

    Design: Corner/validations/enrollment_without_matching_variant_returns_stratification_required
    """
    program = create_program(name="Prospective Program", min_risk_tier="LOW",
                             stratification_variant="PROSPECTIVE")
    care_manager = create_care_manager(full_name="Rita Nolan")
    member = create_member(external_member_id="MBR-6401", full_name="Var Vic",
                           birth_date="1970-01-01", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")

    response = api.create_enrollment(
        create_enrollment_payload(member["id"], program["id"], care_manager["id"]),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STRATIFICATION_REQUIRED.value)
    assert response.status_code == 422

    stratify(member["id"], "PROSPECTIVE")
    data = validate_success(
        api.create_enrollment(
            create_enrollment_payload(member["id"], program["id"],
                                      care_manager["id"]),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert data["risk_tier_at_enrollment"] == "LOW"


def test_enrollment_below_the_program_minimum_tier_is_rejected(api):
    """PRD §3.3: "That stratification's tier must rank at or above the program's
    `min_risk_tier`, ranking the tiers `LOW` below `MODERATE`, `MODERATE` below
    `RISING` and `RISING` below `HIGH`; a member who ranks strictly lower is
    turned away with `ERR_RISK_TIER_BELOW_PROGRAM_MINIMUM`."

    Design: Corner/validations/enrollment_below_program_minimum_tier_is_rejected
    """
    program = create_program(name="High Bar Program", min_risk_tier="HIGH")
    care_manager = create_care_manager(full_name="Rita Nolan")
    member = create_member(external_member_id="MBR-6501", full_name="Low Lou",
                           birth_date="1970-01-01", chronic_condition_count=0)
    assert stratify(member["id"], "CONCURRENT")["tier"] == "LOW"

    response = api.create_enrollment(
        create_enrollment_payload(member["id"], program["id"], care_manager["id"]),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_RISK_TIER_BELOW_PROGRAM_MINIMUM.value)
    assert response.status_code == 422
    assert_caseload_points(
        read_care_manager(care_manager["id"])["assigned_caseload_points"], 0.0
    )


def test_enrollment_naming_an_unauthorized_credential_is_rejected(api):
    """PRD §3.3: "Their `credential_level` must be one of the program's
    `required_credential_levels`, else `ERR_CREDENTIAL_NOT_AUTHORIZED`."

    Design: Corner/validations/enrollment_with_unauthorized_credential_is_rejected
    """
    program = create_program(name="LCSW Only Program", min_risk_tier="LOW",
                             required_credential_levels=["LCSW"])
    registered_nurse = create_care_manager(full_name="Rita Nolan",
                                           credential_level="RN")
    member = create_member(external_member_id="MBR-6601", full_name="Cred Cy",
                           birth_date="1970-01-01", chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")

    response = api.create_enrollment(
        create_enrollment_payload(member["id"], program["id"],
                                  registered_nurse["id"]),
        PROGRAM_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CREDENTIAL_NOT_AUTHORIZED.value)
    assert response.status_code == 422


def test_enrollment_outside_the_managers_licensed_states_is_rejected(api):
    """PRD §3.3: "The member's `state_code` must appear in the manager's
    `licensed_state_codes`, else `ERR_STATE_LICENSURE_MISMATCH`."
    PRD §3.3: "If the filter leaves no candidate at all, nothing is created and
    the request is refused with `ERR_NO_ELIGIBLE_CARE_MANAGER`."

    Design: Corner/validations/enrollment_with_state_licensure_mismatch_is_rejected
    """
    program = create_program(name="Licensure Program", min_risk_tier="LOW")
    out_of_state = create_care_manager(full_name="NY Nolan",
                                       licensed_state_codes=["NY"])
    member = create_member(external_member_id="MBR-6701", full_name="Cali Cam",
                           birth_date="1970-01-01", state_code="CA",
                           chronic_condition_count=0)
    stratify(member["id"], "CONCURRENT")

    explicit = api.create_enrollment(
        create_enrollment_payload(member["id"], program["id"], out_of_state["id"]),
        PROGRAM_ADMIN,
    )
    validate_error(explicit, ApiErrorId.ERR_STATE_LICENSURE_MISMATCH.value)
    assert explicit.status_code == 422

    auto = api.create_enrollment(
        create_enrollment_payload(member["id"], program["id"]), PROGRAM_ADMIN
    )
    validate_error(auto, ApiErrorId.ERR_NO_ELIGIBLE_CARE_MANAGER.value)
    assert auto.status_code == 409
