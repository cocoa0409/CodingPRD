"""
Authority gates on the firm's project accounting API.

Three independent 403 families guard the same endpoints and their order is
observable: project-manager ownership, client-contact ownership, segregation of
duties and the write-off approval level all sit above request shape, so a caller
who trips two of them learns only about the earlier one. The write-off approval
endpoint carries three of those gates at once, the client's own reviewer is the
single entity-backed identity whose reads are confined to its own projects, and
header presence is settled before any role is looked at.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_APPROVAL_LEVEL_INSUFFICIENT,
    ERR_NOT_PROJECT_CLIENT,
    ERR_NOT_PROJECT_MANAGER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import (
    assert_invoice_money,
    assert_money,
    assert_outranks,
    assert_project_ledger,
    assert_write_off_routing,
)
from test_helpers.constants import (
    APPROVER_CONTROLLER,
    APPROVER_PROJECT_MANAGER,
    CLOCK_2026_06_01,
    DECISION_APPROVE,
    DECISION_REQUEST_REVISION,
    INVOICE_PENDING_CLIENT_REVIEW,
    INVOICE_REVISION_REQUESTED,
    TIME_ENTRY_APPROVED,
    TIME_ENTRY_BILLED,
    TIME_ENTRY_WRITTEN_OFF,
    WRITE_OFF_APPROVED,
    WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
    WRITE_OFF_PENDING_PM_APPROVAL,
)
from test_helpers.fixtures import (
    approve_time_entry,
    build_active_project,
    create_private_client,
    prepare_invoice,
    prepare_labor_write_off,
    read_project,
    read_time_entry,
    read_write_off,
    submit_invoice,
    submit_time_entry,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    ACCOUNTANT_USER_ID,
    CONTROLLER,
    CONTROLLER_ALT,
    FIRM_ADMIN,
    PROJECT_MANAGER,
    PROJECT_MANAGER_ALT,
    PROJECT_MANAGER_USER_ID,
    headers_without_role,
    make_client_contact_headers,
    unrecognised_role_headers,
)

# 24.00 h and 20.00 h of PROJECT_ARCHITECT time at a raw cost rate of 62.50
# under a multiplier of 3.0500 freeze billable values of 4575.00 and 3812.50.
LINE_ONE_BILLABLE = 4575.00
LINE_TWO_BILLABLE = 3812.50
BOTH_LINES_BILLABLE = 8387.50


def _two_approved_lines(api):
    # An ACTIVE time-and-materials project carrying two approved unbilled lines,
    # entered by the accountant and approved by a Controller so that neither the
    # owning manager's ownership nor its segregation standing is spent yet.
    ctx = build_active_project(api)
    first = submit_time_entry(api, ctx, hours=24.00, work_date="2026-05-11")
    approve_time_entry(api, first["id"], CONTROLLER)
    second = submit_time_entry(api, ctx, hours=20.00, work_date="2026-05-12")
    approve_time_entry(api, second["id"], CONTROLLER)
    return ctx, first["id"], second["id"]


def test_write_off_amount_and_age_route_the_approval_level(api):
    """
    Two write-offs on the same two approved lines route to different approval
    levels: 8387.50 escalates on amount while 4575.00 stays with the manager,
    and each freezes the ordered prefix of the labour it was allocated to.

    PRD §3.8: "`required_approver` is set to `CONTROLLER` when the `amount` is at or above 5000.00 or the `aging_days` is at or above 90"
    PRD §3.8: "The write-off's initial `status` is `PENDING_CONTROLLER_APPROVAL` when `required_approver` is `CONTROLLER` and `PENDING_PM_APPROVAL` when it is `PROJECT_MANAGER`."
    PRD §3.8: "The candidate list is the project's time entries whose `status` is `APPROVED` and whose `billed_invoice_id` is null, ordered by `work_date` ascending and then by `created_at` ascending — never by `id`."
    PRD §3.8: "`aging_days` is frozen at the greatest age in whole days among those allocated entries, measured from each entry's `work_date` against the logical clock."

    Design: Corner/rbac/write_off_approval_authority_is_a_four_rung_ladder
    """
    ctx, first_id, second_id = _two_approved_lines(api)

    escalated = prepare_labor_write_off(
        api, ctx, BOTH_LINES_BILLABLE, headers=ACCOUNTANT
    )
    manager_level = prepare_labor_write_off(
        api, ctx, LINE_ONE_BILLABLE, headers=PROJECT_MANAGER
    )

    assert_write_off_routing(
        escalated,
        required_approver=APPROVER_CONTROLLER,
        status=WRITE_OFF_PENDING_CONTROLLER_APPROVAL,
        aging_days=21,
        allocated_time_entry_ids=[first_id, second_id],
    )
    assert escalated["prepared_by_user_id"] == ACCOUNTANT_USER_ID
    assert escalated["approved_by_user_id"] is None

    assert_write_off_routing(
        manager_level,
        required_approver=APPROVER_PROJECT_MANAGER,
        status=WRITE_OFF_PENDING_PM_APPROVAL,
        aging_days=21,
        allocated_time_entry_ids=[first_id],
    )
    assert manager_level["prepared_by_user_id"] == PROJECT_MANAGER_USER_ID


def test_off_project_manager_is_stopped_at_ownership_before_the_level_check(api):
    """
    A manager who does not own the project is refused for ownership on a
    write-off that also needs a Controller, because ownership is settled first.

    PRD §2.1: "When `X-User-Role` is `ProjectManager` and the operation mutates a project's own records, the acting `X-User-ID` must equal that project's `project_manager_user_id`; otherwise the request is rejected with `ERR_NOT_PROJECT_MANAGER` (HTTP 403)."
    PRD §2.8: "Project-manager ownership — `ERR_NOT_PROJECT_MANAGER`."

    Design: Corner/rbac/write_off_approval_authority_is_a_four_rung_ladder
    """
    ctx, _first_id, _second_id = _two_approved_lines(api)
    escalated = prepare_labor_write_off(
        api, ctx, BOTH_LINES_BILLABLE, headers=ACCOUNTANT
    )

    response = api.approve_write_off(escalated["id"], PROJECT_MANAGER_ALT)
    validate_error(response, ERR_NOT_PROJECT_MANAGER, 403)
    assert_outranks(ERR_NOT_PROJECT_MANAGER, ERR_APPROVAL_LEVEL_INSUFFICIENT)

    unchanged = read_write_off(api, escalated["id"])
    assert unchanged["status"] == WRITE_OFF_PENDING_CONTROLLER_APPROVAL
    assert unchanged["version"] == escalated["version"]
    assert unchanged["approved_by_user_id"] is None


def test_owning_manager_is_refused_at_the_approval_level_on_an_escalated_row(api):
    """
    The project's own manager clears ownership and segregation on an escalated
    write-off and is still refused: the role is admissible for the operation, it
    is simply not authorised for that particular row.

    PRD §2.1: "A write-off sitting in `PENDING_CONTROLLER_APPROVAL` may only be approved by an acting `Controller`."
    PRD §2.1: "A `ProjectManager` is authenticated and is an admissible role for the write-off approval operation in general, but is not authorised for that particular row; the attempt is refused with `ERR_APPROVAL_LEVEL_INSUFFICIENT` (HTTP 403)."

    Design: Corner/rbac/write_off_approval_authority_is_a_four_rung_ladder
    """
    ctx, first_id, second_id = _two_approved_lines(api)
    escalated = prepare_labor_write_off(
        api, ctx, BOTH_LINES_BILLABLE, headers=ACCOUNTANT
    )

    response = api.approve_write_off(escalated["id"], PROJECT_MANAGER)
    validate_error(response, ERR_APPROVAL_LEVEL_INSUFFICIENT, 403)

    unchanged = read_write_off(api, escalated["id"])
    assert unchanged["status"] == WRITE_OFF_PENDING_CONTROLLER_APPROVAL
    assert unchanged["version"] == escalated["version"]
    for entry_id in (first_id, second_id):
        assert read_time_entry(api, entry_id)["status"] == TIME_ENTRY_APPROVED
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=BOTH_LINES_BILLABLE,
        written_off_gross=0.00,
        total_charge_value=BOTH_LINES_BILLABLE,
    )


def test_manager_may_not_approve_the_write_off_it_prepared_itself(api):
    """
    On a manager-level write-off the owning manager is authorised for the level
    but is the preparer, and preparation and approval are never the same person.

    PRD §2.1: "Four operations enforce it: approving a time entry (against its `submitted_by_user_id`), approving a consultant payable (against its `entered_by_user_id`), approving a write-off (against its `prepared_by_user_id`) and submitting an invoice to the client (against its `prepared_by_user_id`). A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §2.8: "A write-off approval attempted by the wrong-level approver on a row the approver also prepared reports `ERR_SEGREGATION_OF_DUTIES`, because segregation of duties sits above the approval-level gate."

    Design: Corner/rbac/write_off_approval_authority_is_a_four_rung_ladder
    """
    ctx, first_id, _second_id = _two_approved_lines(api)
    manager_level = prepare_labor_write_off(
        api, ctx, LINE_ONE_BILLABLE, headers=PROJECT_MANAGER
    )

    response = api.approve_write_off(manager_level["id"], PROJECT_MANAGER)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)
    assert_outranks(ERR_SEGREGATION_OF_DUTIES, ERR_APPROVAL_LEVEL_INSUFFICIENT)

    unchanged = read_write_off(api, manager_level["id"])
    assert unchanged["status"] == WRITE_OFF_PENDING_PM_APPROVAL
    assert unchanged["version"] == manager_level["version"]
    assert read_time_entry(api, first_id)["status"] == TIME_ENTRY_APPROVED


def test_controller_signing_a_manager_level_write_off_leaves_the_overhead_flag_alone(api):
    """
    A Controller may sign a manager-level write-off, and doing so does not turn
    it into a controller-level one: only the allocated line moves to written off,
    the second line stays approved and the overhead adjustment flag stays false.

    PRD §3.8: "On the project-manager branch, a `ProjectManager` or a `Controller` approves a write-off sitting in `PENDING_PM_APPROVAL`; when the acting role is `ProjectManager`, the acting `X-User-ID` must equal the project's `project_manager_user_id`, and in either case the acting `X-User-ID` must differ from `prepared_by_user_id`."
    PRD §3.8: "This branch leaves the project's `overhead_adjustment_required` flag **unchanged**."
    PRD §3.8: "Every time entry named in `allocated_time_entry_ids` moves `APPROVED → WRITTEN_OFF`, each such entry's `version` incrementing by 1; the project's `unbilled_wip` falls by the write-off `amount` while `written_off_gross` rises by the same amount"

    Design: Corner/rbac/write_off_approval_authority_is_a_four_rung_ladder
    """
    ctx, first_id, second_id = _two_approved_lines(api)
    manager_level = prepare_labor_write_off(
        api, ctx, LINE_ONE_BILLABLE, headers=PROJECT_MANAGER
    )

    approved = get_success_data(
        api.approve_write_off(manager_level["id"], CONTROLLER_ALT)
    )
    assert approved["status"] == WRITE_OFF_APPROVED
    assert approved["approved_by_user_id"] == CONTROLLER_ALT["X-User-ID"]

    assert read_time_entry(api, first_id)["status"] == TIME_ENTRY_WRITTEN_OFF
    assert read_time_entry(api, second_id)["status"] == TIME_ENTRY_APPROVED

    project = read_project(api, ctx.project_id)
    assert project["overhead_adjustment_required"] is False
    assert_project_ledger(
        project,
        unbilled_wip=LINE_TWO_BILLABLE,
        written_off_gross=LINE_ONE_BILLABLE,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        total_charge_value=BOTH_LINES_BILLABLE,
    )


# One 4.00 h architect line at 62.50 under a multiplier of 3.0500 bills 762.50,
# on which a 0.0500 retainage withholds 38.13 and leaves 724.37 net due.
CONTACT_INVOICE_GROSS = 762.50
CONTACT_INVOICE_RETAINAGE = 38.13
CONTACT_INVOICE_NET_DUE = 724.37


def _invoice_awaiting_client_review(api):
    # An invoice of the first client's project sitting in client review, plus a
    # second, unrelated client whose contact has no business with it.
    ctx = build_active_project(api)
    other_client = create_private_client(
        api,
        name="Harbor Point Trust",
        retainage_pct=0.1000,
        expense_markup_pct=0.0500,
        disallowed_categories=[],
        receipt_required_above=25.00,
        review_cycle_days=45,
    )
    entry = submit_time_entry(api, ctx, hours=4.00, work_date="2026-05-11")
    approve_time_entry(api, entry["id"], PROJECT_MANAGER)
    invoice = prepare_invoice(api, ctx, headers=ACCOUNTANT)
    submitted = submit_invoice(api, invoice["id"], CONTROLLER)
    return ctx, other_client["id"], submitted, entry["id"]


def test_another_clients_contact_reaches_neither_the_invoice_nor_the_list(api):
    """
    A contact acting for a different client is refused on the single-invoice
    retrieval and on the filtered list alike, and the refusal is an ownership
    403 rather than a 404, because the invoice plainly exists.

    PRD §2.1: "Concretely, for any invoice a client contact reaches, the owning project's `client_id` must equal the acting `X-User-ID`, and a mismatch is rejected with `ERR_NOT_PROJECT_CLIENT` (HTTP 403)."
    PRD §2.1: "This applies to a client review decision on an invoice and to both invoice read paths — the single-invoice retrieval and the invoice list."

    Design: Corner/rbac/client_contact_reads_and_reviews_only_its_own_projects
    """
    ctx, other_client_id, invoice, _entry_id = _invoice_awaiting_client_review(api)
    assert invoice["status"] == INVOICE_PENDING_CLIENT_REVIEW
    assert_invoice_money(
        invoice,
        labor_billed=CONTACT_INVOICE_GROSS,
        gross_billed=CONTACT_INVOICE_GROSS,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=CONTACT_INVOICE_RETAINAGE,
        net_due=CONTACT_INVOICE_NET_DUE,
    )

    stranger = make_client_contact_headers(other_client_id)
    validate_error(
        api.get_invoice(invoice["id"], stranger), ERR_NOT_PROJECT_CLIENT, 403
    )
    validate_error(
        api.list_invoices(stranger, {"project_id": ctx.project_id}),
        ERR_NOT_PROJECT_CLIENT,
        403,
    )


def test_another_clients_contact_cannot_decide_the_review(api):
    """
    The review decision carries the same ownership comparison as the reads, and
    the refused decision leaves the invoice awaiting its own client.

    PRD §2.1: "Concretely, for any invoice a client contact reaches, the owning project's `client_id` must equal the acting `X-User-ID`, and a mismatch is rejected with `ERR_NOT_PROJECT_CLIENT` (HTTP 403)."
    PRD §3.7: "A `ClientContact` whose `X-User-ID` equals the project's `client_id` supplies a `decision` of `APPROVE` or `REQUEST_REVISION`, optionally with a `comment`, which is recorded on the invoice as `client_decision_comment`."

    Design: Corner/rbac/client_contact_reads_and_reviews_only_its_own_projects
    """
    _ctx, other_client_id, invoice, _entry_id = _invoice_awaiting_client_review(api)

    response = api.review_invoice(
        invoice["id"],
        f.invoice_review_payload(DECISION_APPROVE),
        make_client_contact_headers(other_client_id),
    )
    validate_error(response, ERR_NOT_PROJECT_CLIENT, 403)

    unchanged = get_success_data(api.get_invoice(invoice["id"], CONTROLLER))
    assert unchanged["status"] == INVOICE_PENDING_CLIENT_REVIEW
    assert unchanged["revision_round"] == 0
    assert unchanged["client_decision_comment"] is None
    assert unchanged["version"] == invoice["version"]


def test_a_controller_cannot_stand_in_for_the_clients_own_reviewer(api):
    """
    The client's decision is the one capability the firm's finance owner cannot
    exercise, and the refusal names role admission rather than ownership because
    role admission is settled first.

    PRD §2.1: "A `ClientContact` is the client's own reviewer, whose only exclusive capability is accepting or requesting revision on an invoice under client review, and whose reads are confined to the invoices of their own client's projects."
    PRD §2.1: "If `X-User-Role` is not one of the five recognised roles, or is a recognised role that the target operation does not admit, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.8: "2. Role recognition and role admission for the operation — `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/client_contact_reads_and_reviews_only_its_own_projects
    """
    _ctx, _other_client_id, invoice, _entry_id = _invoice_awaiting_client_review(api)

    response = api.review_invoice(
        invoice["id"], f.invoice_review_payload(DECISION_APPROVE), CONTROLLER
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert_outranks(ERR_UNAUTHORIZED, ERR_NOT_PROJECT_CLIENT)

    unchanged = get_success_data(api.get_invoice(invoice["id"], CONTROLLER))
    assert unchanged["status"] == INVOICE_PENDING_CLIENT_REVIEW
    assert unchanged["revision_round"] == 0


def test_the_owning_clients_contact_reads_and_drives_the_review_cycle(api):
    """
    The contact whose identifier is the project's own client reads the invoice at
    its frozen totals and sends it back for revision, which counts the round
    before moving the state and leaves the swept line billed.

    PRD §2.1: "When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's foreign-key field to `X-User-ID`."
    PRD §3.7: "`REQUEST_REVISION` first increments `revision_round` by 1 and then moves the invoice `PENDING_CLIENT_REVIEW → REVISION_REQUESTED`."
    PRD §3.7: "Charges already attached stay attached; the sweep re-runs and additionally attaches every newly eligible charge dated on or before `period_end`."

    Design: Corner/rbac/client_contact_reads_and_reviews_only_its_own_projects
    """
    ctx, _other_client_id, invoice, entry_id = _invoice_awaiting_client_review(api)
    owner = make_client_contact_headers(ctx.client_id)

    seen = get_success_data(api.get_invoice(invoice["id"], owner))
    assert_invoice_money(
        seen,
        gross_billed=CONTACT_INVOICE_GROSS,
        retainage_amount=CONTACT_INVOICE_RETAINAGE,
        net_due=CONTACT_INVOICE_NET_DUE,
    )

    decided = get_success_data(
        api.review_invoice(
            invoice["id"],
            f.invoice_review_payload(
                DECISION_REQUEST_REVISION, "Split the coordination hours by phase"
            ),
            owner,
        )
    )
    assert decided["revision_round"] == 1
    assert decided["status"] == INVOICE_REVISION_REQUESTED
    assert decided["client_decision_comment"] == "Split the coordination hours by phase"
    assert decided["version"] == invoice["version"] + 1

    still_billed = read_time_entry(api, entry_id)
    assert still_billed["status"] == TIME_ENTRY_BILLED
    assert still_billed["billed_invoice_id"] == invoice["id"]


def test_a_missing_role_header_is_reported_before_a_malformed_body(api, clock_june):
    """
    A request that is both unauthenticated and malformed is answered on the
    header alone: the unknown labour grade and the two absent required fields are
    never reported, and no rate is published.

    PRD §2.1: "Every request to the API must carry two headers. `X-User-ID` identifies the acting user and `X-User-Role` declares the capacity in which they are acting. If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8: "1. Header presence — `ERR_UNAUTHENTICATED`."
    PRD §2.8: "7. Request and query shape — `ERR_INVALID_REQUEST`."

    Design: Corner/rbac/authentication_precedes_authorization_which_precedes_ownership
    """
    response = api.create_labor_rate(
        {"role_code": "SENIOR_ENGINEER"}, headers_without_role()
    )
    validate_error(response, ERR_UNAUTHENTICATED, 401)

    _rows, meta = validate_paginated(api.list_labor_rates(CONTROLLER))
    assert meta["total_count"] == 0


def test_an_unrecognised_role_string_is_unauthorised_rather_than_unauthenticated(
    api, clock_june
):
    """
    Both headers are present and the body is perfectly valid; the capacity
    declared is simply not one of the five the firm recognises.

    PRD §2.1: "If `X-User-Role` is not one of the five recognised roles, or is a recognised role that the target operation does not admit, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "The five roles are spelled exactly `FirmAdmin`, `Controller`, `ProjectManager`, `ProjectAccountant` and `ClientContact`."

    Design: Corner/rbac/authentication_precedes_authorization_which_precedes_ownership
    """
    response = api.create_labor_rate(
        f.labor_rate_payload(), unrecognised_role_headers("aud-001")
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    _rows, meta = validate_paginated(api.list_labor_rates(CONTROLLER))
    assert meta["total_count"] == 0


def test_raw_cost_rates_are_hidden_from_managers_in_both_directions(api, clock_june):
    """
    Publishing and listing raw cost rates are both closed to a project manager,
    while the multiplier history of a project is open to that same manager.

    PRD §3.2: "The firm's cost side is governed by a firm-wide, append-only table of labour cost rates that only a `Controller` may publish."
    PRD §4: "List published cost rates, optionally resolving the window covering a given date | `FirmAdmin`, `Controller`, `ProjectAccountant`"
    PRD §4: "List billing multipliers for a project including superseded history | `FirmAdmin`, `Controller`, `ProjectManager`, `ProjectAccountant`"

    Design: Corner/rbac/authentication_precedes_authorization_which_precedes_ownership
    """
    ctx = build_active_project(api)

    validate_error(
        api.create_labor_rate(
            f.labor_rate_payload(raw_cost_rate=90.00, effective_from="2027-01-01"),
            PROJECT_MANAGER,
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(api.list_labor_rates(PROJECT_MANAGER), ERR_UNAUTHORIZED, 403)

    rows, meta = validate_paginated(
        api.list_billing_multipliers(PROJECT_MANAGER, {"project_id": ctx.project_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx.multiplier_id


def test_the_logical_clock_moves_for_the_firm_administrator_alone(api, clock_june):
    """
    A Controller who tries to move the single source of now is refused, and the
    clock is proved unmoved by the stamp the next registration receives.

    PRD §2.6: "A `FirmAdmin`-only administrative capability moves the clock to a supplied instant, passed as `to_iso8601`; after the move, billing posture and aging buckets are re-evaluated against the new instant the next time they are read."
    PRD §2.4: "Every resource also carries a `created_at` timestamp, an ISO 8601 UTC instant with three fractional digits, recorded from the logical clock described in §2.6 at the moment the row was written."

    Design: Corner/rbac/authentication_precedes_authorization_which_precedes_ownership
    """
    response = api.set_clock(f.clock_payload("2026-07-01T00:00:00Z"), CONTROLLER)
    validate_error(response, ERR_UNAUTHORIZED, 403)

    registered = create_private_client(api, name="Lakeshore Parks Trust")
    assert registered["created_at"] == CLOCK_2026_06_01.replace("Z", ".000Z")


def test_a_client_contact_has_no_role_for_the_project_read_at_all(api):
    """
    The contact of the project's very own client is refused on the project
    retrieval, and the refusal names role admission rather than ownership: the
    capacity is absent from that operation, so ownership is never consulted.

    PRD §2.1: "A `ClientContact` is the client's own reviewer, whose only exclusive capability is accepting or requesting revision on an invoice under client review, and whose reads are confined to the invoices of their own client's projects."
    PRD §2.8: "2. Role recognition and role admission for the operation — `ERR_UNAUTHORIZED`."
    PRD §2.8: "4. Client-contact ownership — `ERR_NOT_PROJECT_CLIENT`."

    Design: Corner/rbac/authentication_precedes_authorization_which_precedes_ownership
    """
    ctx = build_active_project(api)
    before = read_project(api, ctx.project_id)

    response = api.get_project(
        ctx.project_id, make_client_contact_headers(ctx.client_id)
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)
    assert_outranks(ERR_UNAUTHORIZED, ERR_NOT_PROJECT_CLIENT)

    assert read_project(api, ctx.project_id)["version"] == before["version"]


def test_the_firm_administrator_maintains_clients_but_never_bills_them(api):
    """
    Invoice preparation belongs to the accountant and the finance owner; the firm
    administrator is refused and no draft is left behind.

    PRD §3.7: "A `ProjectAccountant` or a `Controller` prepares a draft invoice by naming the `project_id`, a `period_end` acting as the inclusive cut-off date for the sweep, and the `expected_project_version` demanded by §2.7."
    PRD §2.1: "If `X-User-Role` is not one of the five recognised roles, or is a recognised role that the target operation does not admit, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/authentication_precedes_authorization_which_precedes_ownership
    """
    ctx = build_active_project(api)
    entry = submit_time_entry(api, ctx, hours=4.00, work_date="2026-05-11")
    approve_time_entry(api, entry["id"], PROJECT_MANAGER)
    before = read_project(api, ctx.project_id)

    response = api.create_invoice(
        f.invoice_payload(ctx.project_id, before["version"], period_end="2026-05-31"),
        FIRM_ADMIN,
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    _rows, meta = validate_paginated(
        api.list_invoices(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert meta["total_count"] == 0

    after = read_project(api, ctx.project_id)
    assert after["version"] == before["version"]
    assert_money(after["billed_open"], 0.00, "project.billed_open")
