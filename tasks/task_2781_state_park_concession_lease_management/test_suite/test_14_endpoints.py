"""Endpoint coverage: creation, detail read and filtered listing agreeing on the
same row, and the ledger rollups a lease read exposes."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_freshly_created,
    assert_lease_state,
    assert_null,
    assert_pagination_meta,
    assert_status,
    assert_version_is,
)

MONTHLY_RECEIPTS = {
    "lodging_receipts_cents": 10000000,
    "food_beverage_receipts_cents": 20000000,
    "retail_receipts_cents": 8000000,
    "activity_receipts_cents": 2000000,
}
MONTHS = (
    {"period_start": "2027-04-01", "period_end": "2027-05-01"},
    {"period_start": "2027-05-01", "period_end": "2027-06-01"},
    {"period_start": "2027-06-01", "period_end": "2027-07-01"},
)
QUARTER = {"period_start": "2027-04-01", "period_end": "2027-07-01"}


def _lease_with_three_accepted_months(api):
    """An ACTIVE lease whose first quarter is fully reported and paid: three
    accepted months of 40,000,000 each at 2,150,000 of franchise fee."""
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    report_ids = []
    for period in MONTHS:
        report = X.file_report(
            api, ctx["lease_id"], ctx["offeror_id"], **dict(period, **MONTHLY_RECEIPTS)
        )
        assert_cents_equals(report["total_receipts_cents"], 40000000, "total_receipts_cents")
        X.accept_report(api, report["id"], 2150000)
        report_ids.append(report["id"])
    ctx["report_ids"] = report_ids
    return ctx


def _reconciled_lease_year_one(api, clock):
    """The same lease, reconciled for lease year 1 at the supplied clock: an
    invoice of 1,300,000 due 2028-03-30."""
    ctx = _lease_with_three_accepted_months(api)
    X.set_clock(api, clock)
    recon = X.create_reconciliation(
        api, ctx["lease_id"], lease_year_start="2027-03-01", lease_year_end="2028-02-29"
    )
    assert_cents_equals(
        recon["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )
    assert_status(recon, "PENDING_PAYMENT")
    ctx.update({"recon": recon, "recon_id": recon["id"]})
    return ctx


def test_audit_engagement_creation_read_and_lease_filter_agree_on_one_row(api):
    """PRD §3.8: "An engagement names the `lease_id`, the half-open window `audit_period_start` through `audit_period_end`, and a `scope_note`; the lease may be `ACTIVE`, `HOLDOVER` or `EXPIRED`, and any other `contract_status` earns `ERR_LEASE_STATUS_INVALID`."
    PRD §3.8: "The engagement opens in `OPENED`."
    PRD §3.8: "Beginning fieldwork moves it `OPENED → FIELDWORK` and freezes the baseline: `reported_gross_receipts_cents` becomes the sum of `total_receipts_cents` over the lease's `ACCEPTED` reports whose half-open periods lie inside the audit window."
    PRD §2.5: "Field visibility follows a simple rule: every field named in this document, whether the client supplied it, the system stamped it, or a formula computed it, is present in the resource object returned for that entity."
    PRD §2.5: "Computed and system fields that have not yet been established are returned as null rather than omitted."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."
    PRD §2.3: "Performance bonds, operating plans and audit engagements each accept `lease_id` and `status`."
    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they were applied, `total_count` as the number of rows matching the filters before pagination, and `has_more` as true when rows remain beyond the current page."
    PRD §2.3: "`limit` defaults to 10 when absent, may not be smaller than 1 and may not be larger than 100."
    PRD §2.3: "`offset` defaults to 0 and may not be negative."

    Design: Corner/endpoints/audit_engagement_create_read_and_lease_filtered_list_agree
    """
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    report = X.file_report(
        api, ctx["lease_id"], ctx["offeror_id"], **dict(QUARTER, **MONTHLY_RECEIPTS)
    )
    X.accept_report(api, report["id"], 2150000)

    response = api.create_audit(
        F.audit_payload(
            ctx["lease_id"],
            audit_period_start="2027-04-01",
            audit_period_end="2027-07-01",
            scope_note="Routine gross receipts verification for the first operating quarter.",
        ),
        X.auditor_headers(),
    )
    validate_success(response, 201)
    audit = get_success_data(response)
    assert_freshly_created(audit)
    assert_fields(
        audit,
        {
            "lease_id": ctx["lease_id"],
            "audit_period_start": "2027-04-01",
            "audit_period_end": "2027-07-01",
            "scope_note": "Routine gross receipts verification for the first operating quarter.",
            "status": "OPENED",
        },
    )
    assert_null(
        audit,
        "reported_gross_receipts_cents",
        "adjusted_gross_receipts_cents",
        "underreport_pct",
        "penalty_applies",
        "finding_note",
        "contest_basis",
        "withdrawal_basis",
    )

    stored = get_success_data(api.get_audit(audit["id"], X.auditor_headers()))
    assert stored == audit, f"detail read diverged from the created row: {stored!r}"
    assert_version_is(stored, 1)

    rows, meta = validate_paginated(
        api.list_audits(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
    )
    assert_pagination_meta(meta, total_count=1, limit=10, offset=0, has_more=False)
    assert len(rows) == 1, f"expected one engagement on the lease, got {len(rows)}"
    assert_fields(rows[0], {"id": audit["id"], "lease_id": ctx["lease_id"], "status": "OPENED"})


def test_settling_the_invoice_clears_both_the_row_and_the_lease_balance(api):
    """PRD §3.8: "The concessionaire clears the invoice by settling it, moving `PENDING_PAYMENT → SETTLED`, and the payment must be exact: `payment_amount_cents` must equal `additional_fee_due_cents`, else `ERR_PAYMENT_AMOUNT_MISMATCH`."
    PRD §3.8: "Settlement recomputes the lease's outstanding balance, and if the reconciliation carries an `audit_engagement_id` whose audit is in `FINAL`, that audit is closed out in the same request, moving `FINAL → CLOSED`."
    PRD §3.8: "The lease's `outstanding_fee_balance_cents` — the sum of `additional_fee_due_cents` over the lease's reconciliations still in `PENDING_PAYMENT` — is recomputed, and the lease's `version` advances by one."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."
    PRD §2.10: "Both start at their initial values the moment the lease is minted: `PENDING_EXECUTION` and `COMPLIANT`."

    Design: Corner/endpoints/settle_action_clears_the_reconciliation_and_the_lease_balance
    """
    ctx = _reconciled_lease_year_one(api, "2028-03-05T00:00:00Z")

    response = api.settle_reconciliation(
        ctx["recon_id"],
        F.settle_payload(1300000),
        X.concessionaire_headers(ctx["offeror_id"]),
    )
    validate_success(response, 200)
    settled = get_success_data(response)
    assert_status(settled, "SETTLED")
    assert_cents_equals(
        settled["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )
    assert_null(settled, "audit_engagement_id")
    assert_version_is(settled, 2)

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="COMPLIANT")


def test_an_officer_notice_carries_the_reconciliation_that_provoked_it(api):
    """PRD §3.9: "A `ContractingOfficer` issues a **compliance action** against a lease whose `contract_status` is `ACTIVE` or `HOLDOVER` and whose `compliance_status` is `COMPLIANT`, naming the `lease_id`, an `action_type` of `FEE_DELINQUENCY`, `OPERATING_STANDARD` or `INSURANCE_LAPSE`, a `deficiency_note` describing the shortfall, a `cure_deadline` instant, and optionally the `reconciliation_id` of the unpaid invoice that provoked it."
    PRD §3.9: "The action is created in `NOTICE_ISSUED` with `origin` set to `AGENCY_ISSUED` — the value that distinguishes an officer's notice from the `SYSTEM_ISSUED` notices the audit cascade of §3.8 mints — and the lease's `compliance_status` moves `COMPLIANT → DEFICIENT` with its `version` advancing by one."
    PRD §3.9: "`draw_amount_cents` and `cure_note` are null at issuance."
    PRD §2.3: "Compliance actions accept `lease_id`, `reconciliation_id`, `status` and `origin`."
    PRD §4: "Lists compliance actions; filter by lease or by the reconciliation that provoked them."

    Design: Corner/endpoints/compliance_notice_links_the_reconciliation_that_provoked_it
    """
    ctx = _reconciled_lease_year_one(api, "2028-03-05T00:00:00Z")

    response = api.create_compliance_action(
        F.compliance_action_payload(
            ctx["lease_id"],
            action_type="FEE_DELINQUENCY",
            cure_deadline="2028-05-01T00:00:00Z",
            reconciliation_id=ctx["recon_id"],
            deficiency_note="Lease year 1 franchise fee true-up unpaid past the due date.",
        ),
        X.award_officer_headers(),
    )
    validate_success(response, 201)
    action = get_success_data(response)
    assert_freshly_created(action)
    assert_fields(
        action,
        {
            "lease_id": ctx["lease_id"],
            "action_type": "FEE_DELINQUENCY",
            "status": "NOTICE_ISSUED",
            "origin": "AGENCY_ISSUED",
            "reconciliation_id": ctx["recon_id"],
            "cure_deadline": "2028-05-01T00:00:00Z",
        },
    )
    assert_null(action, "draw_amount_cents", "cure_note")

    rows, meta = validate_paginated(
        api.list_compliance_actions(
            X.award_officer_headers(), {"reconciliation_id": ctx["recon_id"]}
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert len(rows) == 1, f"expected one notice on the invoice, got {len(rows)}"
    assert_fields(rows[0], {"id": action["id"], "reconciliation_id": ctx["recon_id"]})

    assert_lease_state(
        X.read_lease(api, ctx["lease_id"]),
        contract_status="ACTIVE",
        compliance_status="DEFICIENT",
    )
    invoice = get_success_data(
        api.get_reconciliation(ctx["recon_id"], X.award_officer_headers())
    )
    assert_status(invoice, "PENDING_PAYMENT")


def test_reading_a_lease_reports_the_live_ledger_rollups_and_mutates_nothing(api):
    """PRD §3.8: "On success the remittance is persisted and three lease ledger fields move at once — `reported_receipts_ytd_cents` rises by the report's `total_receipts_cents`, `remitted_fee_ytd_cents` rises by the logged remittance, and `maintenance_reserve_balance_cents` rises by `maintenance_reserve_due_cents` — with the report and the lease each advancing their `version` by one."
    PRD §3.8: "`maintenance_reserve_due_cents` is one half of one percent of `total_receipts_cents`, rounded half up to whole cents."
    PRD §3.8: "The reserve is an accrual, not cash — its running balance, `maintenance_reserve_balance_cents` on the lease, is the sum of `maintenance_reserve_due_cents` over the lease's `ACCEPTED` and `RESTATED` reports less the `approved_cost_cents` of every reserve-funded improvement that has reached `APPROVED` or beyond."
    PRD §3.8: "The lease's `outstanding_fee_balance_cents` — the sum of `additional_fee_due_cents` over the lease's reconciliations still in `PENDING_PAYMENT` — is recomputed, and the lease's `version` advances by one."
    PRD §3.7: "On success both fields are persisted, the park's `open_closure_window_count` falls by one because the site has reopened, and the lease's `capital_investment_completed_cents` rises by the lesser of `actual_cost_cents` and `approved_cost_cents`."
    PRD §2.5: "Computed and system fields that have not yet been established are returned as null rather than omitted."
    PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."
    PRD §2.10: "Both start at their initial values the moment the lease is minted: `PENDING_EXECUTION` and `COMPLIANT`."
    PRD §4: "Reads one lease including every ledger field and both status dimensions."

    Design: Corner/endpoints/lease_read_exposes_the_live_ledger_rollups_without_mutating_them
    """
    ctx = _lease_with_three_accepted_months(api)

    owner_headers = X.concessionaire_headers(ctx["offeror_id"])
    response = api.get_lease(ctx["lease_id"], owner_headers)
    validate_success(response, 200)
    lease = get_success_data(response)
    assert_cents_equals(
        lease["reported_receipts_ytd_cents"], 120000000, "reported_receipts_ytd_cents"
    )
    assert_cents_equals(lease["remitted_fee_ytd_cents"], 6450000, "remitted_fee_ytd_cents")
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 600000, "maintenance_reserve_balance_cents"
    )
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
    assert_cents_equals(
        lease["capital_investment_completed_cents"], 0, "capital_investment_completed_cents"
    )
    assert_null(
        lease,
        "possessory_interest_value_cents",
        "transfer_settlement_net_cents",
        "transfer_settlement_deficiency_cents",
    )
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="COMPLIANT")

    again = get_success_data(api.get_lease(ctx["lease_id"], owner_headers))
    assert again == lease, f"a read moved the lease: {again!r}"


def test_a_bond_draw_off_by_one_cent_settles_no_invoice(api):
    """PRD §3.9: "Three conditions are checked in order: the lease's bond must be in `ACTIVE` or `PARTIALLY_DRAWN`, else `ERR_BOND_NOT_ACTIVE`; the logical clock must be strictly after the action's `cure_deadline`, else `ERR_CURE_PERIOD_OPEN` — a draw ordered at the very instant the deadline falls is premature; and the requested `draw_amount_cents` must not exceed the bond's current `available_balance_cents`, else `ERR_DRAW_EXCEEDS_BOND`, which is tested against the live balance so that a second draw sees what the first one left."
    PRD §3.9: "**Hop two** moves the money on the bond: `available_balance_cents` falls by the drawn amount and `drawn_total_cents` rises by the same amount, while `penal_sum_cents` never changes — the penal sum is the face value of the instrument, not a running balance."
    PRD §3.9: "If the remaining `available_balance_cents` is at or above that floor the bond lands in `PARTIALLY_DRAWN`, and the agency's security is still adequate; if it falls strictly below the floor the bond lands in `INSUFFICIENT`."
    PRD §3.9: "Separately, and regardless of where the bond landed, if the action carries a `reconciliation_id` and `draw_amount_cents` exactly equals that reconciliation's `additional_fee_due_cents`, the draw is treated as payment: that reconciliation moves `PENDING_PAYMENT → SETTLED` and the lease's `outstanding_fee_balance_cents` is recomputed."
    PRD §3.9: "A draw for any other amount settles nothing, even a draw for more than the invoice."

    Design: Corner/endpoints/bond_draw_settles_the_linked_reconciliation_only_on_an_exact_amount_match
    """
    ctx = _reconciled_lease_year_one(api, "2028-04-01T00:00:00Z")
    action = X.issue_compliance_action(
        api,
        ctx["lease_id"],
        action_type="FEE_DELINQUENCY",
        cure_deadline="2028-05-01T00:00:00Z",
        reconciliation_id=ctx["recon_id"],
        deficiency_note="Lease year 1 franchise fee true-up unpaid past the due date.",
    )
    X.set_clock(api, "2028-05-02T00:00:00Z")

    response = api.order_bond_draw(
        action["id"], F.order_bond_draw_payload(1300001), X.exec_officer_headers()
    )
    validate_success(response, 200)
    ordered = get_success_data(response)
    assert_status(ordered, "BOND_DRAW_ORDERED")
    assert_cents_equals(ordered["draw_amount_cents"], 1300001, "draw_amount_cents")

    bond = get_success_data(api.get_bond(ctx["bond_id"], X.award_officer_headers()))
    assert_status(bond, "PARTIALLY_DRAWN")
    assert_cents_equals(bond["drawn_total_cents"], 1300001, "drawn_total_cents")
    assert_cents_equals(bond["available_balance_cents"], 1699999, "available_balance_cents")
    assert_cents_equals(bond["penal_sum_cents"], 3000000, "penal_sum_cents")

    invoice = get_success_data(
        api.get_reconciliation(ctx["recon_id"], X.award_officer_headers())
    )
    assert_status(invoice, "PENDING_PAYMENT")
    assert_cents_equals(
        invoice["additional_fee_due_cents"], 1300000, "additional_fee_due_cents"
    )

    lease = X.read_lease(api, ctx["lease_id"])
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 1300000, "outstanding_fee_balance_cents"
    )
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="DEFICIENT")
