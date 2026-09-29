"""Writes whose legality is decided by the state of a *different* entity.

Each pair here refuses a request that is faultless in itself, and accepts the
byte-identical request once the other entity has moved.
"""

from test_helpers import (
    NETWORK_MANAGER,
    PROJECT_COORDINATOR,
    ApiErrorId,
    AssignmentStatus,
    CredentialStatus,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    MeasurementStatus,
    PermitResponsibleParty,
    PermitStatus,
    PunchItemStatus,
    assert_committed_minutes,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_score,
    assert_version,
    factories as f,
    fixtures as fx,
    get_success_data,
    make_installer_headers,
    validate_error,
)

MEASURED_AT = "2026-07-01T00:00:00.000Z"
# 45 whole days after the completion instant, to the second.
VALIDITY_LIMIT = "2026-08-15T00:00:00.000Z"
ONE_SECOND_LATE = "2026-08-15T00:00:01.000Z"
WINDOW_END = "2026-08-15T08:00:00.000Z"

DEPOSIT = 59002
QUOTED = 196673


# ---------------------------------------------------------------------------
# Measurement -> InstallerAssignment
# ---------------------------------------------------------------------------
def _measured_on_the_first_of_july(api):
    """A project measured at exactly 2026-07-01T00:00:00.000Z, with an active firm
    standing by. The category keeps a measurement usable for 45 days."""
    base = fx.program_baseline(api, f.measured_category_payload(),
                               f.jurisdiction_payload())
    network = fx.activated_installer(api, base["jurisdiction"]["id"],
                                    background_completed_at="2026-06-01T00:00:00.000Z")
    base.update(network)
    project = fx.sell_project(api, base, estimated_units=420.00)
    project = fx.pay_deposit(api, project, base["customer"]["id"])

    fx.set_clock(api, MEASURED_AT)
    measurement = fx.book_measurement(api, project["id"], "2026-07-01T09:00:00.000Z")
    # measured_units identical to estimated_units, so variance is 0.00 and no
    # variance change order is raised.
    base["measurement"] = fx.complete_measurement(api, measurement["id"], 420.00)
    base["project"] = fx.read_project(api, project["id"])
    return base


def test_a_window_one_second_past_the_measurement_validity_is_refused(api):
    """The assignment itself is faultless; it is the measurement's age, read through the
    category's validity window, that refuses it.

        PRD 3.6: "Where the category has `measurement_required` true, the
    project must have a `COMPLETED` measurement and the assignment's
    `window_start` must be no later than that measurement's `completed_at` plus
    the category's `measurement_validity_days` whole days, an **inclusive**
    upper bound, or the answer is `ERR_MEASUREMENT_STALE` — measurements go
    stale, and a house measured months ago must be measured again."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_depends_on_the_measurement_validity_of_another_entity
    """
    ctx = _measured_on_the_first_of_july(api)
    measurement = ctx["measurement"]
    assert measurement["status"] == MeasurementStatus.COMPLETED
    assert_instant(measurement["completed_at"], MEASURED_AT, "completed_at")
    assert_score(measurement["variance_pct"], 0.00, "variance_pct")
    assert measurement["change_order_triggered"] is False

    version_before = fx.project_version(api, ctx["project"]["id"])
    response = api.create_assignment(
        f.assignment_payload(ctx["project"]["id"], ctx["installer"]["id"],
                             version_before,
                             window_start=ONE_SECOND_LATE,
                             window_end=WINDOW_END),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.MEASUREMENT_STALE)

    after = fx.read_project(api, ctx["project"]["id"])
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED)
    assert_version(after, version_before, "the refused project")


