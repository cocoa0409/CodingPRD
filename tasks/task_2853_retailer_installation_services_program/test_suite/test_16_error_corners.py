"""Error-identifier edges: sibling not-found codes, the two identity failures, the
codes a cancelled project produces, two separate assignment refusals, one shape rule
with three violations, the invoice gates and the removal ladder.

Every test names the single identifier the documented evaluation order licenses and
then shows the store is unchanged.
"""

import pytest

from test_helpers import (
    NETWORK_MANAGER,
    PROGRAM_ADMIN,
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    ApiErrorId,
    AssignmentStatus,
    ChangeOrderOrigin,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    PermitStatus,
    Role,
    UnitKind,
    assert_committed_minutes,
    assert_deposit_buckets,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_score,
    assert_version,
    build_user_headers,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_customer_headers,
    make_installer_headers,
    validate_error,
    validate_paginated,
)

QUOTED = 171020
DEPOSIT = 51306

UNKNOWN_CATEGORY = "00000000-0000-4000-8000-000000000001"
UNKNOWN_CREDENTIAL = "00000000-0000-4000-8000-000000000002"
UNKNOWN_CUSTOMER = "00000000-0000-4000-8000-000000000003"
UNKNOWN_MEASUREMENT = "00000000-0000-4000-8000-000000000004"
UNKNOWN_CHANGE_ORDER = "00000000-0000-4000-8000-000000000005"
UNKNOWN_DELIVERY = "00000000-0000-4000-8000-000000000006"
UNKNOWN_ASSIGNMENT = "00000000-0000-4000-8000-000000000007"
UNKNOWN_PUNCH_ITEM = "00000000-0000-4000-8000-000000000008"
UNKNOWN_CLAIM = "00000000-0000-4000-8000-000000000009"


@pytest.mark.parametrize(
    "read,expected_error",
    [
        (lambda api: api.get_service_category(UNKNOWN_CATEGORY, PROGRAM_ADMIN),
         ApiErrorId.SERVICE_CATEGORY_NOT_FOUND),
        (lambda api: api.get_credential(UNKNOWN_CREDENTIAL, NETWORK_MANAGER),
         ApiErrorId.INSTALLER_CREDENTIAL_NOT_FOUND),
        (lambda api: api.get_customer(UNKNOWN_CUSTOMER, PROGRAM_ADMIN),
         ApiErrorId.CUSTOMER_NOT_FOUND),
        (lambda api: api.get_measurement(UNKNOWN_MEASUREMENT, PROJECT_COORDINATOR),
         ApiErrorId.MEASUREMENT_NOT_FOUND),
        (lambda api: api.get_change_order(UNKNOWN_CHANGE_ORDER, PROJECT_COORDINATOR),
         ApiErrorId.CHANGE_ORDER_NOT_FOUND),
        (lambda api: api.get_material_delivery(UNKNOWN_DELIVERY, PROJECT_COORDINATOR),
         ApiErrorId.MATERIAL_DELIVERY_NOT_FOUND),
        (lambda api: api.get_assignment(UNKNOWN_ASSIGNMENT, PROJECT_COORDINATOR),
         ApiErrorId.INSTALLER_ASSIGNMENT_NOT_FOUND),
        (lambda api: api.get_punch_list_item(UNKNOWN_PUNCH_ITEM, PROJECT_COORDINATOR),
         ApiErrorId.PUNCH_LIST_ITEM_NOT_FOUND),
        (lambda api: api.get_warranty_claim(UNKNOWN_CLAIM, SERVICE_MANAGER),
         ApiErrorId.WARRANTY_CLAIM_NOT_FOUND),
    ],
)
def test_each_read_by_id_carries_its_own_not_found_code(api, read, expected_error):
    """Nine sibling reads against an empty store each answer with their own entity's
    not-found identifier rather than one shared code.

    PRD 2.8 rank 6: "Every identifier appearing in the URL path resolves to a stored
    row, checked left to right — otherwise that entity's not-found code (404)."

    Design: Corner/errors/every_entity_has_its_own_not_found_code_on_a_bare_read
    """
    body = validate_error(read(api), expected_error)
    assert body["message"], "an error body must carry a human-readable message"


