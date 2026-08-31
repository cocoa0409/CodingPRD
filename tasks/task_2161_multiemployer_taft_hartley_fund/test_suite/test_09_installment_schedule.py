"""Paying, missing and defaulting the withdrawal-liability installment schedule."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_payment_installment,
    list_installments,
    make_employer_headers,
    read_employer,
    read_fund,
    read_withdrawal,
    run_collections,
    set_clock,
    setup_boundary_steel_demanded,
    setup_single_installment_demanded,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def _installment(installments, number):
    return [row for row in installments if row["installment_number"] == number][0]


def test_a_defaulted_installment_accelerates_the_assessment_and_suspends_the_employer(api):
    """PRD §3.10: "**The second sweep ages the withdrawal installments, in two
    ordered passes.** Pass A moves every installment still `SCHEDULED` whose
    `due_date` now lies in the past to `MISSED`. Pass B then moves every
    installment that is `MISSED` and whose `due_date` plus 60 days now lies in
    the past to `DEFAULTED` — and pass B explicitly includes the rows pass A has
    just marked, so a single run can carry one installment all the way from
    `SCHEDULED` through `MISSED` to `DEFAULTED` when the clock has advanced far
    enough."
    PRD §3.9: "Default is the other terminal outcome. When a collections run
    drives one of an assessment's installments from `MISSED` to `DEFAULTED`, the
    assessment itself moves to `ACCELERATED` — from `DEMANDED` or from
    `PAYMENT_ACTIVE`, on identical terms — and `accelerated_balance_cents` is set
    to the sum of `amount_cents` across every installment of that assessment
    whose status is `SCHEDULED`, `MISSED`, or `DEFAULTED`; installments already
    `PAID` are excluded. The withdrawing employer's `status` is driven to
    `SUSPENDED` and the fund's `suspended_employer_count` is recomputed."
    PRD §3.9: "Installment number *k* falls due 60 days after `demanded_on` plus
    a further 365 days for each year beyond the first — so the first is due 60
    days after the demand, the second 425 days after it, and so on."

    Design: Corner/state_machines/installment_default_accelerates_assessment_and_suspends_employer
    """
    base = setup_boundary_steel_demanded()
    assessment_id = base["assessment"]["id"]

    schedule = list_installments(assessment_id)
    assert len(schedule) == 12
    first = _installment(schedule, 1)
    assert_payment_installment(first)
    assert first["due_date"] == "2026-05-31"
    assert first["amount_cents"] == 825500
    assert _installment(schedule, 12)["amount_cents"] == 169500

    set_clock("2026-06-01T00:00:00Z")
    first_sweep = validate_success(api.run_collections(base["fund"]["id"], ADMIN))
    assert first_sweep["installments_marked_missed"] == 1

    after_first = list_installments(assessment_id)
    assert _installment(after_first, 1)["status"] == "MISSED"
    assert _installment(after_first, 2)["status"] == "SCHEDULED"
    assert read_withdrawal(assessment_id)["status"] == "DEMANDED"

    set_clock("2026-07-31T00:00:00Z")
    second_sweep = validate_success(api.run_collections(base["fund"]["id"], ADMIN))
    assert second_sweep["installments_defaulted"] == 1
    assert second_sweep["employers_suspended"] == 1

    after_second = list_installments(assessment_id)
    assert _installment(after_second, 1)["status"] == "DEFAULTED"

    assessment = read_withdrawal(assessment_id)
    assert assessment["status"] == "ACCELERATED"
    assert assessment["accelerated_balance_cents"] == 9_250_000

    assert read_employer(base["employer"]["id"])["status"] == "SUSPENDED"
    fund = read_fund(base["fund"]["id"])
    assert fund["suspended_employer_count"] == 1
    assert fund["collections_run_index"] == 2


def test_paying_the_only_installment_carries_the_assessment_to_satisfied(api):
    """PRD §3.9: "A successful payment stamps `paid_on` with the logical clock
    date and moves the installment to `PAID`. Two knock-on transitions follow. If
    the owning assessment was still `DEMANDED`, the first payment moves it to
    `PAYMENT_ACTIVE`. If every installment of the assessment is now `PAID`, the
    assessment moves to `SATISFIED`, which is terminal."
    PRD §3.9: "Every installment except the last carries an `amount_cents` equal
    to `annual_payment_cents`; the final installment carries
    `capped_liability_cents` less `annual_payment_cents` multiplied by one fewer
    than `schedule_years`, which is how the schedule lands exactly on the capped
    total."
    PRD §3.1: "`unallocated_uvb_cents` is always the fund's `total_uvb_cents`
    less its `allocated_uvb_cents`, and `allocated_uvb_cents` is the sum of the
    net liability of every withdrawal assessment against this fund's employers
    whose status is `CERTIFIED`, `DEMANDED`, `REVIEW_REQUESTED`,
    `PAYMENT_ACTIVE`, `ACCELERATED` or `SATISFIED`. Assessments still in `DRAFT`
    contribute nothing."

    Design: Corner/state_machines/final_installment_payment_moves_assessment_to_satisfied
    """
    base = setup_single_installment_demanded()
    assessment = base["assessment"]

    assert assessment["raw_allocation_cents"] == 1_000_000
    assert assessment["de_minimis_reduction_cents"] == 750_000
    assert assessment["net_liability_cents"] == 250_000
    assert assessment["schedule_years"] == 1
    assert assessment["capped_liability_cents"] == 250_000

    schedule = list_installments(assessment["id"])
    assert len(schedule) == 1
    only = schedule[0]
    assert only["amount_cents"] == 250_000
    assert only["due_date"] == "2026-05-31"

    paid = validate_success(
        api.pay_installment(
            only["id"],
            {"amount_cents": 250_000},
            make_employer_headers(base["employer"]["id"]),
        )
    )

    assert paid["status"] == "PAID"
    assert paid["paid_on"] == "2026-04-01"

    assert read_withdrawal(assessment["id"])["status"] == "SATISFIED"
    assert read_fund(base["fund"]["id"])["allocated_uvb_cents"] == 250_000


def test_a_wrong_amount_and_a_defaulted_installment_are_both_unpayable(api):
    """PRD §3.9: "Installments are paid one at a time and in full. A payment
    carries `amount_cents`, which must equal the installment's own `amount_cents`
    exactly — anything else, high or low, is refused with
    `ERR_INSTALLMENT_AMOUNT_MISMATCH`."
    PRD §3.9: "An installment already `PAID` or already `DEFAULTED` accepts
    nothing further, and a `MISSED` installment accepts payment only while the
    logical clock date is no later than 60 days past its `due_date` — its cure
    window — with all three refusals carrying `ERR_INSTALLMENT_NOT_PAYABLE`."
    PRD §3.10: "Pass B then moves every installment that is `MISSED` and whose
    `due_date` plus 60 days now lies in the past to `DEFAULTED` — and pass B
    explicitly includes the rows pass A has just marked, so a single run can
    carry one installment all the way from `SCHEDULED` through `MISSED` to
    `DEFAULTED` when the clock has advanced far enough."

    Design: Corner/validations/installment_payment_guards_reject_wrong_amount_and_defaulted_installment
    """
    base = setup_boundary_steel_demanded()
    employer_headers = make_employer_headers(base["employer"]["id"])
    first = _installment(list_installments(base["assessment"]["id"]), 1)

    validate_error(
        api.pay_installment(first["id"], {"amount_cents": 1}, employer_headers),
        ApiErrorId.ERR_INSTALLMENT_AMOUNT_MISMATCH.value,
    )
    assert _installment(list_installments(base["assessment"]["id"]), 1)["status"] == "SCHEDULED"

    set_clock("2026-07-31T00:00:00Z")
    run_collections(base["fund"]["id"])

    defaulted = _installment(list_installments(base["assessment"]["id"]), 1)
    assert defaulted["status"] == "DEFAULTED", (
        "one run carried the row SCHEDULED to MISSED to DEFAULTED"
    )
    assert defaulted["paid_on"] is None

    validate_error(
        api.pay_installment(first["id"], {"amount_cents": 825_500}, employer_headers),
        ApiErrorId.ERR_INSTALLMENT_NOT_PAYABLE.value,
    )

    assessment = read_withdrawal(base["assessment"]["id"])
    assert assessment["status"] == "ACCELERATED"
    assert assessment["accelerated_balance_cents"] == 9_250_000

    _rows, meta = validate_paginated(
        api.list_installments(
            base["assessment"]["id"], ADMIN, params={"status": "DEFAULTED"}
        )
    )
    assert meta["total_count"] == 1
