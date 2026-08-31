"""Payroll remittance: deadlines, lateness, corrections and reversal."""

from test_helpers import (
    ApiErrorId,
    assert_line_breakdown_sums_to_total,
    assert_plan_compliance_posture_follows_count,
    create_batch,
    create_remittance_batch_payload,
    deposit_batch,
    first_correction,
    make_line_item,
    make_officer_headers,
    make_participant_headers,
    make_sponsor_headers,
    open_contract,
    register_participant,
    register_second_vendor,
    reverse_batch,
    set_clock,
    settle_correction,
    setup_basic_403b,
    setup_late_deposit,
    setup_plan_env,
    setup_withheld_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_deposit_on_the_deadline_is_timely(api):
    """PRD §3.7: "For every other plan the statutory deadline is the fifteenth business
    day of the month immediately following the month in which the `withholding_date`
    falls, counted from the first day of that month and counting only business days; and
    if the sponsor supplied a `segregation_feasible_date`, the deadline is whichever of
    the statutory date and the segregation-feasible date comes earlier."
    PRD §3.7: "A deposit landing on `deadline_date` itself is timely — the comparison is
    inclusive — and moves `compliance_state` from `UNDETERMINED` to `TIMELY`, leaving
    both `calendar_days_late` and `business_days_late` at zero."

    Design: Difficulty/boundary_precision_check/remittance_deposit_exactly_on_deadline_is_timely
    """
    env = setup_withheld_batch()
    set_clock("2026-08-24T00:00:00Z")

    deposited = validate_success(
        api.deposit_remittance_batch(
            env["batch_id"], {"deposit_date": "2026-08-21"},
            make_sponsor_headers(env["employer_id"]),
        )
    )

    assert deposited["deadline_date"] == "2026-08-21"
    assert deposited["compliance_state"] == "TIMELY"
    assert deposited["calendar_days_late"] == 0
    assert deposited["business_days_late"] == 0
    rows, _meta = validate_paginated(
        api.list_corrections(env["batch_id"], make_officer_headers())
    )
    assert rows == [], "a timely deposit produces no correction"


def test_deposit_the_next_business_day_is_late(api):
    """PRD §3.7: "A deposit landing after the deadline moves `compliance_state` from
    `UNDETERMINED` to `LATE`; `calendar_days_late` is then the whole number of calendar
    days from `deadline_date` to `deposit_date`, and `business_days_late` is the count of
    business days falling strictly after `deadline_date` up to and including
    `deposit_date`. The very next business day after the deadline therefore yields a
    `business_days_late` of one."
    PRD §3.7: "The section 4975 excise tax is then computed on the already-summed total,
    never per line: `excise_tax_cents` is 15 percent of `lost_earnings_total_cents`,
    rounded half up to a whole cent."

    Design: Difficulty/boundary_precision_check/remittance_deposit_exactly_on_deadline_is_timely
    """
    env = setup_withheld_batch()
    set_clock("2026-08-24T00:00:00Z")

    deposited = validate_success(
        api.deposit_remittance_batch(
            env["batch_id"], {"deposit_date": "2026-08-24"},
            make_sponsor_headers(env["employer_id"]),
        )
    )

    assert deposited["deadline_date"] == "2026-08-21"
    assert deposited["compliance_state"] == "CORRECTION_PENDING"
    assert deposited["business_days_late"] == 1
    assert deposited["calendar_days_late"] == 3
    correction = first_correction(env["batch_id"])
    assert correction["lost_earnings_total_cents"] == 49
    assert correction["excise_tax_cents"] == 7
    assert validate_success(
        api.get_vendor_account(env["account_id"], make_officer_headers())
    )["ytd_elective_deferrals_cents"] == 100_000


def _three_line_batch_env():
    """One large 403(b) plan, three contracts across two providers, and a WITHHELD batch
    whose lines are 555555, 333333 and 111111 cents."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    participant_a = register_participant(env["employer_id"])
    participant_b = register_participant(
        env["employer_id"], full_name="Ben Okafor", date_of_birth="1980-01-01",
        hire_date="2010-01-01", includible_compensation_cents=8_000_000, years_of_service=16,
    )
    account_one = open_contract(
        participant_a["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant_a["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=3_000_000,
    )
    account_three = open_contract(
        participant_b["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0002", accumulated_benefit_cents=2_000_000,
    )
    batch = create_batch(
        env["plan_id"], env["employer_id"],
        [
            make_line_item(account_one["id"], 555_555),
            make_line_item(account_two["id"], 333_333),
            make_line_item(account_three["id"], 111_111),
        ],
    )
    env.update(
        account_one_id=account_one["id"], account_two_id=account_two["id"],
        account_three_id=account_three["id"], batch_id=batch["id"],
    )
    set_clock("2026-09-30T00:00:00Z")
    return env


def test_lost_earnings_are_rounded_per_line_before_summation(api):
    """PRD §3.7: "For each element of `line_items`, in the exact order the sponsor
    submitted them, take that line's `elective_deferral_cents`, multiply by six percent,
    multiply by the batch's `calendar_days_late`, divide by 365, and round that single
    line's result half up to a whole cent."
    PRD §3.7: "Each rounded line is emitted into `line_breakdown` as an object carrying
    the line's `vendor_account_id` and its `lost_earnings_cents`, in the same order as
    the batch's lines. `lost_earnings_total_cents` is then the sum of those
    already-rounded per-line figures. Summing the unrounded products and rounding once at
    the end is a different number and is explicitly not what this plan does."

    Design: Difficulty/combinatorial_formula/lost_earnings_round_per_line_then_sum
    """
    env = _three_line_batch_env()

    deposited = deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    correction = first_correction(env["batch_id"])

    assert deposited["deadline_date"] == "2026-08-21"
    assert deposited["calendar_days_late"] == 40
    assert deposited["business_days_late"] == 27
    assert deposited["compliance_state"] == "CORRECTION_PENDING"
    assert correction["line_breakdown"][0]["lost_earnings_cents"] == 3653
    assert correction["line_breakdown"][1]["lost_earnings_cents"] == 2192
    assert correction["line_breakdown"][2]["lost_earnings_cents"] == 731
    assert correction["lost_earnings_total_cents"] == 6576, (
        "per-line rounding sums to 6576; sum-then-round would give 6575"
    )
    assert_line_breakdown_sums_to_total(correction)


def test_excise_tax_is_computed_on_the_summed_total(api):
    """PRD §3.7: "The section 4975 excise tax is then computed on the already-summed
    total, never per line: `excise_tax_cents` is 15 percent of
    `lost_earnings_total_cents`, rounded half up to a whole cent."
    PRD §3.7: "Creating that correction adds each line's lost earnings to the
    corresponding contract's `pending_lost_earnings_cents` and forces the plan's
    `open_correction_count` to be recomputed."

    Design: Difficulty/combinatorial_formula/lost_earnings_round_per_line_then_sum
    """
    env = _three_line_batch_env()

    deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    correction = first_correction(env["batch_id"])

    assert correction["lost_earnings_total_cents"] == 6576
    assert correction["excise_tax_cents"] == 986
    for account_id, expected in (
        (env["account_one_id"], 3653),
        (env["account_two_id"], 2192),
        (env["account_three_id"], 731),
    ):
        account = validate_success(api.get_vendor_account(account_id, make_officer_headers()))
        assert account["pending_lost_earnings_cents"] == expected
    rows, _meta = validate_paginated(
        api.list_corrections(env["batch_id"], make_officer_headers())
    )
    assert len(rows) == 1


def test_deposit_and_reversal_move_the_two_axes_independently(api):
    """PRD §3.7: "A batch carries two state values that evolve independently:
    `deposit_state` tracks whether the cash has moved, and `compliance_state` tracks
    whether it moved in time. A batch is `DEPOSITED` regardless of which compliance value
    it lands on, and nothing about the compliance axis prevents the cash axis from
    advancing."
    PRD §3.7: "`compliance_state` is reset to `UNDETERMINED`, `deposit_date` to null, and
    both `calendar_days_late` and `business_days_late` to zero; and the batch's `version`
    increments by one."

    Design: Difficulty/non_linear_state_machine/remittance_batch_parallel_deposit_and_compliance_axes
    """
    env = setup_withheld_batch()
    set_clock("2026-09-30T00:00:00Z")

    deposited = deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    assert deposited["deposit_state"] == "DEPOSITED"
    assert deposited["compliance_state"] == "CORRECTION_PENDING"
    assert deposited["calendar_days_late"] == 40
    assert deposited["business_days_late"] == 27
    account = validate_success(api.get_vendor_account(env["account_id"], make_officer_headers()))
    assert account["ytd_elective_deferrals_cents"] == 100_000
    assert account["pending_lost_earnings_cents"] == 658

    reversed_batch = reverse_batch(env["batch_id"], env["employer_id"], "bank returned the wire")

    assert reversed_batch["deposit_state"] == "REVERSED"
    assert reversed_batch["compliance_state"] == "UNDETERMINED"
    assert reversed_batch["calendar_days_late"] == 0
    assert reversed_batch["business_days_late"] == 0
    account = validate_success(api.get_vendor_account(env["account_id"], make_officer_headers()))
    assert account["ytd_elective_deferrals_cents"] == 0
    assert account["pending_lost_earnings_cents"] == 0
    rows, _meta = validate_paginated(
        api.list_corrections(env["batch_id"], make_officer_headers())
    )
    assert len(rows) == 1
    assert rows[0]["state"] == "VOIDED"


def test_redeposit_lands_timely_on_the_same_deposited_state(api):
    """PRD §3.7: "The `DEPOSITED → REVERSED → DEPOSITED` cycle may repeat any number of
    times, and a redeposit re-evaluates everything against the newly supplied
    `deposit_date`."
    PRD §3.7: "A deposit landing on `deadline_date` itself is timely — the comparison is
    inclusive — and moves `compliance_state` from `UNDETERMINED` to `TIMELY`, leaving
    both `calendar_days_late` and `business_days_late` at zero."

    Design: Difficulty/non_linear_state_machine/remittance_batch_parallel_deposit_and_compliance_axes
    """
    env = setup_withheld_batch()
    set_clock("2026-09-30T00:00:00Z")
    deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    reverse_batch(env["batch_id"], env["employer_id"], "bank returned the wire")

    set_clock("2026-08-21T00:00:00Z")
    redeposited = deposit_batch(env["batch_id"], env["employer_id"], "2026-08-21")

    assert redeposited["deposit_state"] == "DEPOSITED"
    assert redeposited["compliance_state"] == "TIMELY", (
        "the same deposit_state value carried CORRECTION_PENDING on the first pass"
    )
    assert redeposited["deadline_date"] == "2026-08-21"
    assert redeposited["business_days_late"] == 0


def test_abutting_half_open_pay_periods_are_both_admitted(api):
    """PRD §3.7: "A sponsor admin records a batch by naming the `plan_id`, the pay
    period's inclusive `pay_period_start` and its **exclusive** `pay_period_end` — pay
    periods are half-open, so the end date is the first date *not* covered and must fall
    strictly after the start — the `withholding_date` on which the amounts left payroll,
    the sponsor-declared `total_elective_deferral_cents` for the batch, and a
    `line_items` array giving the per-contract breakdown."
    PRD §3.7: "Periods that merely abut — the new one starting on the very day the old
    one ends — do not intersect and are admissible."

    Design: Difficulty/resource_temporal_overlap/remittance_pay_period_half_open_adjacency_admitted
    """
    env = setup_basic_403b()

    first = validate_success(
        api.create_remittance_batch(
            create_remittance_batch_payload(
                env["plan_id"], [make_line_item(env["account_id"], 100_000)],
                pay_period_start="2026-07-01", pay_period_end="2026-07-16",
                withholding_date="2026-07-15",
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )
    second = validate_success(
        api.create_remittance_batch(
            create_remittance_batch_payload(
                env["plan_id"], [make_line_item(env["account_id"], 100_000)],
                pay_period_start="2026-07-16", pay_period_end="2026-07-31",
                withholding_date="2026-07-30",
            ),
            make_sponsor_headers(env["employer_id"]),
        ),
        expected_status=201,
    )

    assert first["deposit_state"] == "WITHHELD"
    assert second["pay_period_start"] == first["pay_period_end"]
    rows, _meta = validate_paginated(
        api.list_remittance_batches(make_officer_headers(), {"plan_id": env["plan_id"]})
    )
    assert len(rows) == 2


def test_intersecting_pay_period_is_rejected(api):
    """PRD §3.7: "Because the interval is half-open, the new batch conflicts with an
    existing batch of the same plan whose `deposit_state` is anything other than
    `REVERSED` when the new `pay_period_start` falls strictly before that batch's
    `pay_period_end` and that batch's `pay_period_start` falls strictly before the new
    `pay_period_end`."
    PRD §3.7: "A genuine intersection is refused with `ERR_REMITTANCE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/remittance_pay_period_half_open_adjacency_admitted
    """
    env = setup_basic_403b()
    create_batch(
        env["plan_id"], env["employer_id"], [make_line_item(env["account_id"], 100_000)],
        pay_period_start="2026-07-01", pay_period_end="2026-07-16",
        withholding_date="2026-07-15",
    )

    response = api.create_remittance_batch(
        create_remittance_batch_payload(
            env["plan_id"], [make_line_item(env["account_id"], 100_000)],
            pay_period_start="2026-07-15", pay_period_end="2026-07-20",
            withholding_date="2026-07-19",
        ),
        make_sponsor_headers(env["employer_id"]),
    )

    validate_error(response, ApiErrorId.ERR_REMITTANCE_PERIOD_OVERLAP.value)
    rows, _meta = validate_paginated(
        api.list_remittance_batches(make_officer_headers(), {"plan_id": env["plan_id"]})
    )
    assert len(rows) == 1


def _two_line_late_env():
    """Two fully vested contracts and one late batch splitting 888888 cents 555555 /
    333333 across them."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    participant = register_participant(env["employer_id"])
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=3_000_000,
    )
    batch = create_batch(
        env["plan_id"], env["employer_id"],
        [
            make_line_item(account_one["id"], 555_555),
            make_line_item(account_two["id"], 333_333),
        ],
    )
    env.update(
        participant_id=participant["id"], account_one_id=account_one["id"],
        account_two_id=account_two["id"], batch_id=batch["id"],
    )
    set_clock("2026-09-30T00:00:00Z")
    return env