def test_a_window_exactly_at_the_measurement_validity_limit_is_held(api):
    """One second earlier, exactly on the inclusive limit, the same request is held and
    the project moves onto the calendar.

    PRD 3.6: "A successful hold creates the assignment at `status` `HELD`, increases the
    installer's `committed_minutes` by `duration_minutes`, drives the project
    `MEASURED → SCHEDULED`, and increments both the project's and the installer's
    `version`."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_depends_on_the_measurement_validity_of_another_entity
    """
    ctx = _measured_on_the_first_of_july(api)
    project_id = ctx["project"]["id"]
    installer_id = ctx["installer"]["id"]
    version_before = fx.project_version(api, project_id)

    validate_error(
        api.create_assignment(
            f.assignment_payload(project_id, installer_id, version_before,
                                 window_start=ONE_SECOND_LATE,
                                 window_end=WINDOW_END),
            PROJECT_COORDINATOR),
        ApiErrorId.MEASUREMENT_STALE,
    )

    assignment = fx.hold_assignment(api, project_id, installer_id, version_before,
                                    window_start=VALIDITY_LIMIT,
                                    window_end=WINDOW_END)
    assert assignment["status"] == AssignmentStatus.HELD
    assert assignment["duration_minutes"] == 480

    project = fx.read_project(api, project_id)
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.SCHEDULED,
                              financial=FinancialStatus.DEPOSIT_HELD,
                              permit=PermitStatus.PENDING_APPLICATION)
    assert project["permit_responsibility"] == PermitResponsibleParty.RETAILER
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    assert_committed_minutes(fx.read_installer(api, installer_id), 480)


# ---------------------------------------------------------------------------
# Installer -> InstallerAssignment
# ---------------------------------------------------------------------------
SECOND_LICENCE = dict(license_number="FL-99450",
                      license_expires_on="2028-04-30T00:00:00.000Z")


