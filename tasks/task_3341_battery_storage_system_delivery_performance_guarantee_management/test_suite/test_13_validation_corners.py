"""Validation corner tests: OCC stale-version rejections, creation-time shape
errors, and LTSA term checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_all_permits,
    create_esa,
    create_project,
    create_project_payload,
    create_service_agreement_payload,
    get_success_data,
    setup_active_ltsa,
    validate_error,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
SVC_MGR = TEST_USERS["service_manager_headers"]


def test_esa_execute_rejects_stale_project_version_with_412(api):
    """PRD §2.6: "Executing an equipment supply agreement requires
    `expected_project_version`, carrying the client's last observed `version`
    of the parent project. If the project's current `version` has advanced
    since that read — for example because a sibling agreement was executed or a
    milestone outcome recomputed the project's capacity fields — the execution
    is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

    Design: Corner/validations/esa_execute_rejects_stale_project_version_with_412
    """
    project = create_project(api=api)
    approve_all_permits(project["id"], api=api)
    esa1 = create_esa(project["id"], api=api)
    esa2 = create_esa(
        project["id"], api=api,
        contracted_power_mw=5, contracted_energy_mwh=5, guaranteed_capacity_mwh=4,
        price_per_mwh_cents=100000, ld_rate_per_day_cents=10000,
        ld_cap_cents=100000,
    )
    v_before = get_success_data(api.get_project(project["id"], DEV))["version"]
    # Executing the sibling ESA bumps Project.version past v_before.
    validate_success(
        api.execute_esa(esa2["id"], {"expected_project_version": v_before}, DEV)
    )

    resp = api.execute_esa(esa1["id"], {"expected_project_version": v_before}, DEV)
    validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)
    esa1_after = get_success_data(api.get_esa(esa1["id"], DEV))
    assert esa1_after["status"] == "DRAFT"

    # A retry carrying the fresh version succeeds.
    v_fresh = get_success_data(api.get_project(project["id"], DEV))["version"]
    executed = validate_success(
        api.execute_esa(esa1["id"], {"expected_project_version": v_fresh}, DEV)
    )
    assert executed["status"] == "EXECUTED"


def test_spare_part_order_rejects_stale_ltsa_version_with_412(api):
    """PRD §2.6: "Creating a spare-part order requires
    `expected_service_agreement_version`, carrying the client's last observed
    `version` of the parent service agreement. A mismatch is rejected with
    `ERR_STALE_LTSA_VERSION` (HTTP 412), forcing a fresh read of the
    credit-pool balance before credit is drawn."

    Design: Corner/validations/spare_part_order_rejects_stale_ltsa_version_with_412
    """
    project = create_project(api=api)
    ltsa = setup_active_ltsa(project["id"], api=api)
    current = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))

    resp = api.create_spare_part_order(
        {
            "service_agreement_id": ltsa["id"],
            "part_description": "Contactor",
            "part_cost_cents": 100000,
            "expected_service_agreement_version": current["version"] - 1,
        },
        SVC_MGR,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_LTSA_VERSION)
    after = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
    assert after["credit_drawn_cents"] == 0


def test_order_creation_missing_required_field_returns_400(api):
    """PRD §2.8: "Pure creation-time shape errors — missing required fields,
    invalid enum values, non-positive quantities, violated input constraints
    on a create payload — are also detected at this stage, so a malformed
    create is rejected with `ERR_INVALID_REQUEST` and never reaches a state
    check."
    PRD §3.7: "Creating an order names the `service_agreement_id`, an optional
    nullable `warranty_claim_id` linking the order to a claim, a free-text
    `part_description`, a non-negative `part_cost_cents`, and the
    `expected_service_agreement_version` guard of §2.6."

    Design: Corner/validations/order_creation_missing_required_field_returns_400
    """
    project = create_project(api=api)
    ltsa = setup_active_ltsa(project["id"], api=api)
    current = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))

    resp = api.create_spare_part_order(
        {
            "service_agreement_id": ltsa["id"],
            "part_description": "Missing cost",
            "expected_service_agreement_version": current["version"],
        },
        SVC_MGR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_ltsa_activate_outside_term_rejected(api):
    """PRD §3.6: "Activation is allowed only while the logical clock sits
    within the inclusive term — at or after `start_date` and at or before
    `end_date`, else `ERR_LTSA_NOT_IN_TERM`"

    Design: Corner/validations/ltsa_activate_outside_term_rejected
    """
    project = create_project(api=api)
    ltsa = validate_success(
        api.create_service_agreement(
            create_service_agreement_payload(
                project["id"],
                start_date="2027-01-01T00:00:00Z",
                end_date="2028-01-01T00:00:00Z",
            ),
            SVC_MGR,
        ),
        expected_status=201,
    )
    resp = api.activate_service_agreement(ltsa["id"], SVC_MGR)
    validate_error(resp, ApiErrorId.ERR_LTSA_NOT_IN_TERM)
    after = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
    assert after["status"] == "DRAFT"