def test_late_deposit_consumes_year_to_date_deferrals(api):
    """PRD §3.7: "The transition stores `deposit_date`, computes `deadline_date`, and
    then, for each element of `line_items` in submitted order, adds that line's
    `elective_deferral_cents` to the named contract's `ytd_elective_deferrals_cents` and
    that line's `employer_contribution_cents` to the same contract's
    `ytd_employer_contributions_cents`."
    PRD §2.10: "At the plan tier, `open_correction_count` is the number of remittance
    corrections in state `OPEN` across every remittance batch whose `plan_id` is this
    plan, and `compliance_posture` follows it mechanically: `UNDER_CORRECTION` while
    `open_correction_count` is greater than zero, `CLEAR` otherwise."

    Design: Difficulty/compensating_invariant/remittance_deposit_reverse_preserves_ytd_deferral_total
    """
    env = _two_line_late_env()
    for account_id in (env["account_one_id"], env["account_two_id"]):
        before = validate_success(api.get_vendor_account(account_id, make_officer_headers()))
        assert before["ytd_elective_deferrals_cents"] == 0

    deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    correction = first_correction(env["batch_id"])

    one = validate_success(api.get_vendor_account(env["account_one_id"], make_officer_headers()))
    two = validate_success(api.get_vendor_account(env["account_two_id"], make_officer_headers()))
    assert one["ytd_elective_deferrals_cents"] == 555_555
    assert two["ytd_elective_deferrals_cents"] == 333_333
    assert one["pending_lost_earnings_cents"] == 3653
    assert two["pending_lost_earnings_cents"] == 2192
    assert correction["lost_earnings_total_cents"] == 5845
    assert correction["excise_tax_cents"] == 877
    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 1
    assert plan["compliance_posture"] == "UNDER_CORRECTION"
    assert_plan_compliance_posture_follows_count(plan)