def _suspended_firm_and_waiting_project(api):
    """A firm admitted to the network and then knocked straight back out by rejecting
    the only licence it holds, with a deposited project waiting for it."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.jurisdiction_payload())
    network = fx.activated_installer(api, base["jurisdiction"]["id"])
    base.update(network)
    get_success_data(
        api.verify_credential(base["credential"]["id"],
                             f.reject_payload("Licence lapsed at the state board"),
                             NETWORK_MANAGER)
    )
    project = fx.sell_project(api, base, estimated_units=420.00)
    base["project"] = fx.pay_deposit(api, project, base["customer"]["id"])
    base["installer"] = fx.read_installer(api, base["installer"]["id"])
    return base


def test_a_suspended_firm_is_refused_on_assignability_not_on_its_licence(api):
    """The firm is both unassignable and unlicensed, and the earlier-ranked
    assignability rule is the one that answers.

    PRD 2.8 rank 16: "The installer being assigned has network `status` of `ACTIVE` or
    `PROBATION`; `APPLIED`, `DOCS_PENDING`, `VERIFIED`, `SUSPENDED` and `REMOVED` firms
    cannot be assigned — otherwise `ERR_INSTALLER_NOT_ASSIGNABLE` (409)."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_depends_on_the_installer_status_another_call_changed
    """
    ctx = _suspended_firm_and_waiting_project(api)
    assert ctx["installer"]["status"] == InstallerStatus.SUSPENDED
    assert ctx["installer"]["verified_credential_count"] == 0

    response = api.create_assignment(
        f.assignment_payload(ctx["project"]["id"], ctx["installer"]["id"],
                             ctx["project"]["version"]),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.INSTALLER_NOT_ASSIGNABLE)

    after = fx.read_project(api, ctx["project"]["id"])
    assert_version(after, ctx["project"]["version"], "the refused project")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)


def test_verifying_a_replacement_licence_makes_the_identical_request_succeed(api):
    """Nothing about the assignment request changes: a second licence verified on the
    credential entity restores the firm and the byte-identical body is accepted.

    PRD 3.2: "Recovery is symmetrical and needs no separate endpoint: verifying any
    `PENDING` licence for a `SUSPENDED` firm moves it `SUSPENDED → ACTIVE`, provided the
    recomputed `verified_credential_count` is at least 1 and `insurance_expires_on` is
    strictly after the logical clock, and clears `probation_started_at` to null."

    Design: Difficulty/cross_entity_state_dependency/assignment_creation_depends_on_the_installer_status_another_call_changed
    """
    ctx = _suspended_firm_and_waiting_project(api)
    project_id = ctx["project"]["id"]
    installer_id = ctx["installer"]["id"]
    version_at_deposit = ctx["project"]["version"]
    payload = f.assignment_payload(project_id, installer_id, version_at_deposit)

    validate_error(api.create_assignment(payload, PROJECT_COORDINATOR),
                   ApiErrorId.INSTALLER_NOT_ASSIGNABLE)

    replacement = fx.file_credential(
        api, installer_id, ctx["jurisdiction"]["id"],
        f.credential_payload(ctx["jurisdiction"]["id"], **SECOND_LICENCE))
    replacement = fx.verify_credential(api, replacement["id"])

    installer = fx.read_installer(api, installer_id)
    assert installer["status"] == InstallerStatus.ACTIVE
    assert installer["verified_credential_count"] == 1
    assert installer["probation_started_at"] is None
    assert fx.read_credential(api, ctx["credential"]["id"])["verification_status"] == (
        CredentialStatus.REJECTED
    )
    assert replacement["verification_status"] == CredentialStatus.VERIFIED

    assignment = get_success_data(api.create_assignment(payload,
                                                        PROJECT_COORDINATOR))
    assert assignment["status"] == AssignmentStatus.HELD

    # Only the accepted hold moved the project, so its version advanced exactly once.
    project = fx.read_project(api, project_id)
    assert_version(project, version_at_deposit + 1, "project")
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.SCHEDULED)


# ---------------------------------------------------------------------------
# PunchListItem -> Project
# ---------------------------------------------------------------------------
COMPLETION_INSTANT = "2026-08-25T15:30:00.000Z"
FINAL_CHARGE = 196673


def test_a_project_cannot_close_while_one_punch_item_is_still_open(api):
    """`PUNCH_OPEN` is a legal state to close from and the money and permit dimensions
    are both ready, so only the punch item's own state blocks the close.

    PRD 3.7: "From `PUNCH_OPEN` it requires **every** punch item on the project to have
    `status` `VERIFIED` — an item still `OPEN`, still `RESOLVED` but unverified, or still
    `ESCALATED` blocks the close with `ERR_PUNCH_LIST_NOT_CLEARED`."

    Design: Difficulty/cross_entity_state_dependency/project_closure_depends_on_every_punch_list_item_reaching_verified
    """
    ctx = fx.punch_open_project(api)
    project_id = ctx["project"]["id"]
    item = ctx["punch_items"][0]
    assert item["status"] == PunchItemStatus.OPEN

    # The two other closing preconditions are already satisfied.
    assert_project_dimensions(ctx["project"],
                              fulfillment=FulfillmentStatus.PUNCH_OPEN,
                              financial=FinancialStatus.SETTLED,
                              permit=PermitStatus.NOT_REQUIRED)

    validate_error(api.close_project(project_id, PROJECT_COORDINATOR),
                   ApiErrorId.PUNCH_LIST_NOT_CLEARED)

    after = fx.read_project(api, project_id)
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.PUNCH_OPEN)
    assert after["closed_at"] is None
    assert fx.list_punch_items(api, project_id)[0]["status"] == PunchItemStatus.OPEN


def test_the_identical_close_succeeds_once_the_item_is_verified(api):
    """Resolving and signing off the one defect is what unlocks the project; the close
    request itself never changes.

    PRD 3.7: "Closing sets `fulfillment_status` to `CLOSED` and stamps `closed_at` with
    the logical clock."

    Design: Difficulty/cross_entity_state_dependency/project_closure_depends_on_every_punch_list_item_reaching_verified
    """
    ctx = fx.punch_open_project(api)
    project_id = ctx["project"]["id"]
    item_id = ctx["punch_items"][0]["id"]

    validate_error(api.close_project(project_id, PROJECT_COORDINATOR),
                   ApiErrorId.PUNCH_LIST_NOT_CLEARED)

    resolved = get_success_data(
        api.resolve_punch_item(
            item_id, f.resolution_payload("Quarter-round replaced and caulked"),
            make_installer_headers(ctx["installer"]["id"]))
    )
    assert resolved["status"] == PunchItemStatus.RESOLVED
    assert_instant(resolved["resolved_at"], COMPLETION_INSTANT, "resolved_at")

    verified = get_success_data(api.verify_punch_item(item_id, PROJECT_COORDINATOR))
    assert verified["status"] == PunchItemStatus.VERIFIED
    assert_instant(verified["verified_at"], COMPLETION_INSTANT, "verified_at")

    project = get_success_data(api.close_project(project_id, PROJECT_COORDINATOR))
    assert_project_dimensions(project, fulfillment=FulfillmentStatus.CLOSED,
                              financial=FinancialStatus.SETTLED,
                              permit=PermitStatus.NOT_REQUIRED)
    assert_instant(project["closed_at"], COMPLETION_INSTANT, "closed_at")
    assert_money(project["total_due_cents"], FINAL_CHARGE, "total_due_cents")
    assert_money(project["balance_due_cents"], 0, "balance_due_cents")
