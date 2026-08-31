"""Action endpoints, filtered listings, the domain-specific 404 codes, and the
role and identity boundaries."""

import pytest

from test_helpers import (
    ApiErrorId,
    BILLING_CLERK,
    DISPATCHER,
    SAFETY_MANAGER,
    TEST_USERS,
    build_critical_world,
    build_standard_world,
    commit_gear,
    configure_body,
    make_customer_headers,
    make_engineer_headers,
    make_operator_headers,
    new_customer,
    new_operator,
    open_plan,
    open_review,
    read_gear,
    read_plan,
    read_review,
    setup_configured_plan,
    setup_critical_plan_under_review,
    setup_released_standard_plan,
    setup_surveyed_plan_with_gear,
    survey_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

def test_withdrawing_a_commitment_updates_the_gear_ledger_and_locks_out_a_repeat(api):
    """PRD 3.4: "Withdrawing a commitment moves it from `ACTIVE` to `RELEASED` and
    recomputes the gear's `committed_assignment_count`; withdrawing anything that is
    not currently `ACTIVE` is refused with `ERR_INVALID_GEAR_STATE`."
    PRD 2.4: "and `version`, an integer that begins at 1 when the row is created and
    increases by exactly 1 on every mutation of that row."

    Design: Corner/endpoints/gear_assignment_release_action_endpoint_updates_the_commitment_ledger
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9500")
    survey_plan(world, plan["id"])
    assignment = commit_gear(world, plan["id"])
    assert assignment["version"] == 1

    released = validate_success(api.release_gear_assignment(assignment["id"], DISPATCHER))
    assert released["status"] == "RELEASED"
    assert released["version"] == 2
    assert read_gear(world["gear_id"])["committed_assignment_count"] == 0

    validate_error(api.release_gear_assignment(assignment["id"], DISPATCHER),
                   ApiErrorId.ERR_INVALID_GEAR_STATE.value, 409)


def test_lift_plans_can_be_narrowed_by_their_readiness_posture(api):
    """PRD 3.3: "Plans are listable and can be narrowed by `site_id`, `customer_id`,
    `crane_id`, `operator_id`, `rigger_id`, `plan_status` and `field_status`."
    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filters before pagination is applied and `has_more` is true when rows remain
    beyond the current page."

    Design: Corner/endpoints/list_lift_plans_filtered_by_plan_status_returns_only_matching_rows
    """
    world = build_standard_world()
    drafted = open_plan(world, job_reference="JOB-DRAFT")
    surveyed = open_plan(world, job_reference="JOB-SURVEYED",
                         window_start="2026-09-20T06:00:00Z",
                         window_end="2026-09-20T16:00:00Z")
    survey_plan(world, surveyed["id"])

    rows, meta = validate_paginated(
        api.list_lift_plans(DISPATCHER, params={"plan_status": "SURVEYED"}))

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert rows[0]["id"] == surveyed["id"]
    assert drafted["id"] not in [row["id"] for row in rows]


def test_configuring_onto_an_out_of_service_crane_reports_the_crane_gate(api):
    """PRD 3.1: "Pulling a machine out of service is a `SafetyManager` action that
    takes a `reason` and is legal from either `AVAILABLE` or `RESERVED`. It sets
    `out_of_service_flag` true and moves `status` to `OUT_OF_SERVICE`, and it launches
    a three-deep cascade."
    PRD 3.4: "The assigned crane may not be `OUT_OF_SERVICE`
    (`ERR_CRANE_OUT_OF_SERVICE`), and the two crew references must match their
    discriminators"

    Design: Corner/errors/configure_onto_an_out_of_service_crane_returns_the_crane_gate_error
    """
    world = build_standard_world()
    ctx = setup_surveyed_plan_with_gear(world, plan_overrides={"job_reference": "JOB-9600"})

    pulled = validate_success(api.crane_out_of_service(
        world["crane_id"], {"reason": "boom hoist brake service"}, SAFETY_MANAGER))
    assert pulled["status"] == "OUT_OF_SERVICE"

    body = configure_body(world, ctx["plan_version"])
    validate_error(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER),
                   ApiErrorId.ERR_CRANE_OUT_OF_SERVICE.value, 409)
    assert read_plan(ctx["plan_id"])["plan_status"] == "SURVEYED"


def test_stamping_a_review_whose_plan_is_not_pending_engineering_is_refused(api):
    """PRD 3.6: "`STAMP` is the consequential one and carries an extra gate: the
    owning plan must be sitting at `PENDING_ENGINEERING` at that moment, or the stamp
    is refused with `ERR_PLAN_NOT_PENDING_ENGINEERING`."
    PRD 3.6: "A new review is created at `UNDER_REVIEW` with `revision_round` at 1,
    `stamped_by_personnel_id` null, and both `change_request_note` and `decision_note`
    null."

    Design: Corner/errors/stamping_a_review_whose_plan_is_not_pending_engineering_returns_not_found_state_error
    """
    world = build_critical_world()
    plan = open_plan(world, job_reference="JOB-9601")
    surveyed = survey_plan(world, plan["id"])
    assert surveyed["plan_status"] == "SURVEYED"

    review = open_review(world, plan["id"], notes="premature analysis")
    assert review["status"] == "UNDER_REVIEW"

    validate_error(api.decide_engineering_review(
        review["id"], {"action": "STAMP", "note": "stamping early"},
        make_engineer_headers(world["eng_b_id"])),
        ApiErrorId.ERR_PLAN_NOT_PENDING_ENGINEERING.value, 409)

    stored = read_review(review["id"])
    assert stored["status"] == "UNDER_REVIEW"
    assert stored["stamped_by_personnel_id"] is None
    assert read_plan(plan["id"])["plan_status"] == "SURVEYED"


@pytest.mark.parametrize(
    "path,headers_key,expected_error",
    [
        ("/permits/00000000-0000-4000-8000-000000000001", "dispatcher_headers",
         ApiErrorId.ERR_PERMIT_NOT_FOUND.value),
        ("/standby-events/00000000-0000-4000-8000-000000000002", "safety_manager_headers",
         ApiErrorId.ERR_STANDBY_EVENT_NOT_FOUND.value),
        ("/invoices/00000000-0000-4000-8000-000000000003", "billing_clerk_headers",
         ApiErrorId.ERR_INVOICE_NOT_FOUND.value),
        ("/engineering-reviews/00000000-0000-4000-8000-000000000004", "engineer_headers",
         ApiErrorId.ERR_REVIEW_NOT_FOUND.value),
        ("/gear-assignments/00000000-0000-4000-8000-000000000005", "dispatcher_headers",
         ApiErrorId.ERR_GEAR_ASSIGNMENT_NOT_FOUND.value),
    ],
)
def test_each_collection_answers_with_its_own_not_found_code(api, path, headers_key,
                                                             expected_error):
    """PRD 2.7: "Every identifier embedded in the URL path resolves to a stored row,
    checked left to right. Depending on which segment fails, the code is one of
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_SITE_NOT_FOUND`, `ERR_CRANE_NOT_FOUND`,
    `ERR_PERSONNEL_NOT_FOUND`, `ERR_GEAR_NOT_FOUND`, `ERR_LIFT_PLAN_NOT_FOUND`,
    `ERR_GEAR_ASSIGNMENT_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`,
    `ERR_STANDBY_EVENT_NOT_FOUND` or `ERR_INVOICE_NOT_FOUND`, always with HTTP 404."
    PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/errors/unknown_ids_across_collections_return_their_domain_specific_not_found
    """
    resp = api.raw_get(path, TEST_USERS[headers_key])
    error = validate_error(resp, expected_error, 404)
    assert resp.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_a_dispatcher_may_not_approve_the_plan_they_configured(api):
    """PRD 2.1: "Once the role is recognized, it is checked against the list of roles
    authorized for the endpoint being called (see the table in §4); a role that does
    not appear there is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.1: "A `LiftDirector` signs off standard lifts and releases every plan to the
    field, but may not configure a plan, may not stamp an engineering analysis, and
    may not inspect gear."
    PRD 2.7: "The supplied role appears among the roles authorized for the endpoint
    being called — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every request."

    Design: Corner/roles/dispatcher_cannot_approve_a_lift_plan
    """
    world = build_standard_world()
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9700"})

    validate_error(api.approve_lift_plan(ctx["plan_id"], DISPATCHER),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert read_plan(ctx["plan_id"])["plan_status"] == "CONFIGURED"


def test_an_engineer_may_not_decide_on_their_own_analysis(api):
    """PRD 2.1: "Concretely, an engineer requesting changes on, stamping, or rejecting
    a review must have an `X-User-ID` different from that review's
    `author_personnel_id`, and an engineer resubmitting a review must have an
    `X-User-ID` equal to it. Either violation is `ERR_SEGREGATION_OF_DUTIES` (HTTP
    403)."
    PRD 3.6: "Deciding on a review is a **second** engineer's job, and this is the
    hardest-enforced segregation boundary in the system: the caller's `X-User-ID` must
    differ from the review's `author_personnel_id` on every decision, and must equal
    it on every resubmission."

    Design: Corner/roles/engineer_cannot_decide_on_the_review_they_authored
    """
    world = build_critical_world()
    ctx = setup_critical_plan_under_review(
        world, plan_overrides={"job_reference": "JOB-9701", "sail_area_sqft": 150.0})

    validate_error(api.decide_engineering_review(
        ctx["review_id"], {"action": "REQUEST_CHANGES", "note": "self review"},
        make_engineer_headers(world["eng_a_id"])),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    peer = validate_success(api.decide_engineering_review(
        ctx["review_id"], {"action": "REQUEST_CHANGES", "note": "peer review"},
        make_engineer_headers(world["eng_b_id"])))
    assert peer["status"] == "CHANGES_REQUESTED"

    validate_error(api.resubmit_engineering_review(
        ctx["review_id"], {"analysis_notes": "rev 2 by the wrong engineer"},
        make_engineer_headers(world["eng_b_id"])),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    assert read_review(ctx["review_id"])["revision_round"] == 1


def test_only_the_assigned_operator_may_drive_the_operational_dimension(api):
    """PRD 2.1: "When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the
    acting `Personnel` row; driving the operational dimension of a lift plan requires
    `X-User-ID` to equal that plan's `operator_id`, and any other operator attempting
    it is refused with `ERR_NOT_ASSIGNED_OPERATOR` (HTTP 403)."
    PRD 3.8: "Once released, the plan's operational dimension becomes the `Operator`'s
    to drive, and only the operator named in the plan's `operator_id` may drive it."

    Design: Corner/roles/operator_cannot_drive_a_plan_they_are_not_assigned_to
    """
    world = build_standard_world()
    stranger = new_operator(full_name="Nia Brant", certification_number="NCCCO-99001")
    ctx = setup_released_standard_plan(world, plan_overrides={"job_reference": "JOB-9702"})

    validate_error(api.set_field_status(
        ctx["plan_id"], {"action": "MOBILIZE"}, make_operator_headers(stranger["id"])),
        ApiErrorId.ERR_NOT_ASSIGNED_OPERATOR.value, 403)

    driven = validate_success(api.set_field_status(
        ctx["plan_id"], {"action": "MOBILIZE"}, make_operator_headers(world["op_id"])))
    assert driven["field_status"] == "MOBILIZED"
    assert driven["operator_id"] == world["op_id"]


def test_a_customer_may_read_only_its_own_account(api):
    """PRD 2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting `Customer` row; reading a customer record, reading an invoice, or disputing
    an invoice all require the target's `customer_id` (or, for the customer record
    itself, its own `id`) to equal `X-User-ID`. A mismatch is
    `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/roles/customer_cannot_read_another_customers_invoice
    """
    customer_a = new_customer(account_name="Customer A")
    customer_b = new_customer(account_name="Customer B")

    error = validate_error(
        api.get_customer(customer_b["id"], make_customer_headers(customer_a["id"])),
        ApiErrorId.ERR_CUSTOMER_SCOPE_VIOLATION.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value

    own = validate_success(
        api.get_customer(customer_a["id"], make_customer_headers(customer_a["id"])))
    assert own["account_name"] == "Customer A"


def test_a_safety_manager_may_not_draft_an_invoice(api):
    """PRD 2.1: "Once the role is recognized, it is checked against the list of roles
    authorized for the endpoint being called (see the table in §4); a role that does
    not appear there is refused with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD 2.1: "A `BillingClerk` owns the money surface: credit holds, invoice drafting,
    issuance, voiding and payment."
    PRD 2.7: "The supplied role appears among the roles authorized for the endpoint
    being called — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every request."

    Design: Corner/roles/safety_manager_cannot_create_an_invoice
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9703")

    error = validate_error(api.create_invoice(
        {"lift_plan_id": plan["id"], "billing_mode": "HOURLY", "on_site_hours": 8.0,
         "travel_hours": 1.0, "travel_miles": 10.0,
         "expected_lift_plan_version": plan["version"]}, SAFETY_MANAGER),
        ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_INVALID_PLAN_STATE.value

    _, meta = validate_paginated(
        api.list_invoices(BILLING_CLERK, params={"lift_plan_id": plan["id"]}))
    assert meta["total_count"] == 0