def test_reversal_returns_year_to_date_deferrals_to_zero(api):
    """PRD §3.7: "A permitted reversal moves the batch `DEPOSITED → REVERSED` and unwinds
    everything the deposit did: for each element of `line_items` in submitted order, that
    line's `elective_deferral_cents` is subtracted from the contract's
    `ytd_elective_deferrals_cents` and its `employer_contribution_cents` from
    `ytd_employer_contributions_cents`; every correction of the batch still in state
    `OPEN` transitions to `VOIDED` and its per-contract lost earnings are subtracted back
    out of `pending_lost_earnings_cents`; the plan's `open_correction_count` is recomputed
    and `compliance_posture` follows it, so a plan whose only open correction was voided
    returns to `CLEAR`; `compliance_state` is reset to `UNDETERMINED`, `deposit_date` to
    null, and both `calendar_days_late` and `business_days_late` to zero; and the batch's
    `version` increments by one."

    Design: Difficulty/compensating_invariant/remittance_deposit_reverse_preserves_ytd_deferral_total
    """
    env = _two_line_late_env()
    deposit_batch(env["batch_id"], env["employer_id"], "2026-09-30")
    correction = first_correction(env["batch_id"])

    reversed_batch = reverse_batch(
        env["batch_id"], env["employer_id"], "payroll file was superseded"
    )

    one = validate_success(api.get_vendor_account(env["account_one_id"], make_officer_headers()))
    two = validate_success(api.get_vendor_account(env["account_two_id"], make_officer_headers()))
    assert one["ytd_elective_deferrals_cents"] == 0
    assert two["ytd_elective_deferrals_cents"] == 0
    assert one["pending_lost_earnings_cents"] == 0
    assert two["pending_lost_earnings_cents"] == 0
    rows, _meta = validate_paginated(
        api.list_corrections(env["batch_id"], make_officer_headers())
    )
    assert rows[0]["id"] == correction["id"]
    assert rows[0]["state"] == "VOIDED"
    assert reversed_batch["deposit_state"] == "REVERSED"
    assert reversed_batch["compliance_state"] == "UNDETERMINED"
    assert reversed_batch["calendar_days_late"] == 0
    assert reversed_batch["business_days_late"] == 0
    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 0
    assert plan["compliance_posture"] == "CLEAR"


