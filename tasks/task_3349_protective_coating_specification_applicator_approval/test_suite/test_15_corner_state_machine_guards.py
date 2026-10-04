"""Corner breadth index (state machines): invalid transitions rejected with
the generic state error, and terminal-state lockdown on warranties.
"""
from test_helpers import (
    PROJECT_ENGINEER_HEADERS,
    TECHNICAL_SERVICE_ENGINEER_HEADERS,
    ApiClient,
    ApiErrorId,
    adjudicate,
    create_work_order,
    create_world,
    drive_to_open_investigation,
    drive_to_prep_approved,
    make_applicator_rep_headers,
    read_investigation,
    read_warranty,
    read_work_order,
    validate_error,
    validate_error_is_one_of,
)


def test_work_order_begin_prep_inspection_from_prep_approved_rejected(api: ApiClient):
    """PRD §3.5: "an `ApplicatorRep` begins preparation inspection, moving the
    work order from `SCHEDULED` to `PREP_INSPECTION`".
    PRD §2.9: "State preconditions of the requested transition
    (`ERR_INVALID_STATE` or the state-specific aliases `ERR_SPEC_NOT_ISSUED`,
    `ERR_QUALIFICATION_NOT_CERTIFIED`, `ERR_WARRANTY_NOT_ACTIVE`,
    `ERR_COAT_NOT_CURED`, `ERR_HOLD_POINT_NOT_RELEASED`, `ERR_SYSTEM_OBSOLETE`,
    and `ERR_PROGRAM_NOT_ACTIVE`, HTTP 409), on every state-transition
    endpoint."

    Design: Corner/state_machines/work_order_begin_prep_inspection_from_prep_approved_rejected
    """
    world = create_world(api, system_overrides={"system_code": "SW-SM-WO"})
    work_order = drive_to_prep_approved(api, world, asset_zone="Z1")

    response = api.begin_prep_inspection(
        world["project"]["id"], work_order["id"],
        make_applicator_rep_headers(world["applicator"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert read_work_order(api, work_order["id"])["status"] == "PREP_APPROVED"


def test_work_order_complete_from_scheduled_rejected(api: ApiClient):
    """PRD §3.6: "A `ProjectEngineer` completes a `COATING_IN_PROGRESS` work
    order only when every coat on it is fully resolved".
    PRD §2.9: "State preconditions of the requested transition
    (`ERR_INVALID_STATE` or the state-specific aliases `ERR_SPEC_NOT_ISSUED`,
    `ERR_QUALIFICATION_NOT_CERTIFIED`, `ERR_WARRANTY_NOT_ACTIVE`,
    `ERR_COAT_NOT_CURED`, `ERR_HOLD_POINT_NOT_RELEASED`, `ERR_SYSTEM_OBSOLETE`,
    and `ERR_PROGRAM_NOT_ACTIVE`, HTTP 409), on every state-transition
    endpoint."

    Design: Corner/state_machines/work_order_complete_from_scheduled_rejected
    """
    world = create_world(api, system_overrides={"system_code": "SW-SM-WC"})
    work_order = create_work_order(
        api, world["project"]["id"], world["spec"]["id"], world["applicator"]["id"],
        asset_zone="Z1",
    )

    response = api.complete_work_order(
        world["project"]["id"], work_order["id"], PROJECT_ENGINEER_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert read_work_order(api, work_order["id"])["status"] == "SCHEDULED"


def test_warranty_void_from_terminal_state_rejected(api: ApiClient):
    """PRD §3.7: "Separately, a `TechnicalServiceEngineer` may void an
    `ACTIVE` warranty for documented applicator fraud or work-order
    misrepresentation".
    PRD §3.7: "`RESOLVED`, `DENIED`, and `VOIDED` are terminal for the
    warranty".

    Design: Corner/state_machines/warranty_void_from_resolved_terminal_lockdown
    """
    world = create_world(api, system_overrides={"system_code": "SW-SM-WAR"})
    opened = drive_to_open_investigation(api, world, asset_zone="Z1", exposure_cents=1_000_000)
    warranty = opened["warranty"]
    adjudicate(api, warranty["id"], opened["investigation"]["id"], "NO_DEFECT")
    assert read_warranty(api, warranty["id"])["status"] == "DENIED"

    response = api.void_warranty(
        world["project"]["id"], warranty["id"],
        {"void_reason": "late fraud claim"}, TECHNICAL_SERVICE_ENGINEER_HEADERS,
    )

    validate_error_is_one_of(
        response, [ApiErrorId.ERR_WARRANTY_NOT_ACTIVE, ApiErrorId.ERR_INVALID_STATE]
    )
    assert response.status_code == 409, (
        f"terminal lockdown must be a 409 state error, got {response.status_code}"
    )
    assert read_warranty(api, warranty["id"])["status"] == "DENIED"


def test_failure_investigation_adjudicate_from_opened_rejected(api: ApiClient):
    """PRD §3.7: "Investigation proceeds in two steps, both by a
    `TechnicalServiceEngineer`. Beginning evidence moves the investigation
    from `OPENED` to `EVIDENCE_GATHERING`. Adjudication then closes it with an
    `outcome` of `PRODUCT_DEFECT`, `APPLICATION_ERROR`, `SHARED`, or
    `NO_DEFECT`, moving the investigation from `EVIDENCE_GATHERING` to
    `ADJUDICATED_PRODUCT_DEFECT`, `ADJUDICATED_APPLICATION_ERROR`,
    `ADJUDICATED_SHARED`, or `CLOSED_NO_DEFECT` respectively".
    PRD §2.9: "State preconditions of the requested transition
    (`ERR_INVALID_STATE` or the state-specific aliases `ERR_SPEC_NOT_ISSUED`,
    `ERR_QUALIFICATION_NOT_CERTIFIED`, `ERR_WARRANTY_NOT_ACTIVE`,
    `ERR_COAT_NOT_CURED`, `ERR_HOLD_POINT_NOT_RELEASED`, `ERR_SYSTEM_OBSOLETE`,
    and `ERR_PROGRAM_NOT_ACTIVE`, HTTP 409), on every state-transition
    endpoint."

    Design: Corner/state_machines/failure_investigation_adjudicate_from_opened_rejected
    """
    world = create_world(api, system_overrides={"system_code": "SW-SM-FI"})
    opened = drive_to_open_investigation(api, world, asset_zone="Z1", begin=False)
    warranty = opened["warranty"]
    investigation = opened["investigation"]

    response = api.adjudicate_investigation(
        warranty["id"], investigation["id"],
        {"outcome": "PRODUCT_DEFECT", "adjudicated_fault_pct": 100},
        TECHNICAL_SERVICE_ENGINEER_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert read_investigation(api, warranty["id"])["status"] == "OPENED"
