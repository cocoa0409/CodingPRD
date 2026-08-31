"""Authentication, role authorisation, resource ownership and the 404 codes each
path segment answers with."""


from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_customer,
    agreement_payload,
    create_branch,
    make_branch_manager_headers,
    make_customer_headers,
    make_approver_headers,
    open_agreement,
    read_agreement,
    read_customer,
    read_agreement_unit,
    read_trailer,
    read_damage_assessment,
    setup_agreement_active,
    setup_agreement_pending_allocation,
    setup_pending_chargeback,
    setup_reference_data,
    trailer_type_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]

_NOT_FOUND_READS = [
    ("get_insurance_certificate", ApiErrorId.ERR_INSURANCE_CERTIFICATE_NOT_FOUND.value),
    ("get_agreement", ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value),
    ("get_agreement_unit", ApiErrorId.ERR_AGREEMENT_UNIT_NOT_FOUND.value),
    ("get_damage_assessment", ApiErrorId.ERR_DAMAGE_ASSESSMENT_NOT_FOUND.value),
    ("get_chargeback", ApiErrorId.ERR_CHARGEBACK_NOT_FOUND.value),
    ("get_relocation_order", ApiErrorId.ERR_RELOCATION_ORDER_NOT_FOUND.value),
    ("get_maintenance_event", ApiErrorId.ERR_MAINTENANCE_EVENT_NOT_FOUND.value),
]