def test_settlement_clears_the_open_correction_count(api):
    """PRD §3.7: "It moves the correction `OPEN → SETTLED`, records the
    `settlement_reference`, stamps `settled_at` from the logical clock and
    `settled_by_user_id` from the acting `X-User-ID`, removes that correction's lost
    earnings from the affected contracts' `pending_lost_earnings_cents`, recomputes the
    plan's `open_correction_count` and with it `compliance_posture`, and increments the
    correction's `version` by one."
    PRD §3.7: "When the last correction of a batch leaves `OPEN`, the batch itself moves
    `CORRECTION_PENDING → CORRECTED` as a system transition, recomputing the plan's
    `open_correction_count` and `compliance_posture` once more and incrementing the
    batch's `version` by one."

    Design: Difficulty/compensating_invariant/correction_settle_restores_open_correction_count_invariant
    """
    env = setup_late_deposit()
    plan_before = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan_before["open_correction_count"] == 1
    assert env["correction"]["lost_earnings_total_cents"] == 658
    assert validate_success(
        api.get_vendor_account(env["account_id"], make_officer_headers())
    )["pending_lost_earnings_cents"] == 658

    settled = settle_correction(
        env["batch_id"], env["correction_id"], "VFCP-2026-0042", "co-2"
    )

    assert settled["state"] == "SETTLED"
    assert settled["settlement_reference"] == "VFCP-2026-0042"
    assert settled["settled_by_user_id"] == "co-2"
    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 0
    assert plan["compliance_posture"] == "CLEAR"
    batch = validate_success(api.get_remittance_batch(env["batch_id"], make_officer_headers()))
    assert batch["compliance_state"] == "CORRECTED"
    assert batch["deposit_state"] == "DEPOSITED"
    account = validate_success(
        api.get_vendor_account(env["account_id"], make_officer_headers())
    )
    assert account["pending_lost_earnings_cents"] == 0
    assert account["ytd_elective_deferrals_cents"] == 100_000, (
        "settling a correction does not unwind the deposit"
    )


