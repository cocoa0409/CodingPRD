"""The rejection ladder: when one request breaks two rules, only the earlier-ranked
check may answer.

Each test builds a request that violates exactly two documented rules and pins the
single identifier the fixed evaluation order licenses.
"""

from test_helpers import (
    MISSING_INSTALLER_ID,
    PROJECT_COORDINATOR,
    ApiErrorId,
    FinancialStatus,
    FulfillmentStatus,
    assert_committed_minutes,
    assert_money,
    assert_project_dimensions,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    validate_error,
)

QUOTED_METRO01 = 196673
DEPOSIT_METRO01 = 59002
QUOTED_METRO02 = 171020
DEPOSIT_METRO02 = 51306


def test_a_coordinator_paying_a_wrong_deposit_is_refused_for_its_role(api):
    """The deposit endpoint admits only the household, so a coordinator sending the
    wrong amount is refused on the role and never reaches the amount test.

    PRD 2.8 rank 2: "`X-User-Role` is one of the six declared roles and is listed as
    authorised for the target endpoint — otherwise `ERR_UNAUTHORIZED_ROLE` (403).
    Applies to every endpoint."

    Design: Difficulty/priority_pair_validation_conflict/coordinator_paying_a_wrong_deposit_is_rejected_for_role_before_amount
    """
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    assert_money(project["deposit_required_cents"], DEPOSIT_METRO01,
                 "deposit_required_cents")

    # 12345 is neither the required amount nor anything like it, so the amount test of
    # rank 34 would also fail if the ladder ever reached it.
    response = api.pay_deposit(project["id"], f.deposit_payload(12345),
                               PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.UNAUTHORIZED_ROLE)


def test_the_refused_deposit_leaves_the_money_dimension_untouched(api):
    """The refused payment moves no bucket and does not open the money dimension.

    PRD 3.3: "A successful payment moves `financial_status` from `QUOTED` to
    `DEPOSIT_HELD`, sets `deposit_paid_cents` and `deposit_held_cents` both to the paid
    amount, re-checks the conservation identity of §2.10, and increments the project's
    `version`."

    Design: Difficulty/priority_pair_validation_conflict/coordinator_paying_a_wrong_deposit_is_rejected_for_role_before_amount
    """
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    validate_error(
        api.pay_deposit(project["id"], f.deposit_payload(12345),
                        PROJECT_COORDINATOR),
        ApiErrorId.UNAUTHORIZED_ROLE,
    )

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, financial=FinancialStatus.QUOTED)
    assert_money(after["deposit_paid_cents"], 0, "deposit_paid_cents")
    assert_money(after["deposit_held_cents"], 0, "deposit_held_cents")
    assert_money(after["deposit_required_cents"], DEPOSIT_METRO01,
                 "deposit_required_cents")
    assert_version(after, project["version"], "project")


