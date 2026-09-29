"""
Gates that read the state of a third entity.

Two firm workflows cannot be decided from the row in hand alone. Releasing
payment to a subconsultant under pay-when-paid terms depends on the status of the
client invoice that billed the payable, and preparing an invoice for a
public-agency client depends on a firm-wide overhead rate certification the
project holds no foreign key to.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_CERTIFICATION_YEAR_DUPLICATE,
    ERR_OVERHEAD_RATE_NOT_CERTIFIED,
    ERR_PAY_WHEN_PAID_NOT_SATISFIED,
)
from test_helpers.assertions import (
    assert_billing_posture,
    assert_invoice_money,
    assert_null,
    assert_pagination_meta,
    assert_payable_axes,
    assert_payable_markup,
    assert_phase_earned_value,
    assert_project_ledger,
    assert_ratio,
    assert_subcontract_rollup,
    assert_swept_counts,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    CERT_CERTIFIED,
    CERT_REJECTED,
    CERT_SUBMITTED,
    CLOCK_2026_06_01,
    DECISION_APPROVE,
    FISCAL_YEAR_2025,
    FISCAL_YEAR_2026,
    INVOICE_APPROVED,
    INVOICE_DRAFT,
    INVOICE_PAID,
    PAYABLE_APPROVED,
    PAYABLE_BILLED_TO_CLIENT,
    PAYABLE_UNBILLED,
    PAYMENT_RELEASED,
    PAYMENT_WITHHELD,
    POSTURE_HOLD,
    POSTURE_OPEN,
    SUBCONTRACT_CLOSED,
    SUBCONTRACT_EXECUTED,
)
from test_helpers.factories import (
    certification_payload,
    findings_payload,
    invoice_payload,
)
from test_helpers.fixtures import (
    activate_project,
    add_approved_payable,
    add_approved_time_entry,
    add_executed_subcontract,
    add_percent_phase,
    build_active_project,
    client_review,
    create_project,
    create_public_client,
    prepare_invoice,
    project_version,
    publish_labor_rate,
    read_payable,
    read_phase,
    read_project,
    read_subcontract,
    record_payment,
    set_clock,
    set_multiplier,
    submit_certification,
    submit_invoice,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    CONTROLLER,
    CONTROLLER_CERTIFIER,
    CONTROLLER_PREPARER,
)
from test_helpers.types import ProjectContext

FINDINGS_TEXT = "Indirect pool includes an unsupported bonus accrual; resubmit with schedules"


def _two_subconsultants_on_one_phase(api):
    """
    An ACTIVE private-client project whose single leaf phase carries two executed
    subcontracts differing only in their pay-when-paid terms, each with one
    approved payable drawn against it.
    """
    ctx = build_active_project(api, phase_overrides={"consultant_budget": 100000.00})
    pay_when_paid = add_executed_subcontract(
        api,
        ctx,
        consultant_name="Halcyon MEP",
        committed_amount=20000.00,
        pay_when_paid=True,
    )
    unconditional = add_executed_subcontract(
        api,
        ctx,
        consultant_name="Cedar Structural",
        committed_amount=30000.00,
        pay_when_paid=False,
    )
    held = add_approved_payable(
        api, pay_when_paid["id"], amount=20000.00, invoice_date="2026-05-20"
    )
    free = add_approved_payable(
        api, unconditional["id"], amount=30000.00, invoice_date="2026-05-21"
    )
    return ctx, pay_when_paid, unconditional, held, free


def _public_agency_project_with_one_approved_line(api):
    """
    An ACTIVE public-agency project carrying a single approved timesheet line of
    10.00 hours at a raw cost rate of 62.50 against a multiplier of 2.5000.
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_public_client(api)
    publish_labor_rate(api)
    project = create_project(
        api,
        client["id"],
        name="Transit Center Renovation",
        contract_amount=900000.00,
        target_multiplier=2.5000,
    )
    phase = add_percent_phase(api, project["id"])
    set_multiplier(
        api,
        project["id"],
        multiplier=2.5000,
        expected_project_version=project["version"],
    )
    activated = activate_project(api, project["id"])
    ctx = ProjectContext(
        client_id=client["id"],
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        is_public_agency=True,
    )
    entry = add_approved_time_entry(api, ctx, hours=10.00, work_date="2026-05-11")
    return ctx, entry