def test_second_settlement_of_the_same_correction_is_rejected(api):
    """PRD §3.7: "Settlement requires the correction's `state` to be `OPEN`, failing which
    the answer is `ERR_CORRECTION_NOT_SETTLEABLE`."
    PRD §2.10: "At the plan tier, `open_correction_count` is the number of remittance
    corrections in state `OPEN` across every remittance batch whose `plan_id` is this
    plan, and `compliance_posture` follows it mechanically: `UNDER_CORRECTION` while
    `open_correction_count` is greater than zero, `CLEAR` otherwise."

    Design: Difficulty/compensating_invariant/correction_settle_restores_open_correction_count_invariant
    """
    env = setup_late_deposit()
    settle_correction(env["batch_id"], env["correction_id"], "VFCP-2026-0042", "co-2")

    response = api.settle_correction(
        env["batch_id"], env["correction_id"],
        {"settlement_reference": "VFCP-2026-0042-DUP"}, make_officer_headers("co-2"),
    )

    validate_error(response, ApiErrorId.ERR_CORRECTION_NOT_SETTLEABLE.value)
    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 0
    assert_plan_compliance_posture_follows_count(plan)


def test_small_plan_deadline_is_the_seventh_business_day(api):
    """PRD §3.7: "For a small plan — one whose `reported_participant_count` is fewer than
    one hundred participants, recorded as `is_small_plan` — the deadline is the seventh
    business day after the `withholding_date`, counting forward from but not including
    the withholding date itself and counting only business days."
    PRD §3.7: "A **business day** here means a weekday — Monday through Friday — that is
    not a federal holiday; the holiday calendar is fixed and consists of 1 January 2026,
    19 January 2026, 16 February 2026, 25 May 2026, 19 June 2026, 3 July 2026,
    7 September 2026, 12 October 2026, 11 November 2026, 26 November 2026 and
    25 December 2026."

    Design: Corner/calculations/small_plan_seven_business_day_deadline_applies
    """
    env = setup_withheld_batch(
        plan_overrides={
            "plan_name": "Cedarbrook 403(b)", "reported_participant_count": 50,
        }
    )
    assert validate_success(
        api.get_plan(env["plan_id"], make_officer_headers())
    )["is_small_plan"] is True
    set_clock("2026-07-27T00:00:00Z")

    deposited = deposit_batch(env["batch_id"], env["employer_id"], "2026-07-24")

    assert deposited["deadline_date"] == "2026-07-24"
    assert deposited["compliance_state"] == "TIMELY"
    assert deposited["business_days_late"] == 0
    assert deposited["calendar_days_late"] == 0
    rows, _meta = validate_paginated(
        api.list_corrections(env["batch_id"], make_officer_headers())
    )
    assert rows == []
    assert validate_success(
        api.get_plan(env["plan_id"], make_officer_headers())
    )["compliance_posture"] == "CLEAR"


