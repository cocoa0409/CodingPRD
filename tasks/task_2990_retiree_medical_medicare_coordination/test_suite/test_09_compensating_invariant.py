"""Forward moves paired with their exact compensating moves.

Each pair is checked for a clean round trip on a conserved quantity: the
five-bucket reimbursement ledger, and the denormalised enrolled headcount on a
plan option that a second, untouched enrollment keeps off zero.
"""
from test_helpers import (
    assert_hra_ledger_conservation,
    assert_instant_equals,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    BILLING_1,
    COUNSELOR_1,
    COUNSELOR_2,
    HRA_ADMIN_2,
    make_enrollment_counselor_headers,
)


COVERED_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED")


def _submitted_dental_claim(api):
    """A Medicare-enrolled retiree with a 122206-cent account holding a
    30000-cent DENTAL_VISION_PREMIUM claim, clock at 2027-04-10.

    Returns {"account", "claim", "retiree_id"}. The account row returned is the
    post-hold reload, so its buckets already reflect the provisional hold.
    """
    funded = fx.hra_funded_retiree(api, covered_months=7)
    account = funded["hra_account"]
    assert account["funded_cents"] == 122206
    assert account["available_balance_cents"] == 122206

    fx.set_clock(api, "2027-04-10T00:00:00Z")
    claim = fx.make_claim(
        api,
        account,
        funded["retiree"]["id"],
        expense_category="DENTAL_VISION_PREMIUM",
        service_date="2027-03-15",
        submitted_cents=30000,
        documentation_reference="DV-INV-2027-0315",
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["provisional_eligible_cents"] == 30000

    held = fx.reload_hra_account(api, account["id"])
    assert held["available_balance_cents"] == 92206
    assert held["pending_hold_cents"] == 30000
    assert held["substantiated_paid_cents"] == 0
    assert held["premium_offset_cents"] == 0
    assert held["forfeited_cents"] == 0
    assert_hra_ledger_conservation(held)

    return {"account": held, "claim": claim, "retiree_id": funded["retiree"]["id"]}


def test_approval_revises_the_hold_and_payment_moves_it_to_substantiated_paid(api):
    """The forward half of the round trip, hop by hop, with the ledger conserved.

    PRD 3.7: "A `DENTAL_VISION_PREMIUM` expense is reimbursed at 5000 basis
    points, that is half of `submitted_cents`, truncated down to whole cents."
    and "The difference between `provisional_eligible_cents` and the final
    `eligible_cents` is then unwound: `pending_hold_cents` decreases by that
    difference and `available_balance_cents` increases by it". Payment then moves
    only between buckets: "`PAY` requires `status` `APPROVED` and moves it to
    `PAID`, sets `paid_at` to the logical clock, and moves the claim's
    `eligible_cents` out of `pending_hold_cents` and into
    `substantiated_paid_cents`, leaving `available_balance_cents` untouched."
    PRD 2.10 requires the five buckets to sum to funded_cents after every one of
    these mutations, not merely at the end.

    Design: Difficulty/compensating_invariant/claim_pay_then_reverse_restores_hra_ledger
    """
    state = _submitted_dental_claim(api)
    account_id = state["account"]["id"]

    approved = fx.review_claim(api, state["claim"]["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    assert approved["eligible_cents"] == 15000
    assert approved["provisional_eligible_cents"] == 30000

    after_approve = fx.reload_hra_account(api, account_id)
    assert after_approve["available_balance_cents"] == 107206
    assert after_approve["pending_hold_cents"] == 15000
    assert after_approve["substantiated_paid_cents"] == 0
    assert after_approve["funded_cents"] == 122206
    assert_hra_ledger_conservation(after_approve)

    paid = fx.settle_claim(api, state["claim"]["id"], "PAY")
    assert paid["status"] == "PAID"
    assert_instant_equals(paid["paid_at"], "2027-04-10T00:00:00.000Z", "paid_at")

    after_pay = fx.reload_hra_account(api, account_id)
    assert after_pay["pending_hold_cents"] == 0
    assert after_pay["substantiated_paid_cents"] == 15000
    assert after_pay["available_balance_cents"] == 107206
    assert after_pay["funded_cents"] == 122206
    assert_hra_ledger_conservation(after_pay)


def test_reversing_the_payment_restores_the_pre_claim_available_balance(api):
    """REVERSE returns exactly 15000 cents, not the 30000 first held.

    PRD 2.10: "A consequence worth stating on its own: paying a claim and then
    reversing that payment must return `available_balance_cents` to precisely the
    value it held before the payment, assuming no other activity intervened."
    Here the pre-payment balance is also the pre-claim balance, because approval
    had already unwound the provisional surplus. PRD 3.7 fixes the amount moved:
    "`REVERSE` requires `status` `PAID` and moves it to `REVERSED`, clears
    `paid_at`, and moves the claim's `eligible_cents` out of
    `substantiated_paid_cents` and back into `available_balance_cents`." So a
    reversal of the provisional 30000 would overshoot to 137206, and one that
    forgets the released hold would stop at 107206.

    Design: Difficulty/compensating_invariant/claim_pay_then_reverse_restores_hra_ledger
    """
    state = _submitted_dental_claim(api)
    account_id = state["account"]["id"]
    claim_id = state["claim"]["id"]

    fx.review_claim(api, claim_id, "APPROVE", reviewer_user_id=HRA_ADMIN_2)
    fx.settle_claim(api, claim_id, "PAY", settler_user_id=BILLING_1)

    reversed_claim = fx.settle_claim(api, claim_id, "REVERSE", settler_user_id=BILLING_1)
    assert reversed_claim["status"] == "REVERSED"

    account = fx.reload_hra_account(api, account_id)
    assert account["substantiated_paid_cents"] == 0
    assert account["available_balance_cents"] == 122206
    assert account["available_balance_cents"] != 137206
    assert account["available_balance_cents"] != 107206
    assert account["pending_hold_cents"] == 0
    assert account["premium_offset_cents"] == 0
    assert account["forfeited_cents"] == 0
    assert account["funded_cents"] == 122206
    assert_hra_ledger_conservation(account)


def _one_enrolled_retiree_and_one_reviewed_election(api):
    """PRE65-CORE carrying R4's PENDING enrollment and an UNDER_REVIEW election
    for R1, alongside a second ACTIVE option nobody elected, clock 2027-01-05.

    R4's enrollment is approved while the clock still stands at 2026-10-20, so it
    opens PENDING against the 2027-01-01 coverage_effective_date; the clock only
    moves past that date afterwards, and no sweep runs to activate it. PENDING is
    one of the three coverage states the PRD 2.10 headcount counts.

    Returns {"plan_year_id", "pre65_core_id", "exch_hra_id", "enrollment_r4",
    "election_r1"}.
    """
    program = fx.standard_program(api)
    plan_year_id = program["plan_year"]["id"]
    pre65_core_id = program["pre65_core"]["id"]
    exch_hra = fx.make_exch_hra(api, plan_year_id, activate=True)
    assert exch_hra["status"] == "ACTIVE"
    assert exch_hra["enrolled_count"] == 0

    r4 = fx.make_certified_retiree(api, plan_year_id, f.retiree_r4_payload())
    enrollment_r4 = fx.make_enrollment(
        api, r4["retiree"]["id"], plan_year_id, pre65_core_id
    )["enrollment"]

    r1 = fx.make_certified_retiree(api, plan_year_id, f.retiree_r1_payload())
    election_r1 = fx.make_election_event(
        api, r1["retiree"]["id"], plan_year_id, pre65_core_id, review=True
    )
    assert election_r1["status"] == "UNDER_REVIEW"

    fx.set_clock(api, "2027-01-05T00:00:00Z")
    assert fx.reload_plan_option(api, pre65_core_id)["enrolled_count"] == 1

    return {
        "plan_year_id": plan_year_id,
        "pre65_core_id": pre65_core_id,
        "exch_hra_id": exch_hra["id"],
        "enrollment_r4": enrollment_r4,
        "election_r1": election_r1,
    }


def _covered_rows(api, plan_option_id):
    """Rows on one option, and the subset counted by the headcount invariant."""
    rows, meta = validate_paginated(
        api.list_enrollments(
            make_enrollment_counselor_headers(COUNSELOR_1),
            {"plan_option_id": plan_option_id},
        )
    )
    covered = [row for row in rows if row["coverage_status"] in COVERED_STATUSES]
    return rows, covered, meta


def test_approving_the_second_election_adds_one_to_the_option_headcount(api):
    """The forward move takes the counter from 1 to 2 and the row set with it.

    PRD 2.10: "For every `PlanOption`, `enrolled_count` equals the number of
    enrollments referencing that option whose `coverage_status` is `PENDING`,
    `ACTIVE` or `SUSPENDED`" and "An approved election is the forward move that
    adds one". PRD 3.5 says the new coverage opens ACTIVE here because "Its
    `coverage_status` is `ACTIVE` when the logical clock has already reached that
    `coverage_effective_date`", the clock standing at 2027-01-05 against a
    2027-01-01 effective date.

    Design: Difficulty/compensating_invariant/election_approve_then_terminate_restores_enrolled_count
    """
    state = _one_enrolled_retiree_and_one_reviewed_election(api)

    approved = validate_success(
        api.decide_election_event(
            state["election_r1"]["id"],
            f.election_decision_payload("APPROVE"),
            make_enrollment_counselor_headers(COUNSELOR_2),
        )
    )
    assert approved["status"] == "APPROVED"

    enrollment_r1 = fx.reload_enrollment(api, approved["resulting_enrollment_id"])
    assert enrollment_r1["coverage_status"] == "ACTIVE"

    assert fx.reload_plan_option(api, state["pre65_core_id"])["enrolled_count"] == 2

    _rows, covered, _meta = _covered_rows(api, state["pre65_core_id"])
    assert len(covered) == 2
    assert sorted(fx.list_ids(covered)) == sorted(
        [state["enrollment_r4"]["id"], enrollment_r1["id"]]
    )


def test_terminating_the_new_enrollment_returns_the_headcount_to_one(api):
    """The compensating move lands on 1, not 0, because R4 is still covered.

    PRD 3.5: "Termination sets `coverage_status` to `TERMINATED`, closes the
    coverage interval by setting `coverage_end_date` to the logical clock, stores
    the supplied `termination_reason`, decrements the option's `enrolled_count`
    by 1 and increments that option's `version` — the exact compensating move for
    the increment an approval made, so that headcount conservation is restored".
    PRD 2.10 also binds the total: "summed across all options of a plan year,
    those counts equal the number of enrollments of that plan year in those same
    three coverage states". The terminated row is still returned by the listing,
    so the counter tracks the covered subset rather than the row count, and
    PRD 2.11 keeps the election itself out of it: coverage and election status are
    separate dimensions, so ending coverage does not rewind the approval.

    Design: Difficulty/compensating_invariant/election_approve_then_terminate_restores_enrolled_count
    """
    state = _one_enrolled_retiree_and_one_reviewed_election(api)

    approved = fx.decide_election_event(api, state["election_r1"]["id"], "APPROVE")
    enrollment_r1_id = approved["resulting_enrollment_id"]
    assert fx.reload_plan_option(api, state["pre65_core_id"])["enrolled_count"] == 2

    terminated = fx.terminate_enrollment(
        api,
        enrollment_r1_id,
        "RETIREE_VOLUNTARY_WITHDRAWAL",
        make_enrollment_counselor_headers(COUNSELOR_1),
    )
    assert terminated["coverage_status"] == "TERMINATED"
    assert_instant_equals(
        terminated["coverage_end_date"], "2027-01-05T00:00:00.000Z", "coverage_end_date"
    )
    assert terminated["termination_reason"] == "RETIREE_VOLUNTARY_WITHDRAWAL"

    pre65 = fx.reload_plan_option(api, state["pre65_core_id"])
    assert pre65["enrolled_count"] == 1
    assert pre65["enrolled_count"] != 0

    # R4's enrollment is untouched by R1's termination. It opened PENDING because
    # PRD 3.5 makes the new coverage "`ACTIVE` when the logical clock has already
    # reached that `coverage_effective_date` and `PENDING` when it has not" and the
    # clock stood at 2026-10-20 against a 2027-01-01 effective date; only the
    # sweep's Phase 1 activates a PENDING enrollment and no sweep has run. PENDING
    # is one of the three coverage states PRD 2.10 counts, so it stays covered.
    assert fx.reload_enrollment(api, state["enrollment_r4"]["id"])["coverage_status"] == (
        "PENDING"
    )

    rows, covered, meta = _covered_rows(api, state["pre65_core_id"])
    assert meta["total_count"] == 2
    assert len(rows) == 2
    assert len(covered) == 1
    assert fx.list_ids(covered) == [state["enrollment_r4"]["id"]]

    exch = fx.reload_plan_option(api, state["exch_hra_id"])
    assert pre65["enrolled_count"] + exch["enrolled_count"] == 1

    assert fx.reload_election_event(api, state["election_r1"]["id"])["status"] == (
        "APPROVED"
    )
