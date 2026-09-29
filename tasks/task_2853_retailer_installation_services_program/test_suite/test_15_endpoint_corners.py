"""Endpoint-shape edges: partial amendment, a computed read that keys on the caller,
a party gate wider than the role gate, two body foreign keys, and the counters the
clock hands back.

Each test drives the documented HTTP surface and pins both what the response carries
and what the stored rows look like afterwards.
"""

from test_helpers import (
    MISSING_INSTALLER_ID,
    MISSING_PROJECT_ID,
    NETWORK_MANAGER,
    PROGRAM_ADMIN,
    PROJECT_COORDINATOR,
    SERVICE_MANAGER,
    ApiErrorId,
    AssignmentStatus,
    CategoryStatus,
    CredentialStatus,
    FinancialStatus,
    FulfillmentStatus,
    InstallerStatus,
    PermitResponsibleParty,
    PermitStatus,
    ReleaseReason,
    WaiverTier,
    assert_committed_minutes,
    assert_instant,
    assert_money,
    assert_project_dimensions,
    assert_version,
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
PATCHED_RATE = 480


def _catalogue(api):
    """One ACTIVE catalogue entry, one county and one household, so a project can be
    attempted against the entry both before and after it is retired."""
    return fx.program_baseline(api, f.service_category_payload(),
                              f.plain_jurisdiction_payload())


def test_a_second_entry_under_a_taken_code_is_refused(api):
    """The code is the catalogue key: a second POST under it is refused and the stored
    entry is not touched.

    PRD 3.1: "A second service category with an existing `code`, a second jurisdiction
    with an existing `code`, and a second live trade licence for a combination of
    installer, jurisdiction and trade all answer `ERR_DUPLICATE_CODE` with HTTP 409."

    Design: Corner/endpoints/service_category_patch_is_partial_and_retirement_closes_the_catalogue_entry
    """
    base = _catalogue(api)
    category = base["category"]

    response = api.create_service_category(
        f.service_category_payload(name="Duplicate Attempt"), PROGRAM_ADMIN)
    validate_error(response, ApiErrorId.DUPLICATE_CODE)

    stored = get_success_data(api.get_service_category(category["id"],
                                                      PROJECT_COORDINATOR))
    assert_version(stored, category["version"], "service category")
    assert stored["name"] == category["name"]
    assert stored["status"] == CategoryStatus.ACTIVE


def test_a_category_amendment_touches_only_the_named_fields(api):
    """Two fields are sent, two fields move, everything else stands, and the version
    advances by exactly one.

    PRD 3.1: "A category may later be amended in its `name`,
    `base_labor_rate_cents_per_unit`, `minimum_billable_units`,
    `measurement_validity_days`, `permit_policy`, `deposit_pct` and `status`; each
    amendment increments the category's `version`, and no amendment ever reaches back
    into a project whose quote has already been frozen."

    Design: Corner/endpoints/service_category_patch_is_partial_and_retirement_closes_the_catalogue_entry
    """
    base = _catalogue(api)
    category = base["category"]

    patched = get_success_data(
        api.patch_service_category(
            category["id"],
            {"name": "Direct-Ship Flooring Install (2026)",
             "base_labor_rate_cents_per_unit": PATCHED_RATE},
            PROGRAM_ADMIN)
    )

    assert patched["name"] == "Direct-Ship Flooring Install (2026)"
    assert patched["base_labor_rate_cents_per_unit"] == PATCHED_RATE
    # Neither the trade code nor the deposit fraction was named, so neither moved.
    assert patched["trade_code"] == category["trade_code"]
    assert patched["deposit_pct"] == category["deposit_pct"]
    assert patched["minimum_billable_units"] == category["minimum_billable_units"]
    assert patched["status"] == CategoryStatus.ACTIVE
    assert_version(patched, category["version"] + 1, "the amended category")

    read_back = get_success_data(api.get_service_category(category["id"],
                                                          PROJECT_COORDINATOR))
    assert read_back["name"] == patched["name"]
    assert read_back["base_labor_rate_cents_per_unit"] == PATCHED_RATE
    assert read_back["status"] == CategoryStatus.ACTIVE
    assert_version(read_back, patched["version"], "the re-read category")


def test_retiring_a_category_closes_it_to_the_catalogue_and_to_new_sales(api):
    """A second amendment retires the entry: the ACTIVE page no longer lists it and a
    project can no longer be sold against it.

    PRD 3.1: "Finally `status` is either `ACTIVE` or `RETIRED` and defaults to
    `ACTIVE`; a `RETIRED` category is refused at project creation with
    `ERR_REFERENCE_NOT_ELIGIBLE`."

    Design: Corner/endpoints/service_category_patch_is_partial_and_retirement_closes_the_catalogue_entry
    """
    base = _catalogue(api)
    category = base["category"]
    patched = get_success_data(
        api.patch_service_category(
            category["id"],
            {"name": "Direct-Ship Flooring Install (2026)",
             "base_labor_rate_cents_per_unit": PATCHED_RATE},
            PROGRAM_ADMIN)
    )

    retired = get_success_data(
        api.patch_service_category(category["id"],
                                   {"status": CategoryStatus.RETIRED},
                                   PROGRAM_ADMIN)
    )
    assert retired["status"] == CategoryStatus.RETIRED
    assert_version(retired, patched["version"] + 1, "the retired category")

    rows, meta = validate_paginated(
        api.list_service_categories(PROJECT_COORDINATOR,
                                    {"status": CategoryStatus.ACTIVE,
                                     "limit": 50, "offset": 0})
    )
    assert rows == []
    assert meta["total_count"] == 0

    response = api.create_project(
        f.project_payload(base["customer"]["id"], category["id"],
                          base["jurisdiction"]["id"]),
        PROJECT_COORDINATOR)
    validate_error(response, ApiErrorId.REFERENCE_NOT_ELIGIBLE)


def _previewable_project(api):
    """A 420.00-unit sale in the plain county with its 51306 deposit held, no material
    delivery, no permit, and the clock ten days on so the 72-hour tier no longer
    matches."""
    base = fx.program_baseline(api, f.service_category_payload(),
                               f.plain_jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    assert_money(project["quoted_labor_cents"], QUOTED, "quoted_labor_cents")
    project = fx.pay_deposit(api, project, base["customer"]["id"])
    assert_money(project["deposit_held_cents"], DEPOSIT, "deposit_held_cents")
    fx.set_clock(api, "2026-08-10T00:00:00.000Z")
    base["project"] = project
    return base


def test_the_same_sale_previews_two_different_settlements_for_two_roles(api):
    """A coordinator previewing this project is told 5131 is retained; a service manager
    previewing the very same project is told nothing is retained.

    PRD 3.8: "Because tier one keys on the acting role, the same project previewed by a
    `ServiceManager` and by its `Customer` legitimately returns two different answers."

    Design: Corner/endpoints/settlement_preview_is_role_sensitive_and_writes_nothing
    """
    ctx = _previewable_project(api)
    project_id = ctx["project"]["id"]

    coordinator = get_success_data(
        api.get_settlement_preview(project_id, PROJECT_COORDINATOR))
    # MEASURED forfeits 0.10 of the held deposit, and with no delivery there is
    # nothing to restock, so the gross is the labour forfeit alone.
    assert coordinator["labor_forfeit_pct"] == 0.10
    assert_money(coordinator["labor_forfeit_cents"], 5131, "labor_forfeit_cents")
    assert_money(coordinator["restocking_fee_cents"], 0, "restocking_fee_cents")
    assert_money(coordinator["gross_retained_cents"], 5131, "gross_retained_cents")
    assert coordinator["matched_waiver_tier"] == WaiverTier.NONE
    assert_money(coordinator["retained_cents"], 5131, "retained_cents")
    assert_money(coordinator["refund_cents"], 46175, "refund_cents")
    assert (coordinator["resulting_financial_status"]
            == FinancialStatus.PARTIALLY_REFUNDED)

    service_manager = get_success_data(
        api.get_settlement_preview(project_id, SERVICE_MANAGER))
    assert service_manager["matched_waiver_tier"] == WaiverTier.RETAILER_FAULT
    assert_money(service_manager["retained_cents"], 0, "retained_cents")
    assert_money(service_manager["refund_cents"], DEPOSIT, "refund_cents")
    assert (service_manager["resulting_financial_status"]
            == FinancialStatus.REFUNDED)
    # The two answers are computed from one unchanged deposit.
    assert_money(service_manager["deposit_held_cents"], DEPOSIT,
                 "deposit_held_cents in the preview")


def test_the_previews_write_nothing_and_the_cancel_lands_on_one_of_them(api):
    """Two previews leave the project exactly as it was, and the coordinator's own
    cancellation then reproduces the coordinator's preview figure for figure.

    PRD 3.8: "A computed read returns what the settlement *would* produce if the project
    were cancelled at this instant by the calling role, without moving a single bucket
    or changing a single status."

    Design: Corner/endpoints/settlement_preview_is_role_sensitive_and_writes_nothing
    """
    ctx = _previewable_project(api)
    project = ctx["project"]

    coordinator = get_success_data(
        api.get_settlement_preview(project["id"], PROJECT_COORDINATOR))
    get_success_data(api.get_settlement_preview(project["id"], SERVICE_MANAGER))

    between = fx.read_project(api, project["id"])
    assert_money(between["deposit_held_cents"], DEPOSIT, "deposit_held_cents")
    assert_money(between["deposit_forfeited_cents"], 0, "deposit_forfeited_cents")
    assert_money(between["deposit_refunded_cents"], 0, "deposit_refunded_cents")
    assert_version(between, project["version"], "the previewed project")
    assert_project_dimensions(between, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)

    cancelled = fx.cancel_project(api, project["id"], PROJECT_COORDINATOR,
                                  "Customer changed their mind")
    assert_money(cancelled["deposit_forfeited_cents"],
                 coordinator["retained_cents"], "deposit_forfeited_cents")
    assert_money(cancelled["deposit_refunded_cents"],
                 coordinator["refund_cents"], "deposit_refunded_cents")
    assert_money(cancelled["deposit_held_cents"], 0, "deposit_held_cents")
    assert_project_dimensions(cancelled,
                              fulfillment=FulfillmentStatus.CANCELLED,
                              financial=FinancialStatus.PARTIALLY_REFUNDED)


def _retailer_permit_project(api):
    """A permit-bearing sale whose paperwork the retailer owes, plus one admitted firm
    so an Installer-role call can be made with a real acting identity."""
    base = fx.program_baseline(api, f.quick_category_payload(),
                               f.jurisdiction_payload())
    project = fx.sell_project(api, base, estimated_units=420.00)
    # 420.00 units clears the 250.00 threshold and FLOORING is a permit trade there.
    assert project["permit_responsibility"] == PermitResponsibleParty.RETAILER
    assert_project_dimensions(project, permit=PermitStatus.PENDING_APPLICATION)
    base["project"] = project
    base.update(fx.activated_installer(api, base["jurisdiction"]["id"]))
    return base


def test_neither_the_household_nor_the_firm_may_file_the_retailers_paperwork(api):
    """Both roles may reach this operation, and both are refused on the party rather
    than on the role, because the responsibility resolved to the retailer.

    PRD 3.5: "Role matching is exact: `ProjectCoordinator` acts for `RETAILER`, the
    assigned `Installer` acts for `INSTALLER`, and the household's `Customer` acts for
    `CUSTOMER`; a caller whose role is permitted to reach the operation at all but does
    not match the recorded responsibility is refused with `ERR_WRONG_PERMIT_PARTY`."

    Design: Corner/endpoints/permit_application_is_gated_on_the_determined_responsible_party
    """
    ctx = _retailer_permit_project(api)
    project = ctx["project"]

    household = api.apply_permit(project["id"],
                                f.permit_apply_payload("PA-CUST-1"),
                                make_customer_headers(ctx["customer"]["id"]))
    validate_error(household, ApiErrorId.WRONG_PERMIT_PARTY)

    firm = api.apply_permit(project["id"],
                           f.permit_apply_payload("PA-INST-1"),
                           make_installer_headers(ctx["installer"]["id"]))
    validate_error(firm, ApiErrorId.WRONG_PERMIT_PARTY)

    after = fx.read_project(api, project["id"])
    assert_project_dimensions(after, permit=PermitStatus.PENDING_APPLICATION)
    assert after["permit_application_reference"] is None
    assert_version(after, project["version"], "the project after two refusals")


def test_the_coordinator_files_the_identical_application(api):
    """The same call from the party the determination named is accepted and moves the
    permit dimension on by one step.

    PRD 3.5: "A filing from `PENDING_APPLICATION` records the reference and moves
    `permit_status` to `APPLIED`."

    Design: Corner/endpoints/permit_application_is_gated_on_the_determined_responsible_party
    """
    ctx = _retailer_permit_project(api)
    project = ctx["project"]
    validate_error(
        api.apply_permit(project["id"], f.permit_apply_payload("PA-CUST-1"),
                         make_customer_headers(ctx["customer"]["id"])),
        ApiErrorId.WRONG_PERMIT_PARTY,
    )

    filed = get_success_data(
        api.apply_permit(project["id"], f.permit_apply_payload("PA-COORD-1"),
                         PROJECT_COORDINATOR)
    )
    assert_project_dimensions(filed, permit=PermitStatus.APPLIED)
    assert filed["permit_application_reference"] == "PA-COORD-1"
    assert_version(filed, project["version"] + 1, "the project after the filing")


def _link_ready(api):
    """One admitted firm and one deposited project in the same county, both sides of the
    link waiting to be joined."""
    ctx = fx.deposited_project(api,
                               jurisdiction_payload=f.plain_jurisdiction_payload())
    ctx.update(fx.activated_installer(api, ctx["jurisdiction"]["id"]))
    return ctx


def test_an_assignment_needs_both_body_keys_to_resolve(api):
    """Each unresolvable body foreign key answers with its own entity's not-found code,
    and neither refusal leaves half a link behind.

    PRD 2.8 rank 7: "Every foreign-key identifier in the request body resolves to a
    stored row, checked in the field order the endpoint declares — otherwise that
    entity's not-found code (404)."

    Design: Corner/endpoints/assignment_creation_requires_both_sides_of_the_link_to_exist
    """
    ctx = _link_ready(api)
    project = ctx["project"]
    installer = ctx["installer"]

    unknown_project = api.create_assignment(
        f.assignment_payload(MISSING_PROJECT_ID, installer["id"],
                             project["version"],
                             window_start="2026-09-01T08:00:00.000Z",
                             window_end="2026-09-01T16:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(unknown_project, ApiErrorId.PROJECT_NOT_FOUND)

    unknown_installer = api.create_assignment(
        f.assignment_payload(project["id"], MISSING_INSTALLER_ID,
                             project["version"],
                             window_start="2026-09-01T08:00:00.000Z",
                             window_end="2026-09-01T16:00:00.000Z"),
        PROJECT_COORDINATOR)
    validate_error(unknown_installer, ApiErrorId.INSTALLER_NOT_FOUND)

    assert_committed_minutes(fx.read_installer(api, installer["id"]), 0)
    after = fx.read_project(api, project["id"])
    assert_version(after, project["version"], "the project after two refusals")
    assert_project_dimensions(after, fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)


def test_the_resolved_link_is_readable_from_both_of_its_parents(api):
    """With both keys resolving, one assignment appears, carries both parent ids, and is
    reflected in the derived fields on each parent.

    PRD 3.6: "A successful hold creates the assignment at `status` `HELD`, increases the
    installer's `committed_minutes` by `duration_minutes`, drives the project
    `MEASURED → SCHEDULED`, and increments both the project's and the installer's
    `version`."

    Design: Corner/endpoints/assignment_creation_requires_both_sides_of_the_link_to_exist
    """
    ctx = _link_ready(api)
    project = ctx["project"]
    installer = ctx["installer"]

    assignment = fx.hold_assignment(api, project["id"], installer["id"],
                                    project["version"],
                                    window_start="2026-09-01T08:00:00.000Z",
                                    window_end="2026-09-01T16:00:00.000Z")

    linked = get_success_data(
        api.get_assignment(assignment["id"],
                           make_installer_headers(installer["id"]))
    )
    assert linked["project_id"] == project["id"]
    assert linked["installer_id"] == installer["id"]
    assert linked["status"] == AssignmentStatus.HELD
    assert linked["duration_minutes"] == 480

    assert_project_dimensions(fx.read_project(api, project["id"]),
                              fulfillment=FulfillmentStatus.SCHEDULED)
    assert_committed_minutes(fx.read_installer(api, installer["id"]), 480)


def _firm_with_a_lapsing_licence(api):
    """One firm whose single verified licence lapses on 2026-09-30, holding one
    480-minute window on a deposited project."""
    ctx = fx.deposited_project(api,
                               jurisdiction_payload=f.plain_jurisdiction_payload())
    jurisdiction_id = ctx["jurisdiction"]["id"]
    ctx.update(fx.activated_installer(
        api, jurisdiction_id,
        credential_payload=f.credential_payload(
            jurisdiction_id, license_expires_on="2026-09-30T00:00:00.000Z"),
    ))
    ctx["assignment"] = fx.hold_assignment(
        api, ctx["project"]["id"], ctx["installer"]["id"],
        ctx["project"]["version"],
        window_start="2026-09-01T08:00:00.000Z",
        window_end="2026-09-01T16:00:00.000Z")
    return ctx


def test_the_clock_advance_reports_the_sweep_it_performed(api):
    """Moving the clock past the only verified licence returns one expiry, one
    suspension and one rescoring in the same response, and the new instant is readable
    afterwards.

    PRD 2.4: "The clock response reports `current_utc` along with three counters —
    `credentials_expired_count`, `installers_suspended_count` and
    `installers_rescored_count` — so a caller can see what the advance did."

    Design: Corner/endpoints/clock_advance_returns_the_sweep_counters_it_actually_applied
    """
    ctx = _firm_with_a_lapsing_licence(api)
    assert ctx["installer"]["verified_credential_count"] == 1

    report = fx.set_clock(api, "2026-10-01T00:00:00.000Z")
    assert_instant(report["current_utc"], "2026-10-01T00:00:00.000Z", "current_utc")
    assert report["credentials_expired_count"] == 1
    assert report["installers_suspended_count"] == 1
    assert report["installers_rescored_count"] == 1

    assert_instant(fx.read_clock(api)["current_utc"], "2026-10-01T00:00:00.000Z",
                   "current_utc on the read-back")


def test_the_same_request_releases_the_window_the_expiry_invalidated(api):
    """The advance is not merely a report: it expires the licence, suspends the firm,
    hands its capacity back and drops the project out of SCHEDULED.

    PRD 3.2: "That suspension is hop three of a four-hop chain: the licence transition is
    hop one, the firm's suspension is hop two, hop three transitions every assignment of
    that firm whose `status` is `HELD` or `CONFIRMED` to `RELEASED` with
    `release_reason` recorded as `INSTALLER_SUSPENDED`, and hop four — caused by hop
    three — reduces the firm's `committed_minutes` by each released assignment's
    `duration_minutes` and reverts each affected project `SCHEDULED → MEASURED`."

    Design: Corner/endpoints/clock_advance_returns_the_sweep_counters_it_actually_applied
    """
    ctx = _firm_with_a_lapsing_licence(api)
    assert_committed_minutes(fx.read_installer(api, ctx["installer"]["id"]), 480)

    fx.set_clock(api, "2026-10-01T00:00:00.000Z")

    credential = fx.read_credential(api, ctx["credential"]["id"])
    assert credential["verification_status"] == CredentialStatus.EXPIRED

    firm = get_success_data(api.get_installer(ctx["installer"]["id"],
                                              NETWORK_MANAGER))
    assert firm["status"] == InstallerStatus.SUSPENDED
    assert firm["verified_credential_count"] == 0
    assert_committed_minutes(firm, 0)

    released = fx.read_assignment(api, ctx["assignment"]["id"])
    assert released["status"] == AssignmentStatus.RELEASED
    assert released["release_reason"] == ReleaseReason.INSTALLER_SUSPENDED

    assert_project_dimensions(fx.read_project(api, ctx["project"]["id"]),
                              fulfillment=FulfillmentStatus.MEASURED,
                              financial=FinancialStatus.DEPOSIT_HELD)