def test_segregation_feasible_date_pulls_the_deadline_earlier(api):
    """PRD §3.7: "For every other plan the statutory deadline is the fifteenth business
    day of the month immediately following the month in which the `withholding_date`
    falls, counted from the first day of that month and counting only business days; and
    if the sponsor supplied a `segregation_feasible_date`, the deadline is whichever of
    the statutory date and the segregation-feasible date comes earlier."
    PRD §3.7: "An optional `segregation_feasible_date` records the earliest date the
    sponsor could reasonably have segregated the assets; it is consulted only for large
    plans and defaults to null."

    Design: Corner/calculations/segregation_feasible_date_pulls_large_plan_deadline_earlier
    """
    env = setup_withheld_batch(batch_overrides={"segregation_feasible_date": "2026-08-05"})
    set_clock("2026-08-10T00:00:00Z")

    deposited = deposit_batch(env["batch_id"], env["employer_id"], "2026-08-10")
    correction = first_correction(env["batch_id"])

    assert deposited["deadline_date"] == "2026-08-05", "the earlier of the two dates governs"
    assert deposited["calendar_days_late"] == 5
    assert deposited["business_days_late"] == 3
    assert deposited["compliance_state"] == "CORRECTION_PENDING"
    assert correction["lost_earnings_total_cents"] == 82
    assert correction["excise_tax_cents"] == 12
    assert validate_success(
        api.get_vendor_account(env["account_id"], make_officer_headers())
    )["pending_lost_earnings_cents"] == 82