def _attempt_invoice(api, ctx, period_end="2026-05-31"):
    """Prepare an invoice against the project's current version."""
    version = project_version(api, ctx.project_id)
    return api.create_invoice(
        invoice_payload(ctx.project_id, version, period_end=period_end), ACCOUNTANT
    )


def test_pay_when_paid_release_refused_while_peer_payable_releases_at_once(api):
    """
    Two payables carrying the identical 0.1000 markup, entered and approved by the
    same operators on one phase, diverge on the subconsultant's terms alone: the
    one drawn against a pay-when-paid subcontract is refused release while it
    names no client invoice, while its unconditional peer is paid immediately and
    drives its own subcontract to CLOSED.

    PRD §3.5: "A release attempted on a pay-when-paid subcontract before the client invoice that billed the payable reached `PAID`, including the case where the payable was never billed to the client at all, is refused with `ERR_PAY_WHEN_PAID_NOT_SATISFIED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/payable_release_gated_by_client_invoice_state
    """
    ctx, pay_when_paid, unconditional, held, free = _two_subconsultants_on_one_phase(api)

    assert_payable_markup(held, 0.1000, 2000.00, 22000.00)
    assert_payable_markup(free, 0.1000, 3000.00, 33000.00)
    assert_null(held["client_invoice_id"], "payable.client_invoice_id")
    assert_null(free["client_invoice_id"], "payable.client_invoice_id")

    refused = api.release_consultant_payment(held["id"], CONTROLLER)
    validate_error(refused, ERR_PAY_WHEN_PAID_NOT_SATISFIED, 409)
    still_withheld = read_payable(api, held["id"])
    assert_payable_axes(
        still_withheld, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_UNBILLED
    )
    assert_subcontract_rollup(
        read_subcontract(api, pay_when_paid["id"]),
        approved_to_date=20000.00,
        released_to_date=0.00,
        committed_remaining=0.00,
        status=SUBCONTRACT_EXECUTED,
    )

    released = validate_success(api.release_consultant_payment(free["id"], CONTROLLER))
    assert_payable_axes(released, PAYABLE_APPROVED, PAYMENT_RELEASED, PAYABLE_UNBILLED)
    assert_subcontract_rollup(
        read_subcontract(api, unconditional["id"]),
        approved_to_date=30000.00,
        released_to_date=30000.00,
        committed_remaining=0.00,
        status=SUBCONTRACT_CLOSED,
    )
    assert_phase_earned_value(
        read_phase(api, ctx.phase_id), consultant_committed_open=20000.00
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=55000.00,
        billed_open=0.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=55000.00,
    )


def test_pay_when_paid_release_refused_while_client_invoice_is_draft_then_approved(api):
    """
    Being billed to the client is not enough. The invoice sweeps both payables and
    links them, yet release stays refused while that invoice sits in DRAFT and is
    refused again once the client has approved it, because only settlement
    satisfies the subconsultant's terms.

    PRD §3.5: "A `Controller` may release explicitly, which requires the payable's `approval_status` to be `APPROVED` and its `payment_status` to be `WITHHELD`, and — when the subcontract's `pay_when_paid` is true — additionally requires that the payable's `client_invoice_id` be non-null and that the client invoice it names have `status` `PAID`."

    Design: Difficulty/cross_entity_state_dependency/payable_release_gated_by_client_invoice_state
    """
    ctx, pay_when_paid, _unconditional, held, _free = _two_subconsultants_on_one_phase(api)

    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert invoice["status"] == INVOICE_DRAFT
    assert_invoice_money(
        invoice,
        labor_billed=0.00,
        expense_billed=0.00,
        consultant_billed=55000.00,
        gross_billed=55000.00,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=2750.00,
        net_due=52250.00,
    )
    assert_swept_counts(
        invoice,
        swept_labor_count=0,
        swept_expense_count=0,
        swept_consultant_count=2,
        backup_missing_count=0,
    )

    while_draft = api.release_consultant_payment(held["id"], CONTROLLER)
    validate_error(while_draft, ERR_PAY_WHEN_PAID_NOT_SATISFIED, 409)
    linked = read_payable(api, held["id"])
    assert_payable_axes(
        linked, PAYABLE_APPROVED, PAYMENT_WITHHELD, PAYABLE_BILLED_TO_CLIENT
    )
    assert linked["client_invoice_id"] == invoice["id"]

    submit_invoice(api, invoice["id"])
    approved = client_review(api, invoice["id"], ctx.client_id, DECISION_APPROVE)
    assert approved["status"] == INVOICE_APPROVED

    while_approved = api.release_consultant_payment(held["id"], CONTROLLER)
    validate_error(while_approved, ERR_PAY_WHEN_PAID_NOT_SATISFIED, 409)
    assert_payable_axes(
        read_payable(api, held["id"]),
        PAYABLE_APPROVED,
        PAYMENT_WITHHELD,
        PAYABLE_BILLED_TO_CLIENT,
    )
    assert_subcontract_rollup(
        read_subcontract(api, pay_when_paid["id"]),
        released_to_date=0.00,
        status=SUBCONTRACT_EXECUTED,
    )
    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=0.00,
        billed_open=55000.00,
        paid_gross_to_date=0.00,
        written_off_gross=0.00,
        total_charge_value=55000.00,
    )


