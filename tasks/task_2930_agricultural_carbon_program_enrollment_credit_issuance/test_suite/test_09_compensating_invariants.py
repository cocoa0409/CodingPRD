"""Compensations that undo some ledger lines while deliberately preserving others.

Cancelling a batch releases the buffer contribution and voids the unpaid accrual but
never rewinds the serial cursor; terminating an
enrollment returns the acres and voids the unpaid accrual but prices the exit fee from
settled cash only.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_PRACTICE_COOLDOWN_ACTIVE,
)
from test_helpers.assertions import assert_acres, assert_cents, assert_credits
from test_helpers.constants import (
    CLOCK_2027,
    ENROLLMENT_EXIT_REQUESTED,
    ENROLLMENT_TERMINATED,
    FIELD_MAPPED,
    ISSUANCE_CANCELLED,
    PAYMENT_PAID,
    PAYMENT_VOID,
    PERMANENCE_BREACHED,
    POOL_HEALTHY,
    REGISTRY_UNLISTED,
    RUN_ISSUED,
)
from test_helpers.factories import (
    cancellation_payload,
    exit_decision_payload,
    exit_request_payload,
    issue_payload,
)
from test_helpers.test_users import ADMIN_HEADERS, REGISTRY_HEADERS

LEDGER_FIELD = {"field_name": "Ledger Quarter", "county_code": "MO-019"}


def _terminable_enrollment(scenario):
    """A per-acre enrollment with one paid 2026 accrual, one unpaid 2027 accrual, exiting."""
    scenario.active_enrollment(
        field_overrides=LEDGER_FIELD,
        enrollment_overrides={"per_acre_rate_cents": 1000.00},
        per_acre=True,
    )
    paid = scenario.accrue_payment(2026)
    get_success_data(scenario.api.pay_grower_payment(paid["id"], None, ADMIN_HEADERS))
    scenario.set_clock(CLOCK_2027)
    unpaid = scenario.accrue_payment(2027)
    requested = get_success_data(
        scenario.api.request_exit(
            scenario.enrollment_id, exit_request_payload(2028), ADMIN_HEADERS
        )
    )
    assert requested["status"] == ENROLLMENT_EXIT_REQUESTED
    return paid, unpaid


def test_cancellation_releases_the_buffer_and_voids_the_unpaid_accrual(scenario):
    """Cancelling the batch moves the issuance axis alone, empties the pool's live figures
    and voids the per-credit payment the issuance had accrued.

    PRD §3.8: "Third, every grower payment whose `credit_batch_id` names this batch and
    whose `status` is `ACCRUED` moves to `VOID`, and the enrollment's
    `accrued_payment_cents` decreases by each such payment's `net_amount_cents`."

    Design: Difficulty/compensating_invariant/batch_cancellation_compensates_everything_except_serial_counter
    """
    batch = scenario.issued_batch()
    assert_credits(batch["buffer_credits"], 51)
    assert_credits(batch["issued_credits"], 232)
    accrued = scenario.payments_of_batch()
    assert len(accrued) == 1
    assert_cents(accrued[0]["net_amount_cents"], 306240)
    assert_cents(scenario.reload_enrollment()["accrued_payment_cents"], 306240)

    cancelled = get_success_data(
        scenario.api.cancel_batch(
            scenario.batch_id, cancellation_payload(scenario.batch_version), REGISTRY_HEADERS
        )
    )

    assert cancelled["issuance_status"] == ISSUANCE_CANCELLED
    assert cancelled["registry_status"] == REGISTRY_UNLISTED
    pool = scenario.buffer_pool()
    assert_credits(pool["released_total"], 51)
    assert_credits(pool["balance_credits"], 0)
    assert_credits(pool["outstanding_issued_credits"], 0)
    assert_credits(pool["required_reserve_credits"], 0)
    assert pool["pool_status"] == POOL_HEALTHY
    enrollment = scenario.reload_enrollment()
    assert_credits(enrollment["credits_issued_total"], 0)
    assert_cents(enrollment["accrued_payment_cents"], 0)
    voided = get_success_data(scenario.api.get_grower_payment(accrued[0]["id"], ADMIN_HEADERS))
    assert voided["status"] == PAYMENT_VOID


def test_cancellation_never_rewinds_the_serial_cursor(scenario):
    """The serial cursor and the batch's own audit record survive the cancellation untouched,
    while every figure §3.8 names as compensated is wound back.

    PRD §3.8: "The pool's `next_serial_number` is **not** rolled back: serial numbers are
    never reused."

    PRD §3.8: "First, the buffer pool's `released_total` increases by the batch's
    `buffer_credits`, its `balance_credits` and `contributed_total` each decrease by the same
    quantity ... Second, the grower's `lifetime_credits_issued` and the enrollment's
    `credits_issued_total` each decrease by `issued_credits`."

    Design: Difficulty/compensating_invariant/batch_cancellation_compensates_everything_except_serial_counter
    """
    scenario.issued_batch()
    run_id = scenario.run_id

    get_success_data(
        scenario.api.cancel_batch(
            scenario.batch_id, cancellation_payload(scenario.batch_version), REGISTRY_HEADERS
        )
    )

    pool = scenario.buffer_pool()
    assert pool["next_serial_number"] == 233
    assert_credits(pool["released_total"], 51)
    assert_credits(pool["contributed_total"], 0)
    assert_credits(pool["drawn_total"], 0)
    assert_credits(scenario.reload_grower()["lifetime_credits_issued"], 0)
    batch = scenario.reload_batch()
    assert_credits(batch["issued_credits"], 232)
    assert batch["serial_start"] == 1
    assert batch["serial_end"] == 232
    assert scenario.reload_run()["status"] == RUN_ISSUED
    validate_error(
        scenario.api.issue_credits(run_id, issue_payload(2026), ADMIN_HEADERS),
        ERR_INVALID_STATE_TRANSITION, 409,
    )
    assert scenario.buffer_pool()["next_serial_number"] == 233


def test_termination_prices_the_exit_fee_from_settled_cash_only(scenario):
    """One fifth of the commitment was served, so the fee is four fifths of the 770000 cents
    actually paid; the unpaid 2027 accrual is voided and never enters the sum.

    PRD §3.9: "The settled figure is the sum of `net_amount_cents` over this enrollment's
    payments whose `status` is `PAID` — and only those; `ACCRUED`, `CLAWED_BACK` and `VOID`
    rows are excluded, which means the same voiding hop that runs on termination cannot
    retroactively change the fee, because voided rows were never in the sum."

    Design: Difficulty/compensating_invariant/termination_conserves_acres_and_cents_across_void_and_exit_fee
    """
    paid, unpaid = _terminable_enrollment(scenario)
    assert_cents(paid["net_amount_cents"], 770000)
    assert_cents(unpaid["net_amount_cents"], 770000)
    assert_cents(scenario.reload_enrollment()["accrued_payment_cents"], 1540000)

    terminated = get_success_data(
        scenario.api.decide_exit(scenario.enrollment_id, exit_decision_payload("APPROVE"),
                                 ADMIN_HEADERS)
    )

    assert terminated["status"] == ENROLLMENT_TERMINATED
    assert terminated["terminated_effective_year"] == 2027
    assert_cents(terminated["exit_fee_cents"], 616000)
    # 1232000 would count the accrued row as settled; 0 would treat the exit as served.
    assert terminated["exit_fee_cents"] not in (1232000, 0)
    assert_cents(terminated["accrued_payment_cents"], 770000)
    assert get_success_data(scenario.api.get_grower_payment(unpaid["id"], ADMIN_HEADERS))[
        "status"] == PAYMENT_VOID
    assert get_success_data(scenario.api.get_grower_payment(paid["id"], ADMIN_HEADERS))[
        "status"] == PAYMENT_PAID
    grower = scenario.reload_grower()
    assert_cents(grower["net_paid_cents"], 770000)
    assert_cents(grower["outstanding_clawback_cents"], 0)


def test_termination_returns_the_acres_and_opens_the_practice_cooldown(scenario):
    """The field's full mapped acreage comes back out of the grower aggregate, permanence is
    breached, and the same practice is barred until two crop years past the effective year.

    PRD §3.9: "After an enrollment reaches `TERMINATED`, the same field may not be
    re-enrolled in the **same** `practice_code` until two crop years have elapsed past the
    `terminated_effective_year`: a new enrollment's `start_crop_year` must be at least the
    `terminated_effective_year` plus 2, or creation is refused with
    `ERR_PRACTICE_COOLDOWN_ACTIVE`."

    Design: Difficulty/compensating_invariant/termination_conserves_acres_and_cents_across_void_and_exit_fee
    """
    _paid, _unpaid = _terminable_enrollment(scenario)
    assert_acres(scenario.reload_grower()["total_enrolled_acres"], 1000.00)

    terminated = get_success_data(
        scenario.api.decide_exit(scenario.enrollment_id, exit_decision_payload("APPROVE"),
                                 ADMIN_HEADERS)
    )

    assert terminated["permanence_status"] == PERMANENCE_BREACHED
    assert scenario.reload_field()["status"] == FIELD_MAPPED
    assert_acres(scenario.reload_grower()["total_enrolled_acres"], 0.00)
    ledger = get_success_data(
        scenario.api.get_grower_ledger_summary(scenario.grower_id, ADMIN_HEADERS)
    )
    assert_cents(ledger["paid_total_cents"], 770000)
    assert_cents(ledger["clawed_back_total_cents"], 0)
    assert_credits(ledger["lifetime_credits_issued"], 0)
    assert_credits(ledger["buffer_contributed_credits"], 0)

    refused = scenario.api.create_enrollment(
        {"field_id": scenario.field_id, "practice_standard_id": scenario.standard_id,
         "commitment_years": 5, "start_crop_year": 2028, "enrolled_acres": 1000.00,
         "payment_model": "PER_ACRE", "per_acre_rate_cents": 1000.00},
        ADMIN_HEADERS,
    )

    validate_error(refused, ERR_PRACTICE_COOLDOWN_ACTIVE, 409)