def test_duplicate_deposit_is_rejected(api):
    """PRD §3.7: "A deposit recorded against a batch already in `DEPOSITED` is refused
    with `ERR_REMITTANCE_ALREADY_DEPOSITED`."
    PRD §3.7: "The transition stores `deposit_date`, computes `deadline_date`, and then,
    for each element of `line_items` in submitted order, adds that line's
    `elective_deferral_cents` to the named contract's `ytd_elective_deferrals_cents` and
    that line's `employer_contribution_cents` to the same contract's
    `ytd_employer_contributions_cents`."

    Design: Corner/state_machines/duplicate_deposit_on_a_deposited_batch_is_rejected
    """
    env = setup_withheld_batch()
    set_clock("2026-08-21T00:00:00Z")

    first = deposit_batch(env["batch_id"], env["employer_id"], "2026-08-21")
    assert first["compliance_state"] == "TIMELY"

    second = api.deposit_remittance_batch(
        env["batch_id"], {"deposit_date": "2026-08-21"}, make_sponsor_headers(env["employer_id"])
    )

    validate_error(second, ApiErrorId.ERR_REMITTANCE_ALREADY_DEPOSITED.value)
    account = validate_success(api.get_vendor_account(env["account_id"], make_officer_headers()))
    assert account["ytd_elective_deferrals_cents"] == 100_000, "credited exactly once"
    assert validate_success(
        api.get_remittance_batch(env["batch_id"], make_officer_headers())
    )["deposit_state"] == "DEPOSITED"


def test_participant_cannot_settle_a_remittance_correction(api):
    """PRD §2.1: "If both headers are well formed but the named role is not among the
    roles the addressed endpoint admits, the refusal is `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."
    PRD §4: "| POST | `/plan-admin/remittance-batches/{id}/corrections/{correction_id}/settle` | Record settlement of an open lost-earnings correction | `ComplianceOfficer` |"

    Design: Corner/rbac/participant_cannot_settle_a_remittance_correction
    """
    env = setup_late_deposit()

    response = api.settle_correction(
        env["batch_id"], env["correction_id"], {"settlement_reference": "SELF-SERVE"},
        make_participant_headers(env["participant_id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
    rows, _meta = validate_paginated(
        api.list_corrections(env["batch_id"], make_officer_headers())
    )
    assert rows[0]["state"] == "OPEN"
    assert rows[0]["settled_by_user_id"] is None
    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 1
    assert plan["compliance_posture"] == "UNDER_CORRECTION"


def test_deposit_cascade_is_visible_immediately(api):
    """PRD §2.10: "Balances live on contracts, aggregates live on participants, and
    compliance counters live on plans, and the service keeps all three tiers consistent
    immediately rather than eventually."
    PRD §3.7: "Landing on `LATE` immediately triggers a system transition
    `LATE → CORRECTION_PENDING`, and with it a four-hop chain that nothing else in the
    system initiates."

    Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_the_same_response
    """
    env = setup_withheld_batch()
    set_clock("2026-09-30T00:00:00Z")

    deposited = validate_success(
        api.deposit_remittance_batch(
            env["batch_id"], {"deposit_date": "2026-09-30"},
            make_sponsor_headers(env["employer_id"]),
        )
    )

    assert deposited["deposit_state"] == "DEPOSITED"
    assert deposited["compliance_state"] == "CORRECTION_PENDING"
    assert deposited["calendar_days_late"] == 40
    assert deposited["business_days_late"] == 27

    plan = validate_success(api.get_plan(env["plan_id"], make_officer_headers()))
    assert plan["open_correction_count"] == 1
    assert plan["compliance_posture"] == "UNDER_CORRECTION"

    account = validate_success(api.get_vendor_account(env["account_id"], make_officer_headers()))
    assert account["ytd_elective_deferrals_cents"] == 100_000
    assert account["pending_lost_earnings_cents"] == 658
