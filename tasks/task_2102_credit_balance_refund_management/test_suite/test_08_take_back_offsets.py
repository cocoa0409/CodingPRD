"""Payer take-backs, the offset waterfall, disputes and offset reversal."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_offset_application,
    assert_recoupment_invariant,
    assert_instant_equals,
    apply_offsets,
    attribute_all,
    create_offset_application_payload,
    create_take_back_notice_payload,
    dispute_notice,
    find_obligation_for_credit_balance,
    list_transactions,
    make_payer_liaison_headers,
    read_account,
    read_credit_balance,
    read_notice,
    read_obligation,
    read_offset,
    record_take_back_notice,
    reverse_offset,
    seed_payer,
    set_clock,
    setup_multi_credit_scenario,
    setup_take_back_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_dispute,
)

ANALYST = TEST_USERS["credit_analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _waterfall_scenario():
    """Three PAYER-attributed credits of 3333 / 3333 / 5000 plus a 10,000-cent notice."""
    return setup_take_back_scenario(
        accounts=[
            {"account_number": "ACCT-OA1", "charge_cents": 10_000,
             "payment_cents": -13_333, "payment_source": "PAYER",
             "financial_class": "INPATIENT"},
            {"account_number": "ACCT-OA2", "charge_cents": 10_000,
             "payment_cents": -13_333, "payment_source": "PAYER",
             "financial_class": "INPATIENT"},
            {"account_number": "ACCT-OA3", "charge_cents": 10_000,
             "payment_cents": -15_000, "payment_source": "PAYER",
             "financial_class": "INPATIENT"},
        ],
        notice_number="TB-1", total_recoup_cents=10_000, admin_fee_cents=1_000,
    )


def _lines_by_credit_balance(lines):
    return {line["credit_balance_id"]: line for line in lines}


def test_offset_waterfall_consumes_oldest_first_and_caps_each_line_at_capacity(api):
    """PRD §3.10: "Qualifying credits are then consumed oldest first: sort them by `identified_at` ascending, breaking ties by `created_at` ascending. Start with a pool equal to the notice's `remaining_unapplied_cents`. Walk the sorted credits in order; stop as soon as the pool is exhausted. For each credit, its capacity is the smaller of its `payer_portion_cents` and its `outstanding_cents`, and the line amount is the smaller of the remaining pool and that capacity."
    PRD §3.10: "its `sequence` is a 1-based waterfall position that continues monotonically from the notice's highest existing sequence — the first line of a second call to the same notice takes the next number after the last line of the first call — its `applied_at` is the logical clock, its `reversed_at` is null and its `state` is `APPLIED`."

    Design: Difficulty/combinatorial_formula/offset_admin_fee_rounded_per_line_then_residual_to_last_waterfall_line
    """
    scenario = _waterfall_scenario()
    cb1, cb2, cb3 = [cb["id"] for cb in scenario["credit_balances"]]

    lines = validate_success(
        api.apply_offsets(
            scenario["notice"]["id"],
            create_offset_application_payload(
                [a["id"] for a in scenario["accounts"]],
                scenario["notice"]["version"],
            ),
            ANALYST,
        ),
        201,
    )
    by_credit = _lines_by_credit_balance(lines)

    assert len(lines) == 3
    for line in lines:
        assert_offset_application(line)
    assert by_credit[cb1]["applied_cents"] == 3_333
    assert by_credit[cb2]["applied_cents"] == 3_333
    assert by_credit[cb3]["applied_cents"] == 3_334
    assert by_credit[cb1]["sequence"] == 1
    assert by_credit[cb2]["sequence"] == 2
    assert by_credit[cb3]["sequence"] == 3


def test_admin_fee_is_rounded_per_line_with_the_residual_on_the_last_line(api):
    """PRD §3.10: "The notice's administrative fee is then prorated across those lines, and the order of operations is pinned. **Round per line, then sum.** For each line, its `admin_fee_share_cents` is the notice's `admin_fee_cents` multiplied by that line's `applied_cents`, divided by the applied total, rounded half up to a whole cent. Take the residual — the notice's `admin_fee_cents` minus the sum of the per-line shares just computed — and add it to the **last** line in waterfall order. The shares therefore always sum to `admin_fee_cents` exactly."
    PRD §3.10: "Finally the notice's own `version` is bumped by 1 and it steps forward: it becomes `PARTIALLY_APPLIED` when `remaining_unapplied_cents` after the call is still strictly greater than 0, and `FULLY_APPLIED` when that figure reaches exactly 0."

    Design: Difficulty/combinatorial_formula/offset_admin_fee_rounded_per_line_then_residual_to_last_waterfall_line
    """
    scenario = _waterfall_scenario()
    cb1, cb2, cb3 = [cb["id"] for cb in scenario["credit_balances"]]

    lines = apply_offsets(
        scenario["notice"]["id"],
        [a["id"] for a in scenario["accounts"]],
        scenario["notice"]["version"],
    )
    by_credit = _lines_by_credit_balance(lines)

    assert by_credit[cb1]["admin_fee_share_cents"] == 333
    assert by_credit[cb2]["admin_fee_share_cents"] == 333
    assert by_credit[cb3]["admin_fee_share_cents"] == 334
    assert sum(line["admin_fee_share_cents"] for line in lines) == 1_000

    notice = read_notice(scenario["notice"]["id"])
    assert notice["applied_cents"] == 10_000
    assert notice["remaining_unapplied_cents"] == 0
    assert notice["state"] == "FULLY_APPLIED"
    assert_recoupment_invariant(notice)


def test_recoupment_pool_is_partitioned_exactly_after_a_line_is_reversed(api):
    """PRD §3.14: "Second, the recoupment invariant: for any take-back notice, `total_recoup_cents` always equals `applied_cents` plus `remaining_unapplied_cents`, and the `admin_fee_share_cents` values across a notice's `APPLIED` lines always sum to exactly its `admin_fee_cents`."
    PRD §3.10: "The notice itself then recomputes `applied_cents` and `remaining_unapplied_cents`, bumps its `version` by 1, and steps its `state` down — `FULLY_APPLIED → PARTIALLY_APPLIED` when applied cents remain after the reversal, and `PARTIALLY_APPLIED → RECEIVED` when `applied_cents` returns to exactly 0."

    Design: Difficulty/compensating_invariant/take_back_recoup_pool_conserved_across_offset_apply_and_reverse
    """
    scenario = _waterfall_scenario()
    cb3 = scenario["credit_balances"][2]["id"]
    lines = apply_offsets(
        scenario["notice"]["id"],
        [a["id"] for a in scenario["accounts"]],
        scenario["notice"]["version"],
    )
    last_line = _lines_by_credit_balance(lines)[cb3]

    reversed_line = validate_success(
        api.reverse_offset_application(
            last_line["id"], {"reason": "Line applied to the wrong account"}, ANALYST
        )
    )
    assert reversed_line["state"] == "REVERSED"

    notice = read_notice(scenario["notice"]["id"])
    assert notice["applied_cents"] == 6_666
    assert notice["remaining_unapplied_cents"] == 3_334
    assert notice["total_recoup_cents"] == 10_000
    assert notice["state"] == "PARTIALLY_APPLIED"
    assert_recoupment_invariant(notice)


def test_reversing_one_line_leaves_the_surviving_lines_and_credits_intact(api):
    """PRD §3.10: "Hop 2 recomputes the owning credit balance's `offset_cents` and `outstanding_cents`, and moves it `RESOLVED_BY_OFFSET → ATTRIBUTED` when the recomputed `outstanding_cents` becomes strictly greater than 0, bumping its `version` by 1 — a compensating edge out of what is otherwise a terminal status, because offsets are reversible in a way that escheatment and write-off are not."
    PRD §2.9: "Its `offset_cents` is the sum of `applied_cents` over the offset lines against it whose `state` is `APPLIED`; a `REVERSED` line contributes nothing."

    Design: Difficulty/compensating_invariant/take_back_recoup_pool_conserved_across_offset_apply_and_reverse
    """
    scenario = _waterfall_scenario()
    cb1 = scenario["credit_balances"][0]["id"]
    cb3 = scenario["credit_balances"][2]["id"]
    lines = apply_offsets(
        scenario["notice"]["id"],
        [a["id"] for a in scenario["accounts"]],
        scenario["notice"]["version"],
    )
    by_credit = _lines_by_credit_balance(lines)
    reverse_offset(by_credit[cb3]["id"], reason="Line applied to the wrong account")

    surviving = read_offset(by_credit[cb1]["id"])
    assert surviving["state"] == "APPLIED"
    assert surviving["applied_cents"] == 3_333

    released = read_credit_balance(cb3)
    assert released["offset_cents"] == 0
    assert released["outstanding_cents"] == 5_000
    assert read_account(scenario["accounts"][2]["id"])["balance_cents"] == -5_000


def test_offset_posting_drives_the_credit_balance_to_resolved_by_offset(api):
    """PRD §3.10: "Each line also posts a ledger row of `txn_type` `TAKE_BACK_OFFSET` with `source` `PAYER`, the notice's `payer_id`, a positive `amount_cents` equal to the line's `applied_cents`, on the credit balance's account; that posting's id is stored on the line as `posted_transaction_id`."
    PRD §3.10: "Hop 2 recomputes each touched credit balance's `offset_cents` and `outstanding_cents`. Hop 3 moves any credit balance whose recomputed `outstanding_cents` reaches 0 from `ATTRIBUTED` to `RESOLVED_BY_OFFSET`, bumping its `version` by 1."

    Design: Difficulty/transitive_cascade/offset_apply_cascade_posting_to_credit_balance_to_status_to_obligation_satisfied_by_offset
    """
    scenario = setup_take_back_scenario(
        accounts=[{"account_number": "ACCT-OF1", "charge_cents": 10_000,
                   "payment_cents": -14_000, "payment_source": "PAYER",
                   "financial_class": "INPATIENT"}],
        notice_number="TB-OF", total_recoup_cents=4_000, admin_fee_cents=0,
    )
    credit_balance_id = scenario["credit_balances"][0]["id"]

    lines = apply_offsets(
        scenario["notice"]["id"], [scenario["accounts"][0]["id"]],
        scenario["notice"]["version"],
    )
    line = lines[0]

    assert line["applied_cents"] == 4_000
    assert line["admin_fee_share_cents"] == 0
    assert line["posted_transaction_id"] is not None

    postings = list_transactions(
        scenario["accounts"][0]["id"], txn_type="TAKE_BACK_OFFSET"
    )
    assert len(postings) == 1
    assert postings[0]["amount_cents"] == 4_000

    credit_balance = read_credit_balance(credit_balance_id)
    assert credit_balance["offset_cents"] == 4_000
    assert credit_balance["outstanding_cents"] == 0
    assert credit_balance["status"] == "RESOLVED_BY_OFFSET"


def test_offset_cascade_settles_the_medicare_obligation_by_offset(api):
    """PRD §3.10: "Hop 4 settles the Medicare obligation on any such credit balance: an obligation in `OPEN`, `LATE` or `REPORTED` moves to `SATISFIED_BY_OFFSET` with `satisfied_at` stamped and `satisfaction_mode` set to `OFFSET`; an obligation that was `LATE` retains its accrued `penalty_cents`."
    PRD §3.10: "Finally the notice's own `version` is bumped by 1 and it steps forward: it becomes `PARTIALLY_APPLIED` when `remaining_unapplied_cents` after the call is still strictly greater than 0, and `FULLY_APPLIED` when that figure reaches exactly 0."

    Design: Difficulty/transitive_cascade/offset_apply_cascade_posting_to_credit_balance_to_status_to_obligation_satisfied_by_offset
    """
    scenario = setup_take_back_scenario(
        accounts=[{"account_number": "ACCT-OF1", "charge_cents": 10_000,
                   "payment_cents": -14_000, "payment_source": "PAYER",
                   "financial_class": "INPATIENT"}],
        notice_number="TB-OF", total_recoup_cents=4_000, admin_fee_cents=0,
    )
    credit_balance_id = scenario["credit_balances"][0]["id"]
    obligation_id = find_obligation_for_credit_balance(credit_balance_id)["id"]

    apply_offsets(
        scenario["notice"]["id"], [scenario["accounts"][0]["id"]],
        scenario["notice"]["version"],
    )

    obligation = read_obligation(obligation_id)
    assert obligation["state"] == "SATISFIED_BY_OFFSET"
    assert obligation["satisfaction_mode"] == "OFFSET"

    assert read_notice(scenario["notice"]["id"])["state"] == "FULLY_APPLIED"
    account = read_account(scenario["accounts"][0]["id"])
    assert account["balance_cents"] == 0
    assert account["credit_balance_cents"] == 0


def test_offset_apply_is_refused_while_the_notice_is_disputed(api):
    """PRD §3.10: "The notice must be `RECEIVED` or `PARTIALLY_APPLIED`; a `DISPUTED`, `FULLY_APPLIED` or `WITHDRAWN` notice refuses the call with `ERR_NOTICE_INVALID_STATE`."
    PRD §3.10: "While a notice is `DISPUTED` no further offset applications may be created against it."

    Design: Difficulty/cross_entity_state_dependency/offset_application_depends_on_take_back_notice_not_being_disputed
    """
    scenario = setup_take_back_scenario(
        accounts=[{"account_number": "ACCT-DI1", "charge_cents": 10_000,
                   "payment_cents": -14_000, "payment_source": "PAYER",
                   "financial_class": "INPATIENT"}],
        notice_number="TB-DI", total_recoup_cents=4_000, admin_fee_cents=0,
    )
    disputed = dispute_notice(
        scenario["notice"]["id"], scenario["payer"]["id"],
        dispute_reason="Provider contests the recoupment basis",
    )
    assert disputed["state"] == "DISPUTED"

    response = api.apply_offsets(
        scenario["notice"]["id"],
        create_offset_application_payload(
            [scenario["accounts"][0]["id"]], disputed["version"]
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_NOTICE_INVALID_STATE.value)


def test_offset_refused_on_a_disputed_notice_writes_no_line_and_no_posting(api):
    """PRD §3.10: "Eligibility is a strict filter. A credit balance qualifies for this waterfall only when its `account_id` is among the named `target_account_ids`, its `payer_id` equals the notice's `payer_id`, its `status` is `ATTRIBUTED` or `REFUND_PENDING`, its `payer_portion_cents` is strictly greater than 0 and its `outstanding_cents` is strictly greater than 0."
    PRD §3.10: "While a notice is `DISPUTED` no further offset applications may be created against it."

    Design: Difficulty/cross_entity_state_dependency/offset_application_depends_on_take_back_notice_not_being_disputed
    """
    scenario = setup_take_back_scenario(
        accounts=[{"account_number": "ACCT-DI1", "charge_cents": 10_000,
                   "payment_cents": -14_000, "payment_source": "PAYER",
                   "financial_class": "INPATIENT"}],
        notice_number="TB-DI", total_recoup_cents=4_000, admin_fee_cents=0,
    )
    disputed = dispute_notice(
        scenario["notice"]["id"], scenario["payer"]["id"],
        dispute_reason="Provider contests the recoupment basis",
    )
    validate_error(
        api.apply_offsets(
            scenario["notice"]["id"],
            create_offset_application_payload(
                [scenario["accounts"][0]["id"]], disputed["version"]
            ),
            ANALYST,
        ),
        ApiErrorId.ERR_NOTICE_INVALID_STATE.value,
    )

    notice = read_notice(scenario["notice"]["id"])
    assert notice["state"] == "DISPUTED"
    assert notice["applied_cents"] == 0
    assert notice["remaining_unapplied_cents"] == 4_000
    _, meta = validate_paginated(
        api.list_offset_applications(
            ANALYST, params={"take_back_notice_id": scenario["notice"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_credit_balance(scenario["credit_balances"][0]["id"])["offset_cents"] == 0
    assert read_account(scenario["accounts"][0]["id"])["balance_cents"] == -4_000


def _single_credit_notice_scenario():
    """One 3,000-cent PAYER credit plus an 8,000-cent notice already 3,000 applied."""
    scenario = setup_take_back_scenario(
        accounts=[{"account_number": "ACCT-CY1", "charge_cents": 10_000,
                   "payment_cents": -13_000, "payment_source": "PAYER",
                   "financial_class": "INPATIENT"}],
        notice_number="TB-CY", total_recoup_cents=8_000, admin_fee_cents=0,
    )
    scenario["lines"] = apply_offsets(
        scenario["notice"]["id"], [scenario["accounts"][0]["id"]],
        scenario["notice"]["version"],
    )
    return scenario


def test_notice_cycles_partially_applied_back_to_received_on_reversal(api):
    """PRD §3.10: "The notice itself then recomputes `applied_cents` and `remaining_unapplied_cents`, bumps its `version` by 1, and steps its `state` down — `FULLY_APPLIED → PARTIALLY_APPLIED` when applied cents remain after the reversal, and `PARTIALLY_APPLIED → RECEIVED` when `applied_cents` returns to exactly 0."
    PRD §3.10: "Reversal moves the line `APPLIED → REVERSED` and stamps `reversed_at`. Hop 1 posts a `REVERSAL` ledger row negating that line's `TAKE_BACK_OFFSET` posting exactly."

    Design: Difficulty/non_linear_state_machine/take_back_notice_cycles_partially_applied_back_to_received_and_dispute_round_trip
    """
    scenario = _single_credit_notice_scenario()
    line = scenario["lines"][0]
    assert read_notice(scenario["notice"]["id"])["state"] == "PARTIALLY_APPLIED"

    reversed_line = validate_success(
        api.reverse_offset_application(
            line["id"], {"reason": "Posted against the wrong account"}, ANALYST
        )
    )
    assert reversed_line["state"] == "REVERSED"

    notice = read_notice(scenario["notice"]["id"])
    assert notice["applied_cents"] == 0
    assert notice["remaining_unapplied_cents"] == 8_000
    assert notice["state"] == "RECEIVED"

    credit_balance = read_credit_balance(scenario["credit_balances"][0]["id"])
    assert credit_balance["offset_cents"] == 0
    assert credit_balance["outstanding_cents"] == 3_000
    assert credit_balance["status"] == "ATTRIBUTED"
    assert read_account(scenario["accounts"][0]["id"])["balance_cents"] == -3_000


def test_notice_makes_a_second_round_trip_through_dispute_and_withdrawal(api):
    """PRD §3.10: "Within the 45-day window — that is, while the logical clock is at or before the notice's `dispute_deadline_at` — a `PayerLiaison` acting for that same payer files a dispute with a `dispute_reason`, moving the notice from `RECEIVED` or `PARTIALLY_APPLIED` to `DISPUTED` and bumping its `version` by 1."
    PRD §3.10: "The same liaison may withdraw the dispute, taking the notice back to `RECEIVED` when its `applied_cents` is exactly 0 and to `PARTIALLY_APPLIED` when its `applied_cents` is strictly greater than 0, again bumping the `version` by 1 — and offsetting may then resume."

    Design: Difficulty/non_linear_state_machine/take_back_notice_cycles_partially_applied_back_to_received_and_dispute_round_trip
    """
    scenario = _single_credit_notice_scenario()
    reverse_offset(scenario["lines"][0]["id"], reason="Posted against the wrong account")
    assert read_notice(scenario["notice"]["id"])["state"] == "RECEIVED"

    disputed = validate_success(
        api.dispute_take_back_notice(
            scenario["notice"]["id"],
            {"dispute_reason": "Recoupment amount disputed by provider relations"},
            make_payer_liaison_headers(scenario["payer"]["id"]),
        )
    )
    assert disputed["state"] == "DISPUTED"

    withdrawn = validate_success(
        api.withdraw_take_back_dispute(
            scenario["notice"]["id"], {},
            make_payer_liaison_headers(scenario["payer"]["id"]),
        )
    )
    assert withdrawn["state"] == "RECEIVED"
    assert withdrawn["applied_cents"] == 0
    assert withdrawn["remaining_unapplied_cents"] == 8_000


def test_notice_number_is_unique_within_a_payer_but_reusable_across_payers(api):
    """PRD §3.10: "a `notice_number` that must be unique within that payer (a collision is `ERR_DUPLICATE_NOTICE_NUMBER`), a `total_recoup_cents` naming the amount the payer intends to recover, and an optional `admin_fee_cents` recording an administrative fee the payer withholds, defaulting to 0."
    PRD §3.10: "The notice is stamped with a `received_at` from the logical clock, given a `dispute_deadline_at` exactly 45 days after `received_at`, and opened in `state` `RECEIVED` with `applied_cents` at 0."

    Design: Corner/validations/duplicate_notice_number_within_payer_rejected_but_reusable_across_payers
    """
    medicare = seed_payer(payer_code="MCR", payer_type="MEDICARE",
                          name="Medicare Region A", take_back_allowed=True)
    commercial = seed_payer(payer_code="COM", payer_type="COMMERCIAL",
                            name="Meridian Commercial", take_back_allowed=True)
    first = record_take_back_notice(medicare["id"], "TB-9", 5_000)

    collision = api.create_take_back_notice(
        create_take_back_notice_payload(medicare["id"], "TB-9", 7_000),
        make_payer_liaison_headers(medicare["id"]),
    )
    validate_error(collision, ApiErrorId.ERR_DUPLICATE_NOTICE_NUMBER.value)

    other_payer = validate_success(
        api.create_take_back_notice(
            create_take_back_notice_payload(commercial["id"], "TB-9", 7_000),
            make_payer_liaison_headers(commercial["id"]),
        ),
        201,
    )
    assert other_payer["payer_id"] == commercial["id"]

    stored = read_notice(first["id"])
    assert stored["total_recoup_cents"] == 5_000
    assert stored["remaining_unapplied_cents"] == 5_000
    assert_instant_equals(
        stored["dispute_deadline_at"], "2026-09-15T00:00:00Z", "dispute_deadline_at"
    )


def test_payer_that_may_not_file_take_backs_is_refused(api):
    """PRD §3.10: "The payer must be permitted to file take-backs at all: a payer whose `take_back_allowed` is false is refused with `ERR_TAKE_BACK_NOT_PERMITTED` (HTTP 422)."

    Design: Corner/validations/take_back_notice_rejected_when_payer_take_back_flag_is_false
    """
    payer = seed_payer(payer_code="NRC", payer_type="COMMERCIAL",
                       name="No Recoup Health", take_back_allowed=False)

    response = api.create_take_back_notice(
        create_take_back_notice_payload(payer["id"], "TB-NR", 5_000),
        make_payer_liaison_headers(payer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TAKE_BACK_NOT_PERMITTED.value)

    _, meta = validate_paginated(
        api.list_take_back_notices(ANALYST, params={"payer_id": payer["id"]})
    )
    assert meta["total_count"] == 0


def test_dispute_filed_after_the_forty_five_day_window_is_refused(api):
    """PRD §3.10: "Within the 45-day window — that is, while the logical clock is at or before the notice's `dispute_deadline_at` — a `PayerLiaison` acting for that same payer files a dispute with a `dispute_reason`, moving the notice from `RECEIVED` or `PARTIALLY_APPLIED` to `DISPUTED` and bumping its `version` by 1. Once past the deadline the filing is refused with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/dispute_filed_after_the_forty_five_day_window_is_rejected
    """
    set_clock("2026-08-16T00:00:00Z")
    payer = seed_payer(payer_code="MCR", payer_type="MEDICARE",
                       name="Medicare Region A", take_back_allowed=True)
    notice = record_take_back_notice(payer["id"], "TB-LT", 5_000)
    set_clock("2026-10-01T00:00:00Z")

    response = api.dispute_take_back_notice(
        notice["id"], {"dispute_reason": "Filed after the window"},
        make_payer_liaison_headers(payer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value)

    stored = read_notice(notice["id"])
    assert_instant_equals(
        stored["dispute_deadline_at"], "2026-09-30T00:00:00Z", "dispute_deadline_at"
    )
    assert stored["state"] == "RECEIVED"


def test_offset_apply_with_no_eligible_credit_balance_is_refused(api):
    """PRD §3.10: "Eligibility is a strict filter. A credit balance qualifies for this waterfall only when its `account_id` is among the named `target_account_ids`, its `payer_id` equals the notice's `payer_id`, its `status` is `ATTRIBUTED` or `REFUND_PENDING`, its `payer_portion_cents` is strictly greater than 0 and its `outstanding_cents` is strictly greater than 0. If no credit balance passes that filter, the call is refused with `ERR_NO_ELIGIBLE_CREDIT` (HTTP 422)."

    Design: Corner/errors/offset_apply_with_no_eligible_credit_balance_is_rejected
    """
    scenario = setup_multi_credit_scenario(
        accounts=[{"account_number": "ACCT-NE1", "charge_cents": 10_000,
                   "payment_cents": -14_000, "payment_source": "PAYER",
                   "financial_class": "INPATIENT"}],
        payer_code="COM", payer_type="COMMERCIAL",
    )
    scenario["credit_balances"] = attribute_all(
        [cb["id"] for cb in scenario["credit_balances"]]
    )
    set_clock("2026-08-16T00:00:00Z")
    other_payer = seed_payer(payer_code="MCR", payer_type="MEDICARE",
                             name="Medicare Region A", take_back_allowed=True)
    notice = record_take_back_notice(other_payer["id"], "TB-NE", 4_000)

    response = api.apply_offsets(
        notice["id"],
        create_offset_application_payload(
            [scenario["accounts"][0]["id"]], notice["version"]
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_CREDIT.value)

    stored = read_notice(notice["id"])
    assert stored["state"] == "RECEIVED"
    assert stored["remaining_unapplied_cents"] == 4_000
    credit_balance = read_credit_balance(scenario["credit_balances"][0]["id"])
    assert credit_balance["offset_cents"] == 0
    assert credit_balance["status"] == "ATTRIBUTED"


def test_payer_liaison_may_not_record_a_notice_for_another_payer(api):
    """PRD §2.1: "Concretely, a `PayerLiaison` recording a take-back notice must supply a `payer_id` equal to its own `X-User-ID`, and a `PayerLiaison` disputing or withdrawing a dispute on an existing notice must be acting for the payer named on that notice; when it is not, the request is rejected with `ERR_PAYER_SCOPE_VIOLATION` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `PayerLiaison`, `X-User-ID` is the `id` of the acting `Payer` row; ownership checks on any resource that references a `Payer` compare the resource's payer foreign key to `X-User-ID`."

    Design: Corner/rbac/payer_liaison_cannot_record_a_notice_for_another_payer
    """
    medicare = seed_payer(payer_code="MCR", payer_type="MEDICARE",
                          name="Medicare Region A", take_back_allowed=True)
    commercial = seed_payer(payer_code="COM", payer_type="COMMERCIAL",
                            name="Meridian Commercial", take_back_allowed=True)

    response = api.create_take_back_notice(
        create_take_back_notice_payload(commercial["id"], "TB-XS", 5_000),
        make_payer_liaison_headers(medicare["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PAYER_SCOPE_VIOLATION.value)

    _, meta = validate_paginated(
        api.list_take_back_notices(ANALYST, params={"payer_id": commercial["id"]})
    )
    assert meta["total_count"] == 0


def test_stale_take_back_notice_version_rejects_the_second_offset_call(api):
    """PRD §2.7: "Applying offsets against a take-back notice requires a non-optional `expected_take_back_notice_version` field carrying the client's last observed `version` of that `TakeBackNotice`. A mismatch against the notice's current `version` is rejected with `ERR_STALE_VERSION` at HTTP 412."
    PRD §2.7: "A notice legitimately accepts repeated offset calls while it is still absorbing its recoupment pool, so a later call would otherwise succeed against a remaining-pool figure the client never saw."

    Design: Corner/cross_cutting_layers/occ_stale_take_back_notice_version_rejects_second_offset_call
    """
    scenario = setup_take_back_scenario(
        accounts=[
            {"account_number": "ACCT-ON1", "charge_cents": 10_000,
             "payment_cents": -13_000, "payment_source": "PAYER",
             "financial_class": "INPATIENT"},
            {"account_number": "ACCT-ON2", "charge_cents": 10_000,
             "payment_cents": -13_000, "payment_source": "PAYER",
             "financial_class": "INPATIENT"},
        ],
        notice_number="TB-ON", total_recoup_cents=8_000,
    )
    stale_version = scenario["notice"]["version"]
    apply_offsets(
        scenario["notice"]["id"], [scenario["accounts"][0]["id"]], stale_version
    )

    response = api.apply_offsets(
        scenario["notice"]["id"],
        create_offset_application_payload(
            [scenario["accounts"][1]["id"]], stale_version
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)

    notice = read_notice(scenario["notice"]["id"])
    assert notice["applied_cents"] == 3_000
    assert notice["remaining_unapplied_cents"] == 5_000
    assert notice["state"] == "PARTIALLY_APPLIED"
    untouched = read_credit_balance(scenario["credit_balances"][1]["id"])
    assert untouched["offset_cents"] == 0
    assert untouched["status"] == "ATTRIBUTED"
    _, meta = validate_paginated(
        api.list_offset_applications(
            ANALYST, params={"take_back_notice_id": scenario["notice"]["id"]}
        )
    )
    assert meta["total_count"] == 1