def _two_jurisdiction_setup(api):
    """One firm licensed in Metro County only, with a confirmed window there and a
    second deposited project in a jurisdiction where it holds no licence."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.jurisdiction_payload())
    other_jurisdiction = fx.create_jurisdiction(api, f.plain_jurisdiction_payload())
    other_customer = fx.create_customer(
        api, other_jurisdiction["id"],
        f.second_customer_payload(other_jurisdiction["id"]))
    network = fx.activated_installer(api, base["jurisdiction"]["id"])
    installer = network["installer"]

    first = fx.sell_project(api, base, estimated_units=420.00)
    first = fx.pay_deposit(api, first, base["customer"]["id"])
    fx.plan_delivery(api, first["id"])
    first_assignment = fx.hold_assignment(api, first["id"], installer["id"],
                                          fx.project_version(api, first["id"]))
    get_success_data(api.confirm_assignment(first_assignment["id"],
                                            PROJECT_COORDINATOR))

    second = fx.sell_project(api, base, estimated_units=420.00,
                             customer=other_customer,
                             jurisdiction=other_jurisdiction,
                             site_address="22 Larch Way")
    second = fx.pay_deposit(api, second, other_customer["id"])

    return {
        "installer": installer,
        "first_project": first,
        "second_project": second,
    }


def test_an_unlicensed_firm_in_an_occupied_window_answers_on_the_licence(api):
    """The licence check of rank 17 runs before the calendar check of rank 23, so a
    request that breaks both answers with the licensing identifier.

    PRD 2.8: "Every compliance check on assignment creation — installer assignability,
    licensing, background check, insurance and measurement freshness, ranks 16 through
    20 — runs **before** the calendar and capacity checks of ranks 23 and 24, which in
    turn run **before** the fiscal check of rank 35."

    Design: Difficulty/priority_pair_validation_conflict/unlicensed_installer_with_overlapping_window_is_rejected_for_licence_first
    """
    ctx = _two_jurisdiction_setup(api)
    second = ctx["second_project"]
    assert_money(second["quoted_labor_cents"], QUOTED_METRO02,
                 "quoted_labor_cents under a multiplier of 1.00")
    assert_money(second["deposit_paid_cents"], DEPOSIT_METRO02,
                 "deposit_paid_cents")

    # 12:00 to 14:00 sits squarely inside the window the firm already holds elsewhere,
    # so the calendar would also refuse this request.
    response = api.create_assignment(
        f.assignment_payload(second["id"], ctx["installer"]["id"],
                             fx.project_version(api, second["id"]),
                             window_start="2026-08-25T12:00:00.000Z",
                             window_end="2026-08-25T14:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSTALLER_NOT_LICENSED)


def test_the_licence_refusal_leaves_both_projects_where_they_were(api):
    """Nothing is held: the second project keeps its version and status, and the firm's
    committed minutes still cover only the window it already had.

    PRD 3.6: "A successful hold creates the assignment at `status` `HELD`, increases the
    installer's `committed_minutes` by `duration_minutes`, drives the project
    `MEASURED → SCHEDULED`, and increments both the project's and the installer's
    `version`."

    Design: Difficulty/priority_pair_validation_conflict/unlicensed_installer_with_overlapping_window_is_rejected_for_licence_first
    """
    ctx = _two_jurisdiction_setup(api)
    second = ctx["second_project"]
    version_before = fx.project_version(api, second["id"])

    validate_error(
        api.create_assignment(
            f.assignment_payload(second["id"], ctx["installer"]["id"],
                                 version_before,
                                 window_start="2026-08-25T12:00:00.000Z",
                                 window_end="2026-08-25T14:00:00.000Z"),
            PROJECT_COORDINATOR),
        ApiErrorId.INSTALLER_NOT_LICENSED,
    )

    after = fx.read_project(api, second["id"])
    assert_version(after, version_before, "the refused project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)
    assert_money(after["quoted_labor_cents"], QUOTED_METRO02,
                 "quoted_labor_cents")
    # Only the confirmed eight-hour window in the other jurisdiction is committed.
    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 480)


def test_an_unknown_installer_outranks_a_stale_project_version(api):
    """A body foreign key that resolves to nothing is caught at rank 7, before the
    optimistic-concurrency comparison of rank 10 ever runs.

    PRD 2.8 rank 7: "Every foreign-key identifier in the request body resolves to a
    stored row, checked in the field order the endpoint declares — otherwise that
    entity's not-found code (404)."

    Design: Difficulty/priority_pair_validation_conflict/unknown_installer_with_stale_version_returns_installer_not_found
    """
    ctx = fx.deposited_project(api)
    project = ctx["project"]
    stale_version = project["version"] - 1

    response = api.create_assignment(
        f.assignment_payload(project["id"], MISSING_INSTALLER_ID, stale_version),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSTALLER_NOT_FOUND)


def test_the_not_found_refusal_does_not_touch_the_project(api):
    """The refused hold leaves the project's version, execution dimension and deposit
    exactly as they were.

    PRD 3.6: "A successful hold creates the assignment at `status` `HELD`, increases the
    installer's `committed_minutes` by `duration_minutes`, drives the project
    `MEASURED → SCHEDULED`, and increments both the project's and the installer's
    `version`."

    Design: Difficulty/priority_pair_validation_conflict/unknown_installer_with_stale_version_returns_installer_not_found
    """
    ctx = fx.deposited_project(api)
    project = ctx["project"]

    validate_error(
        api.create_assignment(
            f.assignment_payload(project["id"], MISSING_INSTALLER_ID,
                                 project["version"] - 1),
            PROJECT_COORDINATOR),
        ApiErrorId.INSTALLER_NOT_FOUND,
    )

    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)
    assert_money(after["deposit_held_cents"], DEPOSIT_METRO01,
                 "deposit_held_cents")
