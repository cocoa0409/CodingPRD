"""
Optimistic concurrency on the owning project.

Exactly two writes key on the project's own mutation counter, and both are
destructive in a way that a stale reader could not see: a successor billing
multiplier truncates the incumbent's effective window, and an invoice sweeps
every eligible unbilled charge into itself. Each token is spent by the write
that consumes it, so a replay is refused even when the write would otherwise
have been legal, and a refused write must leave the incumbent window, the charge
population and every project rollup exactly where it found them.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ERR_STALE_PROJECT_VERSION
from test_helpers.assertions import (
    assert_invoice_money,
    assert_project_ledger,
    assert_ratio,
    assert_swept_counts,
    assert_time_entry_frozen,
)
from test_helpers.constants import (
    INVOICE_DRAFT,
    MULTIPLIER_ACTIVE,
    MULTIPLIER_SUPERSEDED,
    TIME_ENTRY_BILLED,
)
from test_helpers.fixtures import (
    approve_time_entry,
    build_active_project,
    read_project,
    read_time_entry,
    submit_time_entry,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    ACCOUNTANT_ALT,
    ACCOUNTANT_USER_ID,
    CONTROLLER,
    PROJECT_MANAGER,
)

# 4.00 h of architect time at a raw cost rate of 62.50 under a multiplier of
# 3.0500 freezes a raw cost of 250.00 and a billable value of 762.50.
FOUR_HOUR_BILLABLE = 762.50
TWO_HOUR_BILLABLE = 381.25
INCUMBENT_MULTIPLIER = 3.0500
SUCCESSOR_MULTIPLIER = 3.2000


def _project_with_one_approved_line(api):
    # An ACTIVE project whose only multiplier runs open-ended from 2026-01-01,
    # carrying one approved line whose approval has already moved the project on
    # by a mutation nobody addressed to the project directly.
    ctx = build_active_project(api)
    entry = submit_time_entry(api, ctx, hours=4.00, work_date="2026-05-15")
    stale_version = read_project(api, ctx.project_id)["version"]
    approve_time_entry(api, entry["id"], PROJECT_MANAGER)
    return ctx, entry["id"], stale_version


def test_a_stale_project_version_truncates_no_incumbent_multiplier(api):
    """
    A timesheet approval moved the project on, so the version the writer last saw
    is one behind; the successor multiplier is refused and the incumbent keeps its
    open-ended window, its ACTIVE standing and its own counter.

    PRD §2.7: "Each requires a non-optional request field named `expected_project_version` carrying the `version` the client last observed on that `Project`. If the supplied value does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD §2.7: "A successor multiplier legitimately supersedes the incumbent and truncates the incumbent's effective window, so a writer holding a stale view of the project would silently supersede a multiplier it never saw."
    PRD §2.4: "A derived-field refresh counts as a mutation."

    Design: Corner/cross_cutting_layers/stale_project_version_blocks_a_multiplier_from_truncating_what_it_never_saw
    """
    ctx, _entry_id, stale_version = _project_with_one_approved_line(api)

    response = api.create_billing_multiplier(
        f.multiplier_payload(
            ctx.project_id,
            stale_version,
            multiplier=SUCCESSOR_MULTIPLIER,
            effective_from="2026-06-01",
        ),
        CONTROLLER,
    )
    validate_error(response, ERR_STALE_PROJECT_VERSION, 412)

    incumbent = get_success_data(
        api.get_billing_multiplier(ctx.multiplier_id, CONTROLLER)
    )
    assert incumbent["status"] == MULTIPLIER_ACTIVE
    assert incumbent["effective_to"] is None
    assert_ratio(incumbent["multiplier"], INCUMBENT_MULTIPLIER, "multiplier")

    project = read_project(api, ctx.project_id)
    assert project["version"] == stale_version + 1
    assert_project_ledger(
        project, unbilled_wip=FOUR_HOUR_BILLABLE, total_charge_value=FOUR_HOUR_BILLABLE
    )

    _rows, meta = validate_paginated(
        api.list_billing_multipliers(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert meta["total_count"] == 1


def test_the_current_project_version_lets_the_successor_truncate_the_incumbent(api):
    """
    Handed the version the approval left behind, the successor is written, the
    incumbent is truncated to the successor's own start date and turned to
    superseded, and the already-frozen line keeps the multiplier it was billed at.

    PRD §3.2: "When a successor multiplier is created on a project that already has an `ACTIVE` one, the incumbent's `effective_to` is set to the successor's `effective_from` — a half-open truncation, raising no overlap error at all — and the incumbent's `status` becomes `SUPERSEDED`, incrementing that multiplier's `version` by 1."
    PRD §3.2: "Creating a multiplier also increments the owning project's `version` by 1."
    PRD §3.3: "A line may make that round trip any number of times, and its frozen `raw_cost`, `applied_multiplier` and `billable_amount` never change as it does."

    Design: Corner/cross_cutting_layers/stale_project_version_blocks_a_multiplier_from_truncating_what_it_never_saw
    """
    ctx, entry_id, stale_version = _project_with_one_approved_line(api)
    current_version = read_project(api, ctx.project_id)["version"]
    assert current_version == stale_version + 1

    successor = get_success_data(
        api.create_billing_multiplier(
            f.multiplier_payload(
                ctx.project_id,
                current_version,
                multiplier=SUCCESSOR_MULTIPLIER,
                effective_from="2026-06-01",
            ),
            CONTROLLER,
        )
    )
    assert_ratio(successor["multiplier"], SUCCESSOR_MULTIPLIER, "multiplier")
    assert successor["status"] == MULTIPLIER_ACTIVE
    assert successor["effective_from"] == "2026-06-01"
    assert successor["version"] == 1

    incumbent = get_success_data(
        api.get_billing_multiplier(ctx.multiplier_id, CONTROLLER)
    )
    assert incumbent["status"] == MULTIPLIER_SUPERSEDED
    assert incumbent["effective_to"] == "2026-06-01"
    assert incumbent["version"] == 2

    assert read_project(api, ctx.project_id)["version"] == current_version + 1

    frozen = read_time_entry(api, entry_id)
    assert_time_entry_frozen(
        frozen,
        raw_cost=250.00,
        applied_multiplier=INCUMBENT_MULTIPLIER,
        billable_amount=FOUR_HOUR_BILLABLE,
    )


def test_a_multiplier_version_token_is_single_use(api):
    """
    The very token that carried the first successor is replayed for a second one
    whose effective date would otherwise be a legal successor, and it is refused,
    because the first write spent it by moving the project on.

    PRD §2.7: "If the supplied value does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD §3.2: "Creating a multiplier also increments the owning project's `version` by 1."
    PRD §2.8: "10. Optimistic concurrency on the project version — `ERR_STALE_PROJECT_VERSION`."

    Design: Corner/cross_cutting_layers/stale_project_version_blocks_a_multiplier_from_truncating_what_it_never_saw
    """
    ctx, _entry_id, _stale_version = _project_with_one_approved_line(api)
    spent_version = read_project(api, ctx.project_id)["version"]

    get_success_data(
        api.create_billing_multiplier(
            f.multiplier_payload(
                ctx.project_id,
                spent_version,
                multiplier=SUCCESSOR_MULTIPLIER,
                effective_from="2026-06-01",
            ),
            CONTROLLER,
        )
    )

    replay = api.create_billing_multiplier(
        f.multiplier_payload(
            ctx.project_id,
            spent_version,
            multiplier=3.4000,
            effective_from="2026-07-01",
        ),
        CONTROLLER,
    )
    validate_error(replay, ERR_STALE_PROJECT_VERSION, 412)

    rows, meta = validate_paginated(
        api.list_billing_multipliers(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows].count(MULTIPLIER_ACTIVE) == 1
    assert all(float(row["multiplier"]) != 3.4000 for row in rows)


# The first sweep bills 762.50 plus 381.25; a 0.0500 retainage on 1143.75
# withholds 57.19 (round half up of 57.1875) and leaves 1086.56 net due.
FIRST_SWEEP_GROSS = 1143.75
FIRST_SWEEP_RETAINAGE = 57.19
FIRST_SWEEP_NET_DUE = 1086.56
SECOND_SWEEP_RETAINAGE = 19.06
SECOND_SWEEP_NET_DUE = 362.19


def _project_with_two_billable_lines_and_one_pending(api):
    # Two approved unbilled lines inside the billing period plus a third line
    # still awaiting approval, which no sweep may claim.
    ctx = build_active_project(api)
    first = submit_time_entry(api, ctx, hours=4.00, work_date="2026-05-11")
    approve_time_entry(api, first["id"], PROJECT_MANAGER)
    second = submit_time_entry(api, ctx, hours=2.00, work_date="2026-05-12")
    approve_time_entry(api, second["id"], PROJECT_MANAGER)
    third = submit_time_entry(api, ctx, hours=2.00, work_date="2026-05-20")
    return ctx, first["id"], second["id"], third["id"]


def test_two_accountants_on_one_project_version_cannot_both_bill_it(api):
    """
    The first preparation sweeps both approved lines and spends the version it was
    handed; a second accountant holding that same version is refused, and the
    refusal leaves no draft behind, claims no charge and moves no rollup.

    PRD §2.7: "Each requires a non-optional request field named `expected_project_version` carrying the `version` the client last observed on that `Project`. If the supplied value does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD §2.7: "Invoice preparation sweeps every eligible unbilled charge into itself, so a writer holding a stale view of the project would bill a charge population it never observed."
    PRD §3.7: "The sweep's side effects are that every swept time entry moves to `BILLED` with its `billed_invoice_id` set to this invoice, every swept expense moves to `BILLED` with its `billed_invoice_id` set, every swept payable moves to `BILLED_TO_CLIENT` with its `client_invoice_id` set, the project's `unbilled_wip` falls to whatever residual remains and its `billed_open` rises by `gross_billed`, and the project's `version` increments by 1."

    Design: Corner/cross_cutting_layers/invoice_creation_spends_its_version_token_and_a_replay_sweeps_nothing
    """
    ctx, first_id, second_id, third_id = _project_with_two_billable_lines_and_one_pending(
        api
    )
    observed_version = read_project(api, ctx.project_id)["version"]

    invoice = get_success_data(
        api.create_invoice(
            f.invoice_payload(ctx.project_id, observed_version, period_end="2026-05-31"),
            ACCOUNTANT,
        ),
        201,
    )
    assert invoice["status"] == INVOICE_DRAFT
    assert invoice["prepared_by_user_id"] == ACCOUNTANT_USER_ID
    assert_invoice_money(
        invoice,
        labor_billed=FIRST_SWEEP_GROSS,
        expense_billed=0.00,
        consultant_billed=0.00,
        gross_billed=FIRST_SWEEP_GROSS,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=FIRST_SWEEP_RETAINAGE,
        net_due=FIRST_SWEEP_NET_DUE,
    )
    assert_swept_counts(invoice, swept_labor_count=2, swept_expense_count=0)

    replay = api.create_invoice(
        f.invoice_payload(ctx.project_id, observed_version, period_end="2026-05-31"),
        ACCOUNTANT_ALT,
    )
    validate_error(replay, ERR_STALE_PROJECT_VERSION, 412)

    _rows, meta = validate_paginated(
        api.list_invoices(CONTROLLER, {"project_id": ctx.project_id})
    )
    assert meta["total_count"] == 1

    for entry_id in (first_id, second_id):
        swept = read_time_entry(api, entry_id)
        assert swept["status"] == TIME_ENTRY_BILLED
        assert swept["billed_invoice_id"] == invoice["id"]
    assert read_time_entry(api, third_id)["billed_invoice_id"] is None

    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=0.00,
        billed_open=FIRST_SWEEP_GROSS,
        written_off_gross=0.00,
        total_charge_value=FIRST_SWEEP_GROSS,
    )


def test_a_fresh_project_version_bills_only_the_charge_the_first_sweep_left(api):
    """
    Approving the third line moves the project on again, and the accountant who
    reads that newer version bills the residual charge alone: the two lines the
    first sweep already claimed are not billed twice, and the conserved charge
    total across both invoices is the whole of the approved labour.

    PRD §2.7: "Each requires a non-optional request field named `expected_project_version` carrying the `version` the client last observed on that `Project`. If the supplied value does not equal the project's current `version`, the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
    PRD §3.7: "`labor_billed` is the sum of `billable_amount` over time entries whose `status` is `APPROVED`, whose `billed_invoice_id` is null and whose `work_date` is on or before `period_end`."
    PRD §3.7: "Third, `retainage_amount` is keyed on the **post-discount** base and never on `gross_billed` itself: it is `gross_billed` less `discount_amount`, multiplied by the client's `retainage_pct`, rounded half up to 2 decimal places."

    Design: Corner/cross_cutting_layers/invoice_creation_spends_its_version_token_and_a_replay_sweeps_nothing
    """
    ctx, first_id, second_id, third_id = _project_with_two_billable_lines_and_one_pending(
        api
    )
    first_invoice = get_success_data(
        api.create_invoice(
            f.invoice_payload(
                ctx.project_id,
                read_project(api, ctx.project_id)["version"],
                period_end="2026-05-31",
            ),
            ACCOUNTANT,
        ),
        201,
    )

    approve_time_entry(api, third_id, PROJECT_MANAGER)
    refreshed_version = read_project(api, ctx.project_id)["version"]

    second_invoice = get_success_data(
        api.create_invoice(
            f.invoice_payload(ctx.project_id, refreshed_version, period_end="2026-05-31"),
            ACCOUNTANT_ALT,
        ),
        201,
    )
    assert second_invoice["id"] != first_invoice["id"]
    assert_invoice_money(
        second_invoice,
        labor_billed=TWO_HOUR_BILLABLE,
        expense_billed=0.00,
        consultant_billed=0.00,
        gross_billed=TWO_HOUR_BILLABLE,
        volume_discount_pct=0.0000,
        discount_amount=0.00,
        retainage_amount=SECOND_SWEEP_RETAINAGE,
        net_due=SECOND_SWEEP_NET_DUE,
    )
    assert_swept_counts(second_invoice, swept_labor_count=1, swept_expense_count=0)

    for entry_id in (first_id, second_id):
        assert read_time_entry(api, entry_id)["billed_invoice_id"] == first_invoice["id"]
    residual = read_time_entry(api, third_id)
    assert residual["status"] == TIME_ENTRY_BILLED
    assert residual["billed_invoice_id"] == second_invoice["id"]

    assert_project_ledger(
        read_project(api, ctx.project_id),
        unbilled_wip=0.00,
        billed_open=1525.00,
        written_off_gross=0.00,
        total_charge_value=1525.00,
    )