def test_request_without_role_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of
    those five strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.9: "Header authentication. Both `X-User-ID` and `X-User-Role` present,
    and the role one of the five declared names, or `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/request_without_x_user_role_header_returns_unauthenticated
    """
    create_branch()

    response = api.raw_get(f"/branches/{NON_EXISTENT_UUID}",
                           headers={"Content-Type": "application/json"})
    error = validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert error["error_id"] != ApiErrorId.ERR_BRANCH_NOT_FOUND.value, (
        "header authentication runs before path existence"
    )


def test_pagination_limit_above_the_maximum_is_a_malformed_request(api):
    """PRD §2.3: "A `limit` outside the range of 1 through 100, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 422)."

    Design: Corner/validations/pagination_limit_above_max_returns_invalid_request
    """
    create_branch()
    validate_error(
        api.list_branches(ADMIN, params={"limit": 101, "offset": 0}),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


def test_lessee_cannot_submit_another_lessees_contract(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting `Customer`; ownership checks on any resource that references a
    `Customer` compare the resource's customer-bearing field to `X-User-ID`, so a
    `Customer` may act only on agreements whose `customer_id` equals `X-User-ID`
    and on chargebacks whose `customer_id` equals `X-User-ID`."
    PRD §2.1: "A mutation by an entity-backed caller against a resource it does not
    own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/validations/customer_cannot_submit_another_customers_agreement
    """
    ctx = setup_reference_data()
    add_customer(ctx, "customer_two", legal_name="Second Fleet Co",
                 dot_number="DOT-222", credit_tier="A", with_certificate=False)

    agreement = open_agreement(ctx, as_customer=True)

    response = api.submit_agreement(agreement["id"], ctx["customer_two_headers"])
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    stored = read_agreement(agreement["id"])
    assert stored["status"] == "DRAFT"
    assert stored["version"] == 1


def test_branch_manager_cannot_accept_a_return_into_a_foreign_yard(api):
    """PRD §2.1: "Concretely, a `BranchManager` may act on an agreement only when
    `X-User-ID` equals that agreement's `branch_id`; may accept a unit back only
    when `X-User-ID` equals the `return_branch_id` supplied in the return request;
    and may accept an inbound repositioning move only when `X-User-ID` equals that
    order's `destination_branch_id`."

    Design: Corner/validations/branch_manager_cannot_accept_a_return_at_a_yard_it_does_not_manage
    """
    ctx = setup_reference_data()
    from test_helpers import add_east_branch
    add_east_branch(ctx)
    scn = setup_agreement_active(ctx=ctx)

    response = api.return_agreement_unit(
        scn["unit_id"],
        {"return_branch_id": scn["branch_id"], "return_hub_miles": 42000,
         "return_date": "2026-09-03"},
        make_branch_manager_headers(scn["east_branch_id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)

    assert read_agreement_unit(scn["unit_id"])["status"] == "OUT"
    trailer = read_trailer(scn["trailer_id"])
    assert trailer["availability_status"] == "ON_RENT"
    assert trailer["hub_miles"] == 41000


def test_inspector_cannot_run_the_allocation_selector(api):
    """PRD §2.9: "Role authorisation. The caller's role listed for the endpoint, or
    `ERR_FORBIDDEN_ROLE`."
    PRD §3.5: "There are two ways to commit equipment, and both are available to a
    `FleetAdmin` or to the originating yard's `BranchManager`, and both demand that
    the contract be in `PENDING_ALLOCATION` — any other status is rejected with
    `ERR_AGREEMENT_NOT_PENDING_ALLOCATION`."

    Design: Corner/rbac/inspector_cannot_allocate_an_agreement
    """
    scn = setup_agreement_pending_allocation()

    response = api.allocate_agreement(
        scn["agreement_id"],
        {"expected_agreement_version": scn["agreement_version"]},
        INSPECTOR,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    stored = read_agreement(scn["agreement_id"])
    assert stored["status"] == "PENDING_ALLOCATION"
    assert stored["allocated_unit_count"] == 0
    assert read_trailer(scn["trailer_id"])["availability_status"] == "AVAILABLE"


def test_branch_manager_cannot_register_an_equipment_class(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among
    the roles authorised for the endpoint (see the endpoint table in section 4),
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "`FleetAdmin` is corporate fleet operations: it owns the reference
    data, pricing publication, settlement and cash application."

    Design: Corner/rbac/branch_manager_cannot_create_a_trailer_type
    """
    branch = create_branch()

    response = api.create_trailer_type(
        trailer_type_payload(code="REEFER_53", description="53ft reefer",
                             base_daily_rate_cents=7200, base_monthly_rate_cents=150000,
                             residual_floor_cents=900000,
                             required_physical_damage_limit_cents=5000000),
        make_branch_manager_headers(branch["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    rows, _ = validate_paginated(api.list_trailer_types(ADMIN, params={"limit": 100}))
    assert [t for t in rows if t["code"] == "REEFER_53"] == []


def test_approver_cannot_adjudicate_a_chargeback_they_assessed(api):
    """PRD §2.1: "Because the same human being may hold both an inspector badge and
    an approver badge, the API enforces segregation of duties on identifier
    equality: an approver whose `X-User-ID` equals the `assessor_user_id` of the
    assessment behind a chargeback may neither approve nor waive that chargeback,
    and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "Approval records `approver_user_id` — which is null for as long as a
    chargeback sits in `PENDING` or `DISPUTED`, and is written only by an approval
    or a waiver — moves the linked assessment `SUBMITTED → APPROVED`, leaves the
    amount counted in `outstanding_chargeback_cents`, leaves the assessment's
    damage points counted against the trailer, and increments the chargeback's
    `version` by 1."

    Design: Corner/rbac/approver_cannot_adjudicate_a_chargeback_they_authored
    """
    scn = setup_pending_chargeback(inspector_user_id="insp-1")
    assert scn["chargeback_amount"] == 108000

    blocked = api.approve_chargeback(scn["chargeback_id"], make_approver_headers("insp-1"))
    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert read_damage_assessment(scn["assessment_id"])["assessor_user_id"] == "insp-1"

    allowed = validate_success(
        api.approve_chargeback(scn["chargeback_id"], make_approver_headers("appr-1"))
    )
    assert allowed["status"] == "APPROVED"
    assert allowed["approver_user_id"] == "appr-1"
    assert read_damage_assessment(scn["assessment_id"])["status"] == "APPROVED"


def test_lessee_disputes_its_own_chargeback_without_moving_the_balance(api):
    """PRD §3.8: "The lessee may dispute a chargeback, moving it `PENDING →
    DISPUTED` and recording the supplied `dispute_reason`."
    PRD §3.8: "Disputing changes no money: the amount stays counted in
    `outstanding_chargeback_cents`."

    Design: Corner/rbac/customer_may_dispute_its_own_chargeback_without_moving_the_balance
    """
    scn = setup_pending_chargeback()
    before = read_customer(scn["customer_id"])["outstanding_chargeback_cents"]
    assert before == 108000

    chargeback = validate_success(
        api.dispute_chargeback(
            scn["chargeback_id"],
            {"dispute_reason": "damage was documented at checkout"},
            make_customer_headers(scn["customer_id"]),
        )
    )
    assert chargeback["status"] == "DISPUTED"
    assert chargeback["dispute_reason"] == "damage was documented at checkout"

    after = read_customer(scn["customer_id"])["outstanding_chargeback_cents"]
    assert after == 108000, "a dispute leaves the outstanding balance where it stood"


def test_opening_a_contract_for_an_unknown_lessee_reports_customer_not_found(api):
    """PRD §2.8: "Every identifier in a payload — the `trailer_type_id`,
    `home_branch_id`, `branch_id`, `customer_id`, `trailer_id`,
    `destination_branch_id` or `supersedes_assessment_id` a caller supplies — must
    resolve to an existing record, and an unresolvable one is rejected with that
    resource type's 404 code before any business rule runs."

    Design: Corner/entities/create_agreement_with_unknown_customer_returns_customer_not_found
    """
    ctx = setup_reference_data()

    response = api.create_agreement(
        agreement_payload(NON_EXISTENT_UUID, ctx["branch_id"], ctx["trailer_type_id"]),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)

    rows, meta = validate_paginated(api.list_agreements(ADMIN, params={"limit": 100}))
    assert meta["total_count"] == 0


def test_reading_an_unknown_certificate_reports_certificate_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type"

    Design: Corner/errors/get_insurance_certificate_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_insurance_certificate(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_INSURANCE_CERTIFICATE_NOT_FOUND.value,
    )


def test_reading_an_unknown_contract_reports_agreement_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type"

    Design: Corner/errors/get_agreement_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_agreement(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_AGREEMENT_NOT_FOUND.value,
    )


def test_reading_an_unknown_contract_unit_line_reports_agreement_unit_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type"

    Design: Corner/errors/get_agreement_unit_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_agreement_unit(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_AGREEMENT_UNIT_NOT_FOUND.value,
    )


def test_reading_an_unknown_damage_assessment_reports_assessment_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type"

    Design: Corner/errors/get_damage_assessment_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_damage_assessment(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_DAMAGE_ASSESSMENT_NOT_FOUND.value,
    )


def test_reading_an_unknown_chargeback_reports_chargeback_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type"

    Design: Corner/errors/get_chargeback_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_chargeback(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_CHARGEBACK_NOT_FOUND.value,
    )


def test_reading_an_unknown_repositioning_order_reports_order_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type"

    Design: Corner/errors/get_relocation_order_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_relocation_order(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_RELOCATION_ORDER_NOT_FOUND.value,
    )


def test_reading_an_unknown_shop_event_reports_maintenance_event_not_found(api):
    """PRD §2.8: "For every such request the server resolves the path segments
    strictly left to right and rejects on the first identifier that does not
    resolve, with the 404 code belonging to that segment's resource type"

    Design: Corner/errors/get_maintenance_event_by_unknown_id_returns_not_found
    """
    create_branch()
    validate_error(
        api.get_maintenance_event(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_MAINTENANCE_EVENT_NOT_FOUND.value,
    )