def test_client_settlement_releases_the_withheld_payable_without_a_release_call(api):
    """
    Recording the client's payment is itself the release event: the withheld
    payable moves to RELEASED with no further request naming it, its subcontract's
    released_to_date reaches the full commitment and closes, and the closure frees
    the phase's open consultant commitment.

    PRD §3.5: "The system also releases automatically: when the client invoice carrying the payable reaches `PAID`, or reaches `WRITTEN_OFF`, every payable on it whose `approval_status` is `APPROVED`, whose `payment_status` is `WITHHELD` and whose `billing_status` is `BILLED_TO_CLIENT` moves to `RELEASED`."
    PRD §3.5: "When a subcontract's `released_to_date` reaches or passes its `committed_amount`, the subcontract moves `EXECUTED → CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/payable_release_gated_by_client_invoice_state
    """
    ctx, pay_when_paid, unconditional, held, free = _two_subconsultants_on_one_phase(api)

    validate_success(api.release_consultant_payment(free["id"], CONTROLLER))
    invoice = prepare_invoice(api, ctx, period_end="2026-05-31")
    assert_invoice_money(
        invoice,
        consultant_billed=55000.00,
        gross_billed=55000.00,
        retainage_amount=2750.00,
        net_due=52250.00,
    )
    submit_invoice(api, invoice["id"])
    client_review(api, invoice["id"], ctx.client_id, DECISION_APPROVE)

    settled = record_payment(api, invoice["id"], received_on="2026-06-01")
    assert settled["status"] == INVOICE_PAID
    assert settled["paid_on"] == "2026-06-01"

    assert_payable_axes(
        read_payable(api, held["id"]),
        PAYABLE_APPROVED,
        PAYMENT_RELEASED,
        PAYABLE_BILLED_TO_CLIENT,
    )
    assert_subcontract_rollup(
        read_subcontract(api, pay_when_paid["id"]),
        approved_to_date=20000.00,
        released_to_date=20000.00,
        committed_remaining=0.00,
        status=SUBCONTRACT_CLOSED,
    )
    assert_subcontract_rollup(
        read_subcontract(api, unconditional["id"]),
        released_to_date=30000.00,
        status=SUBCONTRACT_CLOSED,
    )
    assert_phase_earned_value(
        read_phase(api, ctx.phase_id), consultant_committed_open=0.00
    )

    project = read_project(api, ctx.project_id)
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        billed_open=0.00,
        paid_gross_to_date=55000.00,
        written_off_gross=0.00,
        total_charge_value=55000.00,
    )
    assert_billing_posture(project, POSTURE_OPEN)


