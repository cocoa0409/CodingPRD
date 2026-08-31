"""Programme setup, the published material list, the roster row, the read-only
cost projection and the logical clock."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_program,
    assert_staffer,
    create_material_category_payload,
    create_program,
    create_program_payload,
    create_staffer_payload,
    read_cost_summary,
    read_program,
    validate_error,
    validate_success,
)


def test_create_program_starts_open_with_every_counter_at_zero(api):
    """PRD §3.1: "A newly created program starts fully open. Its `posture` is
    `OPEN`, `posture_override` is `NONE` with a null `posture_override_expires_utc`,
    and every derived counter starts at zero: `budget_encumbered_cents`,
    `budget_in_transit_cents`, `budget_spent_cents`,
    `open_containment_deficiency_count`, `budget_alert_count`,
    `participant_count_ytd` and `tonnage_ytd_kg`."
    PRD §2.4: "Every entity in this system additionally carries `updated_at`, an
    ISO 8601 UTC timestamp with three fractional digits, and `version`, an integer
    that begins at 1 on creation and increments by exactly 1 on every mutation of
    that row."

    Design: Corner/entities/create_program_mints_defaults_counters_and_version_one
    """
    response = api.create_program(create_program_payload(), ADMIN)
    program = validate_success(response, 201)

    assert_program(program)
    assert program["posture"] == "OPEN"
    assert program["posture_override"] == "NONE"
    assert program["posture_override_expires_utc"] is None
    assert program["version"] == 1, "A created programme starts at version 1"
    assert program["budget_encumbered_cents"] == 0
    assert program["budget_in_transit_cents"] == 0
    assert program["budget_spent_cents"] == 0
    assert program["open_containment_deficiency_count"] == 0
    assert program["budget_alert_count"] == 0
    assert program["participant_count_ytd"] == 0
    assert program["tonnage_ytd_kg"] == 0


def test_material_category_with_undeclared_acceptance_policy_is_rejected(api):
    """PRD §3.1: "The `acceptance_policy` is the fork in the road:
    `ACCEPTED_WITH_LIMIT` means the material is taken up to the stated quantity
    ceilings, while `REJECTED_ALWAYS` means it is never taken at an HHW event under
    any circumstances."
    PRD §2.5: "Request shape: every required body field present and of the declared
    type, every enum value a declared member, every required array non-empty, every
    numeric range satisfied, and — for event scheduling — `window_end_utc` strictly
    after `window_start_utc` and falling on the same UTC calendar date. Violations
    return `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_material_category_invalid_enum_returns_invalid_request
    """
    program = create_program()
    payload = create_material_category_payload(
        program["id"],
        {
            "code": "MYSTERY",
            "display_name": "Mystery Goo",
            "acceptance_policy": "MAYBE",
            "compatibility_class": "TOXIC",
            "dot_hazard_class": "NA",
            "max_kg_per_resident_per_event": 5.0,
            "max_kg_per_resident_per_year": 10.0,
            "disposal_rate_cents_per_kg": 100,
        },
    )

    response = api.create_material_category(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_get_material_category_with_unknown_id_returns_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_material_category_with_unknown_id_returns_material_category_not_found
    """
    response = api.get_material_category(NON_EXISTENT_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_MATERIAL_CATEGORY_NOT_FOUND, 404)


def test_cost_summary_for_unknown_program_returns_program_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/cost_summary_for_unknown_program_returns_program_not_found
    """
    response = api.get_cost_summary(NON_EXISTENT_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404)


def test_cost_summary_is_a_pure_projection_and_never_bumps_the_version(api):
    """PRD §2.4: "The computed cost report on a program is a pure projection and
    does not increment the program's `version`."
    PRD §3.9: "The cost report is a read-only projection computed on demand and
    available to `ProgramAdmin` and `EventCoordinator` alike."

    Design: Corner/endpoints/cost_summary_is_read_only_and_does_not_bump_version
    """
    program = create_program()
    assert program["version"] == 1

    validate_success(api.get_cost_summary(program["id"], COORDINATOR), 200)
    validate_success(api.get_cost_summary(program["id"], ADMIN), 200)

    after = read_program(program["id"])
    assert after["version"] == 1, "A read-only projection must not move the version"
    assert after["budget_encumbered_cents"] == 0


def test_clock_endpoint_echoes_the_new_logical_instant(api):
    """PRD §2.9: "A `ProgramAdmin` advances it by supplying a `to_iso8601` instant,
    and the response reports the resulting `current_utc`."
    PRD §2.9: "Moving the clock mutates no entity and increments no row's `version`;
    it is a test-driving affordance, not a business operation."

    Design: Corner/endpoints/clock_set_echoes_the_new_logical_instant
    """
    program = create_program()

    response = api.set_clock({"to_iso8601": "2026-09-12T09:00:00.000Z"}, ADMIN)
    data = validate_success(response, 200)

    assert data["current_utc"] == "2026-09-12T09:00:00.000Z"
    assert read_program(program["id"])["version"] == 1


def test_request_without_role_header_is_rejected_before_anything_else(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` carries a string
    that is not one of the eight declared roles, the request is rejected with
    `ERR_MISSING_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/roles/create_program_missing_x_user_role_header_returns_unauthenticated
    """
    response = api.create_program(
        create_program_payload(name="Headerless Program"),
        {"Content-Type": "application/json"},
    )
    validate_error(response, ApiErrorId.ERR_MISSING_CONTEXT_HEADER, 400)


def test_new_staffer_is_active_with_an_empty_hours_ledger(api):
    """PRD §3.4: "A staffer also carries a `status` of `ACTIVE` or `INACTIVE`,
    defaulting to `ACTIVE`; an inactive staffer remains on the roster for the record
    but may not be put on a lane. Their `assigned_hours` starts at zero."

    Design: Corner/entities/staffer_assigned_hours_is_computed_and_starts_at_zero
    """
    program = create_program()

    response = api.create_staffer(create_staffer_payload(program["id"]), COORDINATOR)
    staffer = validate_success(response, 201)

    assert_staffer(staffer)
    assert staffer["status"] == "ACTIVE"
    assert staffer["assigned_hours"] == 0
    assert staffer["version"] == 1


def test_program_with_nothing_received_bills_no_mobilisation_fee(api):
    """PRD §3.9: "One override sits on top of the tier table: when no manifest has
    been received at all, `mobilization_fee_cents` is zero rather than the tier-one
    figure — the contractor does not bill mobilisation for a season that shipped
    nothing."

    Design: Difficulty/boundary_precision_check/empty_program_cost_summary_zero_participant_boundary
    """
    program = create_program(
        name="Empty Fiscal Year Program", eligible_jurisdiction_codes=["CO-DEN"]
    )

    summary = read_cost_summary(program["id"])

    assert summary["event_count"] == 0
    assert summary["disposal_subtotal_cents"] == 0
    assert summary["received_tonnage_kg"] == 0
    assert summary["mobilization_fee_cents"] == 0, (
        "The tier table is bypassed entirely when no manifest has been received"
    )
    assert summary["volume_rebate_cents"] == 0
    assert summary["staffing_cost_cents"] == 0


def test_program_with_no_participants_reports_zero_cost_per_participant(api):
    """PRD §3.9: "Eleventh, `cost_per_participant_cents` is
    `total_program_cost_cents` divided by `participant_count` with the fraction
    discarded, and it is zero when `participant_count` is zero — the division is
    never attempted against an empty denominator."
    PRD §3.9: "A program with no completed appointments and no received manifests
    collapses the whole chain to a mobilisation of 0, a total of 0 and a cost per
    participant of 0."

    Design: Difficulty/boundary_precision_check/empty_program_cost_summary_zero_participant_boundary
    """
    program = create_program(
        name="Empty Fiscal Year Program", eligible_jurisdiction_codes=["CO-DEN"]
    )

    response = api.get_cost_summary(program["id"], ADMIN)
    summary = validate_success(response, 200)

    assert summary["participant_count"] == 0
    assert summary["pre_contingency_cents"] == 0
    assert summary["contingency_cents"] == 0
    assert summary["total_program_cost_cents"] == 0
    assert summary["cost_per_participant_cents"] == 0

    program_row = read_program(program["id"])
    assert program_row["participant_count_ytd"] == 0
    assert program_row["tonnage_ytd_kg"] == 0
