"""
Which refusal an architecture practice hears when one request breaks two rules.

The firm's rejection order is a policy statement, not an implementation detail:
regulatory and compliance safety is adjudicated ahead of fiscal capacity, and
temporal integrity ahead of the structural lookups that price a charge. Both
pairs below are genuinely violated by the same request, so the losing rule is
proved reachable on its own once the winning obstacle is cleared — an empty
sweep on a project whose overhead rate has since been certified, and a missing
labour cost rate on an entry dated outside the closed accounting period.

PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one belonging to the earliest rule in the ladder below."
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_NO_EFFECTIVE_LABOR_RATE,
    ERR_NOTHING_TO_INVOICE,
    ERR_OVERHEAD_RATE_NOT_CERTIFIED,
    ERR_PERIOD_LOCKED,
)
from test_helpers.assertions import (
    assert_billing_posture,
    assert_null,
    assert_outranks,
    assert_pagination_meta,
    assert_project_ledger,
    assert_ratio,
    assert_time_entry_carries_no_money,
)
from test_helpers.constants import (
    CERT_CERTIFIED,
    CLOCK_2026_06_01,
    FISCAL_YEAR_2026,
    POSTURE_HOLD,
    POSTURE_OPEN,
    ROLE_CODE_DESIGNER,
    TIME_ENTRY_SUBMITTED,
)
from test_helpers.factories import invoice_payload, lock_period_payload
from test_helpers.fixtures import (
    activate_project,
    add_percent_phase,
    build_active_project,
    certify_year,
    create_project,
    create_public_client,
    project_version,
    read_project,
    read_time_entry,
    set_clock,
    set_multiplier,
    submit_time_entry,
)
from test_helpers.test_users import ACCOUNTANT, CONTROLLER, PROJECT_MANAGER


def _stand_up_uncertified_public_agency_project(api):
    """
    A public-agency project carrying no charges of any kind and with no overhead
    rate certification anywhere in the firm, so its billing posture is HOLD and an
    invoice prepared against it would also sweep nothing at all.
    """
    set_clock(api, CLOCK_2026_06_01)
    client = create_public_client(api)
    project = create_project(
        api,
        client["id"],
        name="Transit Center Renovation",
        contract_amount=900000.00,
        target_multiplier=2.5000,
    )
    add_percent_phase(api, project["id"])
    set_multiplier(
        api,
        project["id"],
        multiplier=2.5000,
        effective_from="2026-01-01",
        expected_project_version=project["version"],
    )
    activate_project(api, project["id"])
    return client["id"], project["id"]


def test_uncertified_overhead_rate_outranks_the_empty_sweep_on_invoice_preparation(api):
    """
    Preparing an invoice on a public-agency project with no certified overhead
    rate for the current year breaks two rules at once: the compliance gate that
    holds the project, and the fiscal rule that there is nothing to bill because
    the project carries no charges. The compliance refusal must be the one
    returned, and no invoice row is left behind.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one belonging to the earliest rule in the ladder below."
    PRD §2.11: "Otherwise, if the project's client has `is_public_agency` set to true and there exists no `OverheadRateCertification` whose `status` is `CERTIFIED` and whose `fiscal_year` equals the calendar year of the logical clock, the posture is `HOLD`."
    PRD §3.7: "The owning project must be `ACTIVE`, and its `billing_posture` must not be `HOLD` — a public-agency project with no certified overhead rate for the current year is refused here with `ERR_OVERHEAD_RATE_NOT_CERTIFIED` (HTTP 409)."
    PRD §3.7: "`gross_billed` is `labor_billed` plus `consultant_billed` plus `expense_billed`, and if it comes to exactly 0.00 there is no invoice to make: the request is refused with `ERR_NOTHING_TO_INVOICE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/certification_hold_outranks_nothing_to_invoice
    """
    _client_id, project_id = _stand_up_uncertified_public_agency_project(api)
    assert_outranks(ERR_OVERHEAD_RATE_NOT_CERTIFIED, ERR_NOTHING_TO_INVOICE)

    held = read_project(api, project_id)
    assert_billing_posture(held, POSTURE_HOLD)
    assert_null(held["certified_multiplier_ceiling"], "project.certified_multiplier_ceiling")
    assert_project_ledger(
        held, unbilled_wip=0.00, billed_open=0.00, total_charge_value=0.00
    )

    refused = api.create_invoice(
        invoice_payload(project_id, held["version"], period_end="2026-05-31"), ACCOUNTANT
    )
    validate_error(refused, ERR_OVERHEAD_RATE_NOT_CERTIFIED, 409)

    rows, meta = validate_paginated(
        api.list_invoices(CONTROLLER, {"project_id": project_id})
    )
    assert rows == [], f"no invoice may exist after the refusal, got {rows}"
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_certifying_the_fiscal_year_exposes_the_empty_sweep_on_the_same_request(api):
    """
    The losing rule is genuinely violated too. Certifying fiscal 2026 publishes a
    multiplier ceiling of 2.8325, lifts the project's posture from HOLD to OPEN
    and clears the compliance obstacle; the identical preparation request, differing
    only in the refreshed project version it carries, then reports the empty sweep.

    PRD §3.9: "`certified_multiplier_ceiling` is one plus `final_overhead_rate`, multiplied by one plus a profit margin cap of 0.1000, rounded half up to 4 decimal places. On the figures above, the ceiling is 2.8325."
    PRD §3.9: "Third, those projects re-run `billing_posture`, so a project that was held for a missing certification moves from `HOLD` to `OPEN` and becomes invoiceable."
    PRD §3.7: "`gross_billed` is `labor_billed` plus `consultant_billed` plus `expense_billed`, and if it comes to exactly 0.00 there is no invoice to make: the request is refused with `ERR_NOTHING_TO_INVOICE` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/certification_hold_outranks_nothing_to_invoice
    """
    _client_id, project_id = _stand_up_uncertified_public_agency_project(api)

    first_attempt = api.create_invoice(
        invoice_payload(
            project_id, project_version(api, project_id), period_end="2026-05-31"
        ),
        ACCOUNTANT,
    )
    validate_error(first_attempt, ERR_OVERHEAD_RATE_NOT_CERTIFIED, 409)

    certified = certify_year(api, FISCAL_YEAR_2026)
    assert certified["status"] == CERT_CERTIFIED, (
        f"certification.status: expected {CERT_CERTIFIED}, got {certified['status']}"
    )
    assert_ratio(
        certified["final_overhead_rate"], 1.5750, "certification.final_overhead_rate"
    )
    assert_ratio(
        certified["certified_multiplier_ceiling"],
        2.8325,
        "certification.certified_multiplier_ceiling",
    )

    opened = read_project(api, project_id)
    assert_billing_posture(opened, POSTURE_OPEN)
    assert_ratio(
        opened["certified_multiplier_ceiling"],
        2.8325,
        "project.certified_multiplier_ceiling",
    )

    second_attempt = api.create_invoice(
        invoice_payload(project_id, opened["version"], period_end="2026-05-31"),
        ACCOUNTANT,
    )
    validate_error(second_attempt, ERR_NOTHING_TO_INVOICE, 422)

    rows, meta = validate_paginated(
        api.list_invoices(CONTROLLER, {"project_id": project_id})
    )
    assert rows == [], f"no invoice may exist after either refusal, got {rows}"
    assert_pagination_meta(meta, total_count=0, has_more=False)


def _stand_up_locked_period_with_no_rate_for_the_grade(api):
    """
    A project on which no labour cost rate has ever been published for the
    DESIGNER grade, carrying two submitted DESIGNER lines: one dated 2026-03-15,
    inside the accounting period the controller then closes through 2026-03-31,
    and one dated 2026-05-11, safely outside it.
    """
    ctx = build_active_project(
        api, clock=CLOCK_2026_06_01, publish_rate=False, project_overrides={
            "name": "Riverside Library"
        }
    )
    inside_lock = submit_time_entry(
        api, ctx, hours=8.00, work_date="2026-03-15", role_code=ROLE_CODE_DESIGNER
    )
    get_success_data(
        api.lock_period(
            ctx.project_id, lock_period_payload("2026-03-31"), CONTROLLER
        )
    )
    after_lock = submit_time_entry(
        api, ctx, hours=8.00, work_date="2026-05-11", role_code=ROLE_CODE_DESIGNER
    )
    return ctx, inside_lock["id"], after_lock["id"]


def test_closed_accounting_period_outranks_the_missing_labor_cost_rate(api):
    """
    Approving the line dated inside the closed period breaks two rules at once:
    its work date falls on or before the locked-through date, and no labour cost
    rate window covers the DESIGNER grade on that date. Both refusals are 422s,
    and the temporal one must win. The line keeps its state and its money stays
    unwritten, so the project's labour position is untouched.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one belonging to the earliest rule in the ladder below."
    PRD §2.6: "Once set, a charge whose service date falls **on or before** `locked_through_date` may neither be created nor approved: the service date is `work_date` for a time entry, `incurred_on` for an expense and `invoice_date` for a consultant payable."
    PRD §2.6: "The rejection is `ERR_PERIOD_LOCKED` (HTTP 422), and it is reachable on time entry creation, expense creation, consultant payable creation and time entry approval."
    PRD §3.3: "If no rate window covers the pair, the request is refused with `ERR_NO_EFFECTIVE_LABOR_RATE` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/period_lock_outranks_missing_labor_rate
    """
    ctx, inside_lock_id, _after_lock_id = _stand_up_locked_period_with_no_rate_for_the_grade(api)
    assert_outranks(ERR_PERIOD_LOCKED, ERR_NO_EFFECTIVE_LABOR_RATE)

    refused = api.approve_time_entry(inside_lock_id, PROJECT_MANAGER)
    validate_error(refused, ERR_PERIOD_LOCKED, 422)

    entry = read_time_entry(api, inside_lock_id)
    assert entry["status"] == TIME_ENTRY_SUBMITTED, (
        f"time_entry.status: expected {TIME_ENTRY_SUBMITTED}, got {entry['status']}"
    )
    assert_time_entry_carries_no_money(entry)
    assert_null(entry["approved_by_user_id"], "time_entry.approved_by_user_id")

    project = read_project(api, ctx.project_id)
    assert project["locked_through_date"] == "2026-03-31", (
        "project.locked_through_date: expected 2026-03-31, got "
        f"{project['locked_through_date']}"
    )
    assert_project_ledger(
        project,
        unbilled_wip=0.00,
        raw_labor_cost_to_date=0.00,
        total_charge_value=0.00,
        net_multiplier_achieved=0.0000,
    )


def test_line_dated_after_the_lock_surfaces_the_missing_labor_cost_rate(api):
    """
    The losing rule is genuinely violated too. The second line carries the same
    DESIGNER grade and the same 8.00 hours but a work date outside the closed
    period, so the temporal obstacle no longer applies and the approval reports
    the absent labour cost rate instead. It also stays SUBMITTED and carries no
    money, so the firm's raw labour cost remains 0.00.

    PRD §3.3: "If no rate window covers the pair, the request is refused with `ERR_NO_EFFECTIVE_LABOR_RATE` (HTTP 422)"
    PRD §2.6: "Once set, a charge whose service date falls **on or before** `locked_through_date` may neither be created nor approved: the service date is `work_date` for a time entry, `incurred_on` for an expense and `invoice_date` for a consultant payable."

    Design: Difficulty/priority_pair_validation_conflict/period_lock_outranks_missing_labor_rate
    """
    ctx, _inside_lock_id, after_lock_id = _stand_up_locked_period_with_no_rate_for_the_grade(api)

    refused = api.approve_time_entry(after_lock_id, PROJECT_MANAGER)
    validate_error(refused, ERR_NO_EFFECTIVE_LABOR_RATE, 422)

    entry = read_time_entry(api, after_lock_id)
    assert entry["status"] == TIME_ENTRY_SUBMITTED, (
        f"time_entry.status: expected {TIME_ENTRY_SUBMITTED}, got {entry['status']}"
    )
    assert_time_entry_carries_no_money(entry)

    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=0.00,
        billed_open=0.00,
        raw_labor_cost_to_date=0.00,
        earned_revenue_to_date=0.00,
        total_charge_value=0.00,
        net_multiplier_achieved=0.0000,
    )
