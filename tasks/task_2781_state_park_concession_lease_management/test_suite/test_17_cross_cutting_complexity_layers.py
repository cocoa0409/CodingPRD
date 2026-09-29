"""Optimistic-concurrency coverage: the two writes that carry
expected_lease_version, and the precision of the lease's own counter."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_cents_equals,
    assert_fields,
    assert_lease_state,
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


def _refusal(response, expected_error_id: str, expected_status: int) -> None:
    assert response.status_code == expected_status, (
        f"expected HTTP {expected_status} for {expected_error_id}, "
        f"got {response.status_code}"
    )
    validate_error(response, expected_error_id, expected_status)


def _total(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_reconciliation_creation_on_a_stale_lease_version_is_refused(api):
    """PRD §2.7: "In both cases the client must send `expected_lease_version` — a required, non-optional integer field carrying the `version` value the client last observed on the `Lease` named by the request's `lease_id`."
    PRD §2.7: "If that number does not equal the lease's current `version`, the write is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412) and nothing is created or modified."
    PRD §2.7: "The first is the creation of a fee reconciliation."
    PRD §2.9: "**Lease version currency** — `expected_lease_version` equals the lease's current `version`, else `ERR_STALE_LEASE_VERSION` (HTTP 412). Applies to fee-reconciliation creation and operating-plan creation."
    PRD §3.5: "Neither of the lease's two status dimensions moves, but the lease's `version` advances by one, which matters to any client holding an `expected_lease_version` from before the filing."

    Design: Corner/cross_cutting_complexity_layers/reconciliation_create_on_a_stale_lease_version_is_rejected
    """
    ctx = X.setup_lease_with_season(api)
    X.set_clock(api, "2027-07-02T00:00:00Z")
    for period in MONTHS:
        report = X.file_report(
            api, ctx["lease_id"], ctx["offeror_id"], **dict(period, **MONTHLY_RECEIPTS)
        )
        X.accept_report(api, report["id"], 2150000)

    X.set_clock(api, "2028-03-05T00:00:00Z")
    stale_version = X.lease_version(api, ctx["lease_id"])
    refiled = get_success_data(
        api.record_insurance_certificate(
            ctx["lease_id"],
            F.insurance_certificate_payload("2029-06-30"),
            X.exec_officer_headers(),
        )
    )
    assert_version_is(refiled, stale_version + 1)
    assert_lease_state(refiled, contract_status="ACTIVE", compliance_status="COMPLIANT")

    _refusal(
        api.create_reconciliation(
            F.reconciliation_payload(
                ctx["lease_id"],
                stale_version,
                lease_year_start="2027-03-01",
                lease_year_end="2028-02-29",
            ),
            X.exec_officer_headers(),
        ),
        "ERR_STALE_LEASE_VERSION",
        412,
    )

    assert _total(
        api.list_reconciliations(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
    ) == 0, "a stale write creates nothing"
    lease = X.read_lease(api, ctx["lease_id"])
    assert_version_is(lease, stale_version + 1)
    assert_cents_equals(
        lease["outstanding_fee_balance_cents"], 0, "outstanding_fee_balance_cents"
    )
    assert_lease_state(lease, contract_status="ACTIVE", compliance_status="COMPLIANT")


def test_operating_plan_submission_on_a_stale_lease_version_is_refused(api):
    """PRD §2.7: "If that number does not equal the lease's current `version`, the write is rejected with `ERR_STALE_LEASE_VERSION` (HTTP 412) and nothing is created or modified."
    PRD §2.7: "The second is the submission of an operating plan."
    PRD §2.7: "A newly submitted plan is legitimate from any active lease, so no state precondition covers a client working from an outdated view of the lease's season calendar, rate ceilings or compliance posture; requiring the version forces that client to re-read the lease first."
    PRD §3.6: "Because a submission is legitimate from any active lease, the request must also carry `expected_lease_version` as described in §2.7, and a successful submission advances the lease's `version` by one in addition to creating the plan in `SUBMITTED`."
    PRD §3.5: "A `ContractingOfficer` may record the certificate currently on file at any point while the lease's `contract_status` is `PENDING_EXECUTION`, `ACTIVE` or `HOLDOVER`, supplying a new `insurance_expires_on` and optionally a new `carrier_name`."

    Design: Corner/cross_cutting_complexity_layers/operating_plan_create_on_a_stale_lease_version_is_rejected
    """
    ctx = X.setup_active_lease(api)
    stale_version = X.lease_version(api, ctx["lease_id"])
    recertified = get_success_data(
        api.record_insurance_certificate(
            ctx["lease_id"],
            F.insurance_certificate_payload("2029-06-30"),
            X.exec_officer_headers(),
        )
    )
    assert_version_is(recertified, stale_version + 1)

    _refusal(
        api.create_operating_plan(
            F.operating_plan_payload(ctx["lease_id"], stale_version),
            X.concessionaire_headers(ctx["offeror_id"]),
        ),
        "ERR_STALE_LEASE_VERSION",
        412,
    )

    assert _total(
        api.list_operating_plans(X.award_officer_headers(), {"lease_id": ctx["lease_id"]})
    ) == 0, "a stale submission leaves no plan behind"
    lease = X.read_lease(api, ctx["lease_id"])
    assert_version_is(lease, stale_version + 1)
    assert_lease_state(lease, contract_status="ACTIVE")
    assert_fields(lease, {"insurance_expires_on": "2029-06-30"})

    fresh = X.submit_operating_plan(api, ctx["lease_id"], ctx["offeror_id"])
    assert_status(fresh, "SUBMITTED")
    assert_version_is(X.read_lease(api, ctx["lease_id"]), stale_version + 2)


def test_the_lease_counter_advances_only_on_writes_that_touch_the_lease_row(api):
    """PRD §2.5: "A newly created record has `version` 1 and `updated_at` equal to `created_at`; every subsequent mutation of that record advances `version` by exactly one and refreshes `updated_at` to the logical clock instant at which the mutation was applied."
    PRD §2.7: "No other endpoint takes a version field."
    PRD §2.7: "Both of these writes advance `Lease.version` by one when they succeed, which means a client performing two of them in sequence must re-read the lease between them."
    PRD §3.5: "On success the three supplied fields are persisted, `executed_by_user_id` records the acting `X-User-ID`, and the lease's `version` advances by one."
    PRD §3.6: "Approval belongs to a `ContractingOfficer` and moves the plan `SUBMITTED → APPROVED`."
    PRD §3.8: "On success the remittance is persisted and three lease ledger fields move at once — `reported_receipts_ytd_cents` rises by the report's `total_receipts_cents`, `remitted_fee_ytd_cents` rises by the logged remittance, and `maintenance_reserve_balance_cents` rises by `maintenance_reserve_due_cents` — with the report and the lease each advancing their `version` by one."
    PRD §3.8: "The report is created in `SUBMITTED`."

    Design: Corner/cross_cutting_complexity_layers/lease_version_advances_only_on_writes_that_touch_the_lease_row
    """
    ctx = X.setup_awarded_lease(api)
    assert_version_is(ctx["lease"], 1)
    X.post_bond(api, ctx["bond_id"], ctx["offeror_id"], 3000000)

    executed = X.execute_lease(api, ctx["lease_id"])
    assert_version_is(executed, 2)

    plan = X.submit_operating_plan(api, ctx["lease_id"], ctx["offeror_id"])
    assert_version_is(plan, 1)
    assert_version_is(X.read_lease(api, ctx["lease_id"]), 3)

    approved = X.approve_operating_plan(api, plan["id"])
    assert_status(approved, "APPROVED")
    assert_version_is(approved, 2)
    assert_version_is(X.read_lease(api, ctx["lease_id"]), 3)

    X.set_clock(api, "2027-07-02T00:00:00Z")
    report = X.file_report(
        api, ctx["lease_id"], ctx["offeror_id"], **dict(MONTHS[0], **MONTHLY_RECEIPTS)
    )
    assert_status(report, "SUBMITTED")
    assert_version_is(X.read_lease(api, ctx["lease_id"]), 3)

    response = api.accept_report(
        report["id"], F.accept_report_payload(2150000), X.exec_officer_headers()
    )
    validate_success(response, 200)
    assert_status(get_success_data(response), "ACCEPTED")

    lease = X.read_lease(api, ctx["lease_id"])
    assert_version_is(lease, 4)
    assert_cents_equals(
        lease["reported_receipts_ytd_cents"], 40000000, "reported_receipts_ytd_cents"
    )
    assert_cents_equals(lease["remitted_fee_ytd_cents"], 2150000, "remitted_fee_ytd_cents")
    assert_cents_equals(
        lease["maintenance_reserve_balance_cents"], 200000, "maintenance_reserve_balance_cents"
    )