def _two_households(api):
    """Two households on one county, and a sold project belonging to the first of
    them with its deposit still unpaid."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    other = fx.create_customer(api, base["jurisdiction"]["id"],
                               f.second_customer_payload(base["jurisdiction"]["id"]))
    project = fx.sell_project(api, base, estimated_units=420.00)
    assert_money(project["deposit_required_cents"], DEPOSIT,
                 "deposit_required_cents")
    base["other_customer"] = other
    base["project"] = project
    return base


def test_an_empty_identity_header_is_an_authentication_failure(api):
    """An `X-User-ID` sent as an empty string counts as absent, so the request dies at
    the very first check with a 401 rather than anywhere later.

    PRD 2.1: "If either header is absent or present but empty, the request is rejected
    with `ERR_MISSING_AUTH_HEADERS` and HTTP 401."

    Design: Corner/errors/empty_identity_header_and_foreign_ownership_are_different_failures
    """
    ctx = _two_households(api)
    project = ctx["project"]

    anonymous = api.pay_deposit(project["id"], f.deposit_payload(DEPOSIT),
                               build_user_headers("", Role.CUSTOMER))
    validate_error(anonymous, ApiErrorId.MISSING_AUTH_HEADERS)

    empty_role = api.pay_deposit(project["id"], f.deposit_payload(DEPOSIT),
                                build_user_headers(ctx["customer"]["id"], ""))
    validate_error(empty_role, ApiErrorId.MISSING_AUTH_HEADERS)

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, financial=FinancialStatus.QUOTED)
    assert_money(after["deposit_paid_cents"], 0, "deposit_paid_cents")
    assert_version(after, project["version"], "the project")


def test_a_stranger_with_a_perfect_payload_fails_on_ownership(api):
    """The second household's identity is well formed and its role is on the endpoint's
    list, so the refusal is about ownership — and the owner's identical payload is then
    accepted.

    PRD 2.1: "When the role itself is permitted at the endpoint but the acting
    `X-User-ID` does not own the resource, the answer is `ERR_NOT_RESOURCE_OWNER` with
    HTTP 403 — never `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/errors/empty_identity_header_and_foreign_ownership_are_different_failures
    """
    ctx = _two_households(api)
    project = ctx["project"]

    stranger = api.pay_deposit(
        project["id"], f.deposit_payload(DEPOSIT),
        make_customer_headers(ctx["other_customer"]["id"]))
    validate_error(stranger, ApiErrorId.NOT_RESOURCE_OWNER)

    unchanged = fx.read_project(api, project["id"])
    assert_money(unchanged["deposit_paid_cents"], 0, "deposit_paid_cents")
    assert_version(unchanged, project["version"], "the project")

    paid = fx.pay_deposit(api, project, ctx["customer"]["id"])
    assert_project_dimensions(paid, financial=FinancialStatus.DEPOSIT_HELD)
    assert_money(paid["deposit_held_cents"], DEPOSIT, "deposit_held_cents")


def _cancelled_project(api):
    """A sale cancelled before any money moved: the settlement runs against a zero
    balance and the project sits at CANCELLED with every bucket empty."""
    base = fx.program_baseline(api, f.measured_never_permit_category_payload(),
                               f.plain_jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.MEASURE_PENDING)
    base["project"] = fx.cancel_project(api, project["id"], PROJECT_COORDINATOR,
                                        "Customer withdrew before measurement")
    return base


def test_a_cancelled_project_refuses_children_and_a_second_cancellation(api):
    """Planning material against a cancelled project is refused for the project's state,
    and cancelling it again answers the cancellation-specific code rather than the
    generic state code.

    PRD 3.8: "And while a project is `CANCELLED`, any attempt to write one of its
    children — booking a measurement, raising a change order, holding an assignment,
    planning a delivery or recording a quality inspection — is refused with
    `ERR_PROJECT_CANCELLED`."

    PRD 2.8 rank 12: "Consequently an un-cancellable project answers
    `ERR_NOT_CANCELLABLE`, never `ERR_INVALID_STATE`."

    Design: Corner/errors/cancelled_project_blocks_children_recancellation_and_late_reinstatement
    """
    ctx = _cancelled_project(api)
    project = ctx["project"]
    # A zero-held cancellation still lands in REFUNDED.
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.REFUNDED)

    child = api.create_material_delivery(
        project["id"],
        f.delivery_payload("2026-08-19T09:00:00.000Z", "2026-08-20T09:00:00.000Z",
                           sku_count=4, material_cost_cents=250000),
        PROJECT_COORDINATOR)
    validate_error(child, ApiErrorId.PROJECT_CANCELLED)

    rows, meta = validate_paginated(
        api.list_project_material_deliveries(project["id"], PROJECT_COORDINATOR)
    )
    assert rows == []
    assert meta["total_count"] == 0

    again = api.cancel_project(project["id"], f.cancel_payload("Second attempt"),
                              PROJECT_COORDINATOR)
    validate_error(again, ApiErrorId.NOT_CANCELLABLE)

    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "the cancelled project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.REFUNDED)


def test_a_reinstatement_at_exactly_seventy_two_hours_is_too_late(api):
    """The reinstatement window is strictly less than 72 hours after the cancellation,
    so a request made on the boundary is refused.

    PRD 3.8: "Three conditions apply: the project's `fulfillment_status` must be
    `CANCELLED`; the supplied version must match the project's current `version`, or the
    answer is `ERR_STALE_PROJECT_VERSION`; and the logical clock must be **strictly**
    less than 72 hours after `cancelled_at`, or the answer is
    `ERR_REINSTATE_WINDOW_CLOSED` — exactly 72 hours is too late."

    Design: Corner/errors/cancelled_project_blocks_children_recancellation_and_late_reinstatement
    """
    ctx = _cancelled_project(api)
    project = ctx["project"]
    assert_instant(project["cancelled_at"], "2026-08-01T00:00:00.000Z",
                   "cancelled_at")

    report = fx.set_clock(api, "2026-08-04T00:00:00.000Z")
    assert_instant(report["current_utc"], "2026-08-04T00:00:00.000Z", "current_utc")

    response = api.reinstate_project(
        project["id"],
        f.reinstate_payload(project["version"],
                            note="Customer changed their mind"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.REINSTATE_WINDOW_CLOSED)

    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "the cancelled project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.REFUNDED)
    assert after["cancel_reason"] == "Customer withdrew before measurement"


LONG_INSURANCE = "2028-12-31T00:00:00.000Z"
LONG_LICENCE = "2028-12-31T00:00:00.000Z"
FUTURE_WINDOW = ("2027-09-01T08:00:00.000Z", "2027-09-01T16:00:00.000Z")


def _two_firms_one_unpaid_sale(api):
    """Two admitted firms differing only in the age of their background check, and an
    undeposited sale for them to be booked against."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    jurisdiction_id = base["jurisdiction"]["id"]
    base["project"] = fx.sell_project(
        api, base, estimated_units=420.00,
        requested_install_date="2027-09-01T13:00:00.000Z")
    assert_project_dimensions(base["project"], financial=FinancialStatus.QUOTED)

    stale = fx.activated_installer(
        api, jurisdiction_id,
        installer_payload=f.installer_payload(
            legal_name="Stalecheck Flooring LLC",
            contact_email="ops@stalecheck.example",
            insurance_expires_on=LONG_INSURANCE),
        credential_payload=f.credential_payload(jurisdiction_id,
                                                license_number="FL-11111",
                                                license_expires_on=LONG_LICENCE),
        background_completed_at="2026-07-15T00:00:00.000Z")
    assert stale["installer"]["status"] == InstallerStatus.ACTIVE

    # 2027-08-01 is 382 whole days after that check, and no credential expires until
    # 2028, so the jump itself changes nothing.
    report = fx.set_clock(api, "2027-08-01T00:00:00.000Z")
    assert report["credentials_expired_count"] == 0
    assert report["installers_suspended_count"] == 0

    fresh = fx.activated_installer(
        api, jurisdiction_id,
        installer_payload=f.installer_payload(
            legal_name="Freshcheck Flooring LLC",
            contact_email="ops@freshcheck.example",
            insurance_expires_on=LONG_INSURANCE),
        credential_payload=f.credential_payload(jurisdiction_id,
                                                license_number="FL-22222",
                                                license_expires_on=LONG_LICENCE),
        background_completed_at="2027-07-15T00:00:00.000Z")
    assert fresh["installer"]["status"] == InstallerStatus.ACTIVE

    base["stale_installer"] = stale["installer"]
    base["fresh_installer"] = fresh["installer"]
    return base


def test_a_stale_background_check_answers_before_the_unpaid_deposit(api):
    """The firm with the aged check dies on the compliance floor; the compliant firm
    reaches the fiscal check on the very same unpaid project and dies there.

    PRD 2.8 rank 18: "`background_check_result` is `PASS` and
    `background_check_completed_at` is no older than the jurisdiction's
    `background_check_recency_days` whole days measured from the logical clock, inclusive
    — otherwise `ERR_BACKGROUND_CHECK_STALE` (409)."

    PRD 2.8 rank 35: "An assignment may be created only while the project's
    `financial_status` is `DEPOSIT_HELD`, `BALANCE_DUE` or `SETTLED` — otherwise
    `ERR_DEPOSIT_NOT_HELD` (409)."

    Design: Corner/errors/stale_background_check_and_unheld_deposit_are_separate_assignment_refusals
    """
    ctx = _two_firms_one_unpaid_sale(api)
    project = ctx["project"]

    aged = api.create_assignment(
        f.assignment_payload(project["id"], ctx["stale_installer"]["id"],
                             project["version"],
                             window_start=FUTURE_WINDOW[0],
                             window_end=FUTURE_WINDOW[1]),
        PROJECT_COORDINATOR)
    validate_error(aged, ApiErrorId.BACKGROUND_CHECK_STALE)

    compliant = api.create_assignment(
        f.assignment_payload(project["id"], ctx["fresh_installer"]["id"],
                             project["version"],
                             window_start=FUTURE_WINDOW[0],
                             window_end=FUTURE_WINDOW[1]),
        PROJECT_COORDINATOR)
    validate_error(compliant, ApiErrorId.DEPOSIT_NOT_HELD)

    for installer_id in (ctx["stale_installer"]["id"], ctx["fresh_installer"]["id"]):
        assert_committed_minutes(fx.read_installer(api, installer_id), 0)
    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "the undeposited project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.QUOTED)


def test_paying_the_deposit_unblocks_only_the_compliant_firm(api):
    """Once the money is held the compliant firm's identical request is accepted, while
    the aged check still refuses the other firm.

    PRD 3.6: "A successful hold creates the assignment at `status` `HELD`, increases the
    installer's `committed_minutes` by `duration_minutes`, drives the project
    `MEASURED → SCHEDULED`, and increments both the project's and the installer's
    `version`."

    Design: Corner/errors/stale_background_check_and_unheld_deposit_are_separate_assignment_refusals
    """
    ctx = _two_firms_one_unpaid_sale(api)
    project = ctx["project"]

    paid = fx.pay_deposit(api, project, ctx["customer"]["id"])
    assert_project_dimensions(paid, financial=FinancialStatus.DEPOSIT_HELD)
    assert_money(paid["deposit_held_cents"], DEPOSIT, "deposit_held_cents")

    still_stale = api.create_assignment(
        f.assignment_payload(project["id"], ctx["stale_installer"]["id"],
                             paid["version"],
                             window_start=FUTURE_WINDOW[0],
                             window_end=FUTURE_WINDOW[1]),
        PROJECT_COORDINATOR)
    validate_error(still_stale, ApiErrorId.BACKGROUND_CHECK_STALE)

    assignment = fx.hold_assignment(api, project["id"],
                                    ctx["fresh_installer"]["id"], paid["version"],
                                    window_start=FUTURE_WINDOW[0],
                                    window_end=FUTURE_WINDOW[1])
    assert assignment["status"] == AssignmentStatus.HELD
    assert assignment["duration_minutes"] == 480
    assert_committed_minutes(fx.read_installer(api, ctx["fresh_installer"]["id"]),
                             480)
    assert_committed_minutes(fx.read_installer(api, ctx["stale_installer"]["id"]), 0)
    assert_project_dimensions(fx.read_project(api, project["id"]),
                              fulfillment=FulfillmentStatus.SCHEDULED)


ELEVEN_TRIM_LINES = [f.line(UnitKind.TRIM_LINEAR_FT, 1.00)] * 11


def _scopable_project(api):
    """A sale sitting at MEASURED, where a well-shaped change order would be accepted."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    base["project"] = fx.sell_project(api, base, estimated_units=420.00)
    assert_project_dimensions(base["project"],
                              fulfillment=FulfillmentStatus.MEASURED)
    return base


@pytest.mark.parametrize(
    "origin,lines",
    [
        (ChangeOrderOrigin.CUSTOMER_REQUEST, []),
        (ChangeOrderOrigin.CUSTOMER_REQUEST, ELEVEN_TRIM_LINES),
        (ChangeOrderOrigin.MEASUREMENT_VARIANCE, []),
    ],
)
def test_three_different_shape_violations_share_one_identifier(api, origin, lines):
    """No lines, eleven lines and a server-only origin are all the same shape failure,
    and the third is a legal enum member so it is not a type failure.

    PRD 3.4: "The `origin` must be `CUSTOMER_REQUEST` or `SITE_CONDITION`: a client that
    submits `MEASUREMENT_VARIANCE` is refused with `ERR_CHANGE_ORDER_SHAPE`, because only
    the measurement cascade may mint that origin."

    PRD 3.4: "Symmetrically, a `MEASUREMENT_VARIANCE` change order must carry an empty
    `lines` array while every client-raised change order must carry between one and ten
    entries; either violation is the same `ERR_CHANGE_ORDER_SHAPE`."

    Design: Corner/errors/change_order_shape_is_policed_against_its_origin
    """
    ctx = _scopable_project(api)
    project = ctx["project"]

    response = api.create_change_order(
        f.change_order_payload(project["id"], project["version"], lines=lines,
                              origin=origin),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.CHANGE_ORDER_SHAPE)


def test_no_change_order_survives_a_shape_failure(api):
    """Three refused attempts leave the project with no change order at all and its
    version where it started.

    PRD 2.8 rank 28: "A change order's shape matches its `origin` — otherwise
    `ERR_CHANGE_ORDER_SHAPE` (422), on change-order creation and change-order
    submission."

    Design: Corner/errors/change_order_shape_is_policed_against_its_origin
    """
    ctx = _scopable_project(api)
    project = ctx["project"]

    for origin, lines in ((ChangeOrderOrigin.CUSTOMER_REQUEST, []),
                          (ChangeOrderOrigin.CUSTOMER_REQUEST, ELEVEN_TRIM_LINES),
                          (ChangeOrderOrigin.MEASUREMENT_VARIANCE, [])):
        validate_error(
            api.create_change_order(
                f.change_order_payload(project["id"], project["version"],
                                      lines=lines, origin=origin),
                PROJECT_COORDINATOR),
            ApiErrorId.CHANGE_ORDER_SHAPE,
        )

    rows, meta = validate_paginated(
        api.list_project_change_orders(project["id"], PROJECT_COORDINATOR)
    )
    assert rows == []
    assert meta["total_count"] == 0

    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "the project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.QUOTED)
    assert_money(after["change_order_upcharge_cents"], 0,
                 "change_order_upcharge_cents")


PERMIT_FEE = 25000
TOTAL_DUE = 196020
BALANCE = 144714


def _invoiced_project(api):
    """A finished install in a county that inspects: the invoice carries the frozen
    labour and the passed-through permit fee, and the permit is only ISSUED."""
    base = fx.program_baseline(api, f.quick_category_payload(),
                               f.inspected_jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00,
                              site_address="6 Inspector Row",
                              requested_install_date="2026-08-21T09:00:00.000Z")
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    project = fx.pay_deposit(api, project, base["customer"]["id"])

    get_success_data(api.apply_permit(project["id"],
                                     f.permit_apply_payload("PA-6001"),
                                     PROJECT_COORDINATOR))
    project = get_success_data(
        api.issue_permit(project["id"],
                         f.permit_issue_payload(PERMIT_FEE,
                                                "2026-08-02T00:00:00.000Z"),
                         PROJECT_COORDINATOR)
    )
    assert_money(project["permit_fee_cents_billed"], PERMIT_FEE,
                 "permit_fee_cents_billed")

    network = fx.activated_installer(api, base["jurisdiction"]["id"])
    installer_headers = make_installer_headers(network["installer"]["id"])
    fx.plan_delivery(api, project["id"],
                     f.delivery_payload("2026-08-19T09:00:00.000Z",
                                        "2026-08-20T09:00:00.000Z",
                                        sku_count=4, material_cost_cents=250000))
    assignment = fx.hold_assignment(api, project["id"],
                                    network["installer"]["id"],
                                    fx.project_version(api, project["id"]),
                                    window_start="2026-08-21T09:00:00.000Z",
                                    window_end="2026-08-21T17:00:00.000Z")
    confirmed = get_success_data(api.confirm_assignment(assignment["id"],
                                                        PROJECT_COORDINATOR))
    assert confirmed["status"] == AssignmentStatus.CONFIRMED

    fx.set_clock(api, "2026-08-21T09:30:00.000Z")
    get_success_data(api.start_assignment(assignment["id"], installer_headers))
    fx.set_clock(api, "2026-08-21T17:00:00.000Z")
    finished = get_success_data(
        api.complete_assignment(assignment["id"],
                                f.completion_payload("2026-08-21T16:45:00.000Z"),
                                installer_headers)
    )
    assert finished["on_time"] is True

    base.update(network)
    base["assignment"] = finished
    base["project"] = fx.read_project(api, project["id"])
    return base


def test_a_balance_one_cent_short_of_the_invoice_is_refused(api):
    """The invoice is the frozen labour plus the billed permit fee less the applied
    deposit, and a payment one cent under it is refused outright.

    PRD 2.8 rank 36: "A balance payment's `amount_cents` equals the project's
    `balance_due_cents` exactly, and `balance_due_cents` is greater than zero —
    otherwise `ERR_BALANCE_AMOUNT_MISMATCH` (422)."

    Design: Corner/errors/completed_install_gates_balance_closure_and_warranty_filing
    """
    ctx = _invoiced_project(api)
    project = ctx["project"]

    assert_money(project["final_labor_cents"], QUOTED, "final_labor_cents")
    assert_money(project["total_due_cents"], TOTAL_DUE, "total_due_cents")
    assert_money(project["deposit_applied_cents"], DEPOSIT,
                 "deposit_applied_cents")
    assert_money(project["balance_due_cents"], BALANCE, "balance_due_cents")
    assert_project_dimensions(project,
                              fulfillment=FulfillmentStatus.INSTALL_COMPLETE,
                              financial=FinancialStatus.BALANCE_DUE,
                              permit=PermitStatus.ISSUED)

    short = api.pay_balance(project["id"], f.balance_payload(BALANCE - 1),
                           make_customer_headers(ctx["customer"]["id"]))
    validate_error(short, ApiErrorId.BALANCE_AMOUNT_MISMATCH)

    after = fx.read_project(api, project["id"])
    assert_money(after["balance_due_cents"], BALANCE, "balance_due_cents")
    assert_project_dimensions(after, financial=FinancialStatus.BALANCE_DUE)


def test_a_second_payment_against_a_settled_invoice_is_the_same_refusal(api):
    """The exact amount settles the invoice, and the identical payment repeated is then
    refused because the balance is no longer above zero.

    PRD 3.6: "The household pays the remainder by supplying `amount_cents`, which must
    equal `balance_due_cents` **exactly** and which requires `balance_due_cents` to be
    greater than zero; any other figure, or a payment against a zero balance, is
    `ERR_BALANCE_AMOUNT_MISMATCH`."

    Design: Corner/errors/completed_install_gates_balance_closure_and_warranty_filing
    """
    ctx = _invoiced_project(api)
    project = ctx["project"]
    customer_headers = make_customer_headers(ctx["customer"]["id"])

    settled = get_success_data(
        api.pay_balance(project["id"], f.balance_payload(BALANCE),
                        customer_headers)
    )
    assert_money(settled["balance_due_cents"], 0, "balance_due_cents")
    assert_project_dimensions(settled, financial=FinancialStatus.SETTLED)
    # A balance payment moves no deposit bucket, so the conservation identity is
    # exactly what the waterfall left behind.
    assert_deposit_buckets(settled, DEPOSIT, 0, DEPOSIT, 0, 0)

    again = api.pay_balance(project["id"], f.balance_payload(BALANCE),
                           customer_headers)
    validate_error(again, ApiErrorId.BALANCE_AMOUNT_MISMATCH)

    after = fx.read_project(api, project["id"])
    assert_money(after["balance_due_cents"], 0, "balance_due_cents")
    assert_deposit_buckets(after, DEPOSIT, 0, DEPOSIT, 0, 0)


def test_a_settled_invoice_still_cannot_close_or_carry_a_warranty_claim(api):
    """With the money settled the project still cannot close, because the county has not
    passed the permit — and no warranty claim can be filed until it does close.

    PRD 2.8 rank 22: "A project whose jurisdiction has `inspection_required` true and
    whose `permit_responsibility` is not `NOT_REQUIRED` may not be closed until its
    `permit_status` is `CLOSED` — otherwise `ERR_INSPECTION_NOT_PASSED` (409), on project
    closing."

    PRD 2.8 rank 31: "A warranty claim has `claim_type` of `LABOR_DEFECT` and is filed no
    later than the project's `closed_at` plus 365 whole days, inclusive — otherwise
    `ERR_WARRANTY_EXPIRED` (409)."

    Design: Corner/errors/completed_install_gates_balance_closure_and_warranty_filing
    """
    ctx = _invoiced_project(api)
    project = ctx["project"]
    customer_headers = make_customer_headers(ctx["customer"]["id"])

    early_claim = api.create_warranty_claim(
        f.warranty_claim_payload(project["id"], "LABOR_DEFECT",
                                 "Seam lifting at the hallway threshold"),
        customer_headers)
    validate_error(early_claim, ApiErrorId.WARRANTY_EXPIRED)

    get_success_data(api.pay_balance(project["id"], f.balance_payload(BALANCE),
                                     customer_headers))

    closure = api.close_project(project["id"], PROJECT_COORDINATOR)
    validate_error(closure, ApiErrorId.INSPECTION_NOT_PASSED)

    material_claim = api.create_warranty_claim(
        f.warranty_claim_payload(project["id"], "MATERIAL_DEFECT",
                                 "Planks arrived warped"),
        customer_headers)
    validate_error(material_claim, ApiErrorId.WARRANTY_EXPIRED)

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after,
                              fulfillment=FulfillmentStatus.INSTALL_COMPLETE,
                              financial=FinancialStatus.SETTLED,
                              permit=PermitStatus.ISSUED)
    assert after["closed_at"] is None


def test_a_stale_installer_version_answers_before_the_eligibility_rule(api):
    """A removal request one version ahead of the truth is refused on the concurrency
    token, even though the eligibility rule would have refused it too.

    PRD 2.8 rank 11: "`expected_installer_version` equals the target installer's current
    `version` — otherwise `ERR_STALE_INSTALLER_VERSION` (412), on installer removal."

    PRD 2.8: "And the stale-version guards of ranks 10 and 11 run **before** any state
    precondition, so a client that is both stale and wrong about the state sees the
    stale-version error."

    Design: Corner/errors/removal_refusals_check_the_version_before_the_eligibility
    """
    jurisdiction = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())
    firm = fx.activated_installer(api, jurisdiction["id"])["installer"]
    # With no scorecard event at all the firm sits on the programme baseline.
    assert firm["status"] == InstallerStatus.ACTIVE
    assert firm["removal_eligible"] is False
    assert_score(firm["composite_score"], 85.00, "composite_score")

    response = api.remove_installer(firm["id"],
                                    f.removal_payload(firm["version"] + 1),
                                    SERVICE_MANAGER)
    validate_error(response, ApiErrorId.STALE_INSTALLER_VERSION)

    after = fx.read_installer(api, firm["id"])
    assert after["status"] == InstallerStatus.ACTIVE
    assert after["removed_at"] is None
    assert_version(after, firm["version"], "the installer")


def test_the_correct_version_then_fails_on_the_eligibility_rule(api):
    """With the right token the request reaches the eligibility rule and is refused
    there, because a firm with no adverse history is not removable.

    PRD 2.8 rank 33: "`removal_eligible` is true, the installer's `status` is `ACTIVE`,
    `PROBATION` or `SUSPENDED`, and the installer holds no assignment whose `status` is
    `IN_PROGRESS` — otherwise `ERR_REMOVAL_NOT_ELIGIBLE` (409)."

    Design: Corner/errors/removal_refusals_check_the_version_before_the_eligibility
    """
    jurisdiction = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())
    firm = fx.activated_installer(api, jurisdiction["id"])["installer"]

    validate_error(
        api.remove_installer(firm["id"], f.removal_payload(firm["version"] + 1),
                             SERVICE_MANAGER),
        ApiErrorId.STALE_INSTALLER_VERSION,
    )
    response = api.remove_installer(firm["id"], f.removal_payload(firm["version"]),
                                    SERVICE_MANAGER)
    validate_error(response, ApiErrorId.REMOVAL_NOT_ELIGIBLE)

    after = fx.read_installer(api, firm["id"])
    assert after["status"] == InstallerStatus.ACTIVE
    assert after["removed_at"] is None
    assert after["removal_reason"] is None
    assert_version(after, firm["version"], "the installer")