def test_public_agency_invoicing_held_until_the_current_year_is_certified(api):
    """
    A public-agency project with invoiceable work in progress is held before any
    certification exists, and certifying the prior fiscal year does not free it:
    the certified row publishes a final rate of 1.4500 for 2025, yet the project's
    own ceiling stays null and its posture stays HOLD because the year must match
    the logical clock.

    PRD §2.11: "Otherwise, if the project's client has `is_public_agency` set to true and there exists no `OverheadRateCertification` whose `status` is `CERTIFIED` and whose `fiscal_year` equals the calendar year of the logical clock, the posture is `HOLD`."
    PRD §3.9: "it is the ceiling published by the `CERTIFIED` certification whose `fiscal_year` matches the calendar year of the logical clock, and it is `null` whenever no such certification exists."

    Design: Difficulty/cross_entity_state_dependency/public_invoicing_gated_by_certification_row_state_and_year
    """
    ctx, entry = _public_agency_project_with_one_approved_line(api)
    assert_time_entry_frozen(entry, 625.00, 2.5000, 1562.50)

    held = read_project(api, ctx.project_id)
    assert_billing_posture(held, POSTURE_HOLD)
    assert_null(held["certified_multiplier_ceiling"], "project.certified_multiplier_ceiling")
    assert_project_ledger(
        held,
        unbilled_wip=1562.50,
        billed_open=0.00,
        total_charge_value=1562.50,
        raw_labor_cost_to_date=625.00,
        net_multiplier_achieved=2.5000,
    )

    validate_error(_attempt_invoice(api, ctx), ERR_OVERHEAD_RATE_NOT_CERTIFIED, 409)

    prior_year = submit_certification(
        api,
        fiscal_year=FISCAL_YEAR_2025,
        ytd_months=12,
        direct_labor_base=1000000.00,
        indirect_cost_pool=1500000.00,
        unallowable_costs=50000.00,
    )
    assert_ratio(
        prior_year["provisional_overhead_rate"],
        1.5000,
        "certification.provisional_overhead_rate",
    )
    certified = validate_success(
        api.certify_certification(prior_year["id"], CONTROLLER_CERTIFIER)
    )
    assert certified["status"] == CERT_CERTIFIED
    assert_ratio(
        certified["final_overhead_rate"], 1.4500, "certification.final_overhead_rate"
    )

    still_held = read_project(api, ctx.project_id)
    assert_billing_posture(still_held, POSTURE_HOLD)
    assert_null(
        still_held["certified_multiplier_ceiling"], "project.certified_multiplier_ceiling"
    )
    validate_error(_attempt_invoice(api, ctx), ERR_OVERHEAD_RATE_NOT_CERTIFIED, 409)

    _rows, meta = validate_paginated(
        api.list_invoices(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert_pagination_meta(meta, total_count=0)


def test_submitted_certification_neither_frees_invoicing_nor_admits_a_second_row(api):
    """
    A submitted fiscal-year row carries the higher provisional rate of 1.6500 but
    no final rate at all, so the public-agency project stays held; and because the
    year is now occupied, a second submission for it is refused outright.

    PRD §3.7: "The owning project must be `ACTIVE`, and its `billing_posture` must not be `HOLD` — a public-agency project with no certified overhead rate for the current year is refused here with `ERR_OVERHEAD_RATE_NOT_CERTIFIED` (HTTP 409)."
    PRD §3.9: "At most one certification per `fiscal_year` may exist in `SUBMITTED` or `CERTIFIED` status at a time; a second submission for an already-occupied year is refused with `ERR_CERTIFICATION_YEAR_DUPLICATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/public_invoicing_gated_by_certification_row_state_and_year
    """
    ctx, _entry = _public_agency_project_with_one_approved_line(api)

    submitted = validate_success(
        api.create_certification(
            certification_payload(fiscal_year=FISCAL_YEAR_2026), CONTROLLER_PREPARER
        ),
        201,
    )
    assert submitted["status"] == CERT_SUBMITTED
    assert_ratio(
        submitted["provisional_overhead_rate"],
        1.6500,
        "certification.provisional_overhead_rate",
    )
    assert_null(submitted["final_overhead_rate"], "certification.final_overhead_rate")
    assert_null(
        submitted["certified_multiplier_ceiling"],
        "certification.certified_multiplier_ceiling",
    )

    validate_error(_attempt_invoice(api, ctx), ERR_OVERHEAD_RATE_NOT_CERTIFIED, 409)

    duplicate = api.create_certification(
        certification_payload(fiscal_year=FISCAL_YEAR_2026), CONTROLLER_PREPARER
    )
    validate_error(duplicate, ERR_CERTIFICATION_YEAR_DUPLICATE, 409)

    _rows, meta = validate_paginated(
        api.list_certifications(CONTROLLER, {"fiscal_year": FISCAL_YEAR_2026})
    )
    assert_pagination_meta(meta, total_count=1)

    project = read_project(api, ctx.project_id)
    assert_billing_posture(project, POSTURE_HOLD)
    assert_null(
        project["certified_multiplier_ceiling"], "project.certified_multiplier_ceiling"
    )


def test_returned_findings_keep_the_hold_until_a_corrected_year_is_certified(api):
    """
    Returning an audit finding leaves the year uncertified with no final rate, so
    the public-agency project is still refused an invoice — but it frees the year,
    and the corrected submission certifies at a final rate of 1.5750, publishes a
    ceiling of 2.8325 onto the project, opens its posture and lets exactly one
    invoice through with the pinned retainage of 78.13.

    PRD §3.9: "No final rate is computed — `final_overhead_rate` stays `null` — no `certified_multiplier_ceiling` is published, public-agency invoicing stays blocked, and the certification's `version` increments by 1. Rejection frees the `fiscal_year` slot, so a corrected certification may be submitted for the same year."
    PRD §3.9: "`certified_multiplier_ceiling` is one plus `final_overhead_rate`, multiplied by one plus a profit margin cap of 0.1000, rounded half up to 4 decimal places."

    Design: Difficulty/cross_entity_state_dependency/public_invoicing_gated_by_certification_row_state_and_year
    """
    ctx, _entry = _public_agency_project_with_one_approved_line(api)

    first = submit_certification(api, fiscal_year=FISCAL_YEAR_2026)
    returned = validate_success(
        api.return_certification_findings(
            first["id"], findings_payload(FINDINGS_TEXT), CONTROLLER_CERTIFIER
        )
    )
    assert returned["status"] == CERT_REJECTED
    assert returned["findings"] == FINDINGS_TEXT
    assert_null(returned["final_overhead_rate"], "certification.final_overhead_rate")
    assert_null(
        returned["certified_multiplier_ceiling"],
        "certification.certified_multiplier_ceiling",
    )

    validate_error(_attempt_invoice(api, ctx), ERR_OVERHEAD_RATE_NOT_CERTIFIED, 409)
    assert_billing_posture(read_project(api, ctx.project_id), POSTURE_HOLD)

    replacement = validate_success(
        api.create_certification(
            certification_payload(fiscal_year=FISCAL_YEAR_2026), CONTROLLER_PREPARER
        ),
        201,
    )
    assert replacement["status"] == CERT_SUBMITTED
    certified = validate_success(
        api.certify_certification(replacement["id"], CONTROLLER_CERTIFIER)
    )
    assert certified["status"] == CERT_CERTIFIED
    assert_ratio(
        certified["final_overhead_rate"], 1.5750, "certification.final_overhead_rate"
    )
    assert_ratio(
        certified["certified_multiplier_ceiling"],
        2.8325,
        "certification.certified_multiplier_ceiling",
    )

    opened = read_project(api, ctx.project_id)
    assert_billing_posture(opened, POSTURE_OPEN)
    assert_ratio(
        opened["certified_multiplier_ceiling"],
        2.8325,
        "project.certified_multiplier_ceiling",
    )

    invoice = validate_success(_attempt_invoice(api, ctx), 201)
    assert invoice["status"] == INVOICE_DRAFT
    assert_invoice_money(
        invoice,
        labor_billed=1562.50,
        expense_billed=0.00,
        consultant_billed=0.00,
        gross_billed=1562.50,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=78.13,
        net_due=1484.37,
    )
    assert_swept_counts(
        invoice,
        swept_labor_count=1,
        swept_expense_count=0,
        swept_consultant_count=0,
    )
    assert invoice["revision_round"] == 0

    _rows, meta = validate_paginated(
        api.list_invoices(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert_pagination_meta(meta, total_count=1)
