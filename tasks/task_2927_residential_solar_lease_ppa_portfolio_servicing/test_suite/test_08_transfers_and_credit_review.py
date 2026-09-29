"""Transfer at sale: the intake fork, the field matrix and buyer credit.

One creation endpoint serves three destinations and forks the case itself, so
the assumption arm is underwritten while the buyout arms are priced later. The
tests below pin the fork, the four coherence directions of the field matrix,
the clamped and weighted credit sub-scores with their inclusive tiers, and the
two terminal exits that hand the agreement back to `ACTIVE`.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import assert_credit_counters, assert_identity_fields
from test_helpers.fixtures import (
    activate,
    book_ppa,
    clear_title,
    close_transfer,
    make_buyer,
    make_homeowner,
    make_tariff,
    open_assumption,
    open_prepayment,
    read_agreement,
    run_credit_review,
    set_clock,
)

# The shared PPA terms: contract year 2 of this agreement bills 12142 cents a
# month, which is the figure both the burden sub-score and the deposit use.
A1_TERMS = {
    "contract_start_date": "2025-01-01",
    "escalator_pct": 0.029,
    "base_ppa_rate_per_kwh_millicents": 14750,
    "guaranteed_annual_kwh": 9600,
    "guarantee_band_pct": 0.05,
}
YEAR_2_PAYMENT_CENTS = 12142
# A buyer earning this much has a payment target of 300000 cents, so the burden
# ratio is far below 1 and the burden sub-score clamps to its ceiling.
HIGH_INCOME_CENTS = 3000000


def _seller_and_tariff(api, clock="2026-08-01T00:00:00Z"):
    """Move the clock into contract year 2 and register the selling homeowner."""
    set_clock(api, clock)
    return make_homeowner(api), make_tariff(api)


def _active_ppa(api, seller_id, tariff_id, **overrides):
    terms = dict(A1_TERMS)
    terms.update(overrides)
    agreement = book_ppa(api, seller_id, tariff_id, **terms)
    activate(api, agreement["id"])
    return read_agreement(api, agreement["id"])


def _one_active_ppa(api, clock="2026-08-01T00:00:00Z"):
    seller, schedule = _seller_and_tariff(api, clock)
    return seller, _active_ppa(api, seller["id"], schedule["id"])


def _two_active_ppas(api, clock="2026-08-01T00:00:00Z"):
    """Two identically-priced agreements under one seller and one tariff row."""
    seller, schedule = _seller_and_tariff(api, clock)
    first = _active_ppa(api, seller["id"], schedule["id"])
    second = _active_ppa(
        api,
        seller["id"],
        schedule["id"],
        site_address="920 Alder Way, Fremont, CA",
    )
    return seller, first, second


def _read_case(api, transfer_case_id):
    return validate_success(
        api.get_transfer_case(transfer_case_id, U.agent_headers()), 200
    )


def _composite(case):
    """The two-decimal composite as a number, whatever JSON shape carries it."""
    return float(case["credit_composite_score"])


def test_one_endpoint_forks_the_case_into_two_different_initial_states(api):
    """An assumption opens in credit review; a prepayment opens unpriced.

    §3.8: "The case forks inside that single creation request, and the system
    takes the fork itself rather than letting the caller choose it. An
    `ASSUMPTION` lands in `status` `CREDIT_REVIEW` with `payoff_method` set to
    `NONE` and `payoff_quote_cents` at 0, because nothing is being bought out. A
    `PREPAYMENT` or `RELOCATION` lands in `INITIATED` and is priced later, at
    title clearance." §3.8: "In every case `seller_homeowner_id` is copied from
    the agreement's current `homeowner_id`, `successor_agreement_id` starts null,
    the five credit fields start null with `required_deposit_cents` at 0,
    `credit_decided_by_user_id` and `title_cleared_by_user_id` start null, and the
    agreement moves `ACTIVE → TRANSFER_PENDING` with its `version` advancing."

    Design: Difficulty/non_linear_state_machine/transfer_case_fork_assumption_vs_prepayment_from_same_creation_endpoint
    """
    seller, assumed, prepaid = _two_active_ppas(api)
    buyer = make_buyer(
        api,
        fico_score=760,
        dti_ratio=0.05,
        monthly_income_cents=HIGH_INCOME_CENTS,
    )
    before = assumed["version"]

    assumption = open_assumption(api, assumed["id"], "2026-08-20", buyer["id"])
    prepayment = open_prepayment(api, prepaid["id"], "2026-08-20")

    assert_identity_fields(assumption)
    assert assumption["status"] == C.TRANSFER_CREDIT_REVIEW
    assert assumption["transfer_type"] == C.TYPE_ASSUMPTION
    assert assumption["payoff_method"] == C.PAYOFF_NONE
    assert assumption["payoff_quote_cents"] == 0
    assert assumption["seller_homeowner_id"] == seller["id"]
    assert assumption["buyer_homeowner_id"] == buyer["id"]
    assert assumption["successor_agreement_id"] is None
    assert assumption["credit_fico_snapshot"] is None
    assert assumption["credit_dti_snapshot"] is None
    assert assumption["credit_composite_score"] is None
    assert assumption["credit_decision"] is None
    assert assumption["required_deposit_cents"] == 0
    assert assumption["credit_decided_by_user_id"] is None
    assert assumption["title_cleared_by_user_id"] is None

    assert prepayment["status"] == C.TRANSFER_INITIATED
    assert prepayment["transfer_type"] == C.TYPE_PREPAYMENT
    assert prepayment["seller_homeowner_id"] == seller["id"]

    parent = read_agreement(api, assumed["id"])
    assert parent["lifecycle_state"] == C.LIFECYCLE_TRANSFER_PENDING
    assert parent["version"] == before + 1
    assert parent["homeowner_id"] == seller["id"]
    assert (
        read_agreement(api, prepaid["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )


def test_neither_arm_may_borrow_the_other_arms_next_step(api):
    """Credit review has no edge out of INITIATED and clearance none out of review.

    §3.8: "Credit qualification is exclusive to the `CreditUnderwriter` and
    applies only to the assumption arm." §3.8: "On the assumption arm the case
    moves `CREDIT_APPROVED → TITLE_CLEARED`". §2.10 rung 8: "HTTP 409 on every
    action endpoint whose target is not in a state from which the requested
    transition exists. The generic code is `ERR_INVALID_STATE_TRANSITION`".

    Design: Difficulty/non_linear_state_machine/transfer_case_fork_assumption_vs_prepayment_from_same_creation_endpoint
    """
    _, assumed, prepaid = _two_active_ppas(api)
    buyer = make_buyer(
        api,
        fico_score=760,
        dti_ratio=0.05,
        monthly_income_cents=HIGH_INCOME_CENTS,
    )
    assumption = open_assumption(api, assumed["id"], "2026-08-20", buyer["id"])
    prepayment = open_prepayment(api, prepaid["id"], "2026-08-20")

    validate_error(
        api.run_credit_review(prepayment["id"], U.underwriter_headers()),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.clear_title(assumption["id"], U.title_headers()),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    still_open = _read_case(api, prepayment["id"])
    assert still_open["status"] == C.TRANSFER_INITIATED
    assert still_open["credit_decision"] is None

    still_reviewing = _read_case(api, assumption["id"])
    assert still_reviewing["status"] == C.TRANSFER_CREDIT_REVIEW
    assert still_reviewing["title_cleared_by_user_id"] is None
    assert still_reviewing["payoff_method"] == C.PAYOFF_NONE


def test_the_two_arms_rejoin_at_close_with_opposite_agreement_outcomes(api):
    """One closing hands the contract to a buyer, the other extinguishes it.

    §3.8: "An `ASSUMPTION` returns the agreement `TRANSFER_PENDING → ACTIVE` and
    replaces its `homeowner_id` with the `buyer_homeowner_id`. The three credit
    counters — `credit_balance_cents`, `credit_earned_cents` and
    `credit_applied_cents` — carry over to the new owner unchanged, because the
    obligation and its history are being assumed whole." §3.8: "A `PREPAYMENT`
    moves the agreement `TRANSFER_PENDING → PREPAID_CLOSED`." §3.8: "The
    `payoff_method` a case uses is determined by its `transfer_type` and is not a
    caller choice: `ASSUMPTION` uses `NONE`, `PREPAYMENT` uses
    `NPV_REMAINING_PAYMENTS`, and `RELOCATION` uses `UNAMORTIZED_SYSTEM_COST`."

    Design: Difficulty/non_linear_state_machine/transfer_case_fork_assumption_vs_prepayment_from_same_creation_endpoint
    """
    seller, assumed, prepaid = _two_active_ppas(api)
    buyer = make_buyer(
        api,
        fico_score=760,
        dti_ratio=0.05,
        monthly_income_cents=HIGH_INCOME_CENTS,
    )
    assumption = open_assumption(api, assumed["id"], "2026-08-20", buyer["id"])
    prepayment = open_prepayment(api, prepaid["id"], "2026-08-20")

    reviewed = run_credit_review(api, assumption["id"])
    assert reviewed["status"] == C.TRANSFER_CREDIT_APPROVED
    assert _composite(reviewed) == 86.67
    assert reviewed["credit_decision"] == C.CREDIT_APPROVED
    assert reviewed["required_deposit_cents"] == 0

    cleared_assumption = clear_title(api, assumption["id"])
    assert cleared_assumption["status"] == C.TRANSFER_TITLE_CLEARED
    assert cleared_assumption["payoff_method"] == C.PAYOFF_NONE
    assert cleared_assumption["payoff_quote_cents"] == 0
    assert cleared_assumption["title_cleared_by_user_id"] == U.TITLE_1

    cleared_prepayment = clear_title(api, prepayment["id"])
    assert cleared_prepayment["status"] == C.TRANSFER_TITLE_CLEARED
    assert cleared_prepayment["payoff_method"] == C.PAYOFF_NPV
    assert cleared_prepayment["payoff_quote_cents"] > 0

    set_clock(api, "2026-08-20T00:00:00Z")
    closed_assumption = close_transfer(api, assumption["id"])
    closed_prepayment = close_transfer(api, prepayment["id"])

    assert closed_assumption["status"] == C.TRANSFER_CLOSED
    new_owner = read_agreement(api, assumed["id"])
    assert new_owner["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert new_owner["homeowner_id"] == buyer["id"]
    assert_credit_counters(new_owner, earned=0, applied=0, balance=0)

    assert closed_prepayment["status"] == C.TRANSFER_CLOSED
    bought_out = read_agreement(api, prepaid["id"])
    assert bought_out["lifecycle_state"] == C.LIFECYCLE_PREPAID_CLOSED
    assert bought_out["homeowner_id"] == seller["id"]


def _assumption_for_buyer(api, agreement_id, **buyer_terms):
    """Open an assumption for a buyer described only by their credit inputs."""
    buyer = make_buyer(api, monthly_income_cents=HIGH_INCOME_CENTS, **buyer_terms)
    return buyer, open_assumption(api, agreement_id, "2026-09-01", buyer["id"])


def test_a_composite_of_exactly_seventy_two_is_approved_without_a_deposit(api):
    """FICO 712 lands the weighted sum on the threshold itself.

    §3.8: "The weighted sum is 0.55 times the FICO sub-score plus 0.30 times the
    debt sub-score plus 0.15 times the burden sub-score — weights that total
    exactly 1.00 — and `credit_composite_score` is that sum multiplied by 100 and
    rounded to exactly two decimal places." §3.8: "Otherwise, a
    `credit_composite_score` of at least 72.00 yields `APPROVED` with
    `required_deposit_cents` at 0." §3.8: "Both tier thresholds are inclusive, so a
    composite of exactly 72.00 is approved outright".

    Design: Difficulty/boundary_precision_check/credit_composite_exactly_seventy_two_approves_without_deposit
    """
    _, agreement = _one_active_ppa(api)
    buyer, case = _assumption_for_buyer(api, agreement["id"], fico_score=712, dti_ratio=0.09)

    reviewed = run_credit_review(api, case["id"])

    assert _composite(reviewed) == 72.00
    assert reviewed["credit_decision"] == C.CREDIT_APPROVED
    assert reviewed["required_deposit_cents"] == 0
    assert reviewed["status"] == C.TRANSFER_CREDIT_APPROVED
    assert reviewed["credit_fico_snapshot"] == 712
    assert float(reviewed["credit_dti_snapshot"]) == 0.09
    assert reviewed["credit_decided_by_user_id"] == U.CREDIT_1
    assert reviewed["buyer_homeowner_id"] == buyer["id"]
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )


def test_one_fico_point_lower_scores_seventy_one_seventy_five_and_needs_a_deposit(api):
    """The same buyer one point weaker falls to the deposit tier.

    §3.8: "Otherwise, a composite of at least 50.00 **together with** a
    `fico_score` of at least 620 yields `APPROVED_WITH_DEPOSIT`, and
    `required_deposit_cents` is three times the notional monthly payment for the
    agreement's `current_contract_year`." §3.8: "An approval or a
    deposit-conditioned approval moves the case `CREDIT_REVIEW → CREDIT_APPROVED`".

    Design: Difficulty/boundary_precision_check/credit_composite_exactly_seventy_two_approves_without_deposit
    """
    _, agreement = _one_active_ppa(api)
    _, case = _assumption_for_buyer(api, agreement["id"], fico_score=711, dti_ratio=0.09)

    reviewed = run_credit_review(api, case["id"])

    assert _composite(reviewed) == 71.75
    assert reviewed["credit_decision"] == C.CREDIT_APPROVED_WITH_DEPOSIT
    assert reviewed["required_deposit_cents"] == 3 * YEAR_2_PAYMENT_CENTS
    assert reviewed["required_deposit_cents"] == 36426
    assert reviewed["status"] == C.TRANSFER_CREDIT_APPROVED
    assert reviewed["credit_fico_snapshot"] == 711
    assert reviewed["credit_decided_by_user_id"] == U.CREDIT_1
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )


def test_a_buyer_past_both_ceilings_is_clamped_down_to_seventy(api):
    """FICO 820 caps the first sub-score at 1 and DTI 0.60 floors the second at 0.

    §3.8: "The FICO sub-score is the buyer's `fico_score` minus 580, divided by
    220 — the span from 580 up to 800 — and clamped into the range 0 through 1. The
    debt sub-score is 0.45 minus the buyer's `dti_ratio`, divided by 0.45, clamped
    the same way." §3.8: "None of the three sub-scores is rounded." §3.8: "It
    snapshots the buyer's `fico_score` into `credit_fico_snapshot` and their
    `dti_ratio` into `credit_dti_snapshot`".

    Design: Corner/calculations/credit_subscores_are_clamped_at_both_ends_before_weighting
    """
    _, agreement = _one_active_ppa(api)
    _, case = _assumption_for_buyer(api, agreement["id"], fico_score=820, dti_ratio=0.60)

    reviewed = run_credit_review(api, case["id"])

    assert reviewed["status"] == C.TRANSFER_CREDIT_APPROVED
    assert _composite(reviewed) == 70.00
    assert reviewed["credit_decision"] == C.CREDIT_APPROVED_WITH_DEPOSIT
    assert reviewed["required_deposit_cents"] == 36426
    assert reviewed["credit_fico_snapshot"] == 820
    assert float(reviewed["credit_dti_snapshot"]) == 0.60
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )


def test_a_decline_is_terminal_and_hands_the_agreement_straight_back(api):
    """FICO 610 clears the hard gate but misses the deposit tier's own gate.

    §3.8: "Otherwise, a composite of at least 50.00 **together with** a
    `fico_score` of at least 620 yields `APPROVED_WITH_DEPOSIT` ... Anything else is
    `DECLINED` with `required_deposit_cents` at 0." §3.8: "a decline moves it
    `CREDIT_REVIEW → CREDIT_DECLINED`, which is terminal, and simultaneously returns
    the agreement `TRANSFER_PENDING → ACTIVE` because that closing is dead."

    Design: Corner/state_machines/declined_credit_review_returns_the_agreement_to_active
    """
    seller, agreement = _one_active_ppa(api)
    _, case = _assumption_for_buyer(api, agreement["id"], fico_score=610, dti_ratio=0.00)

    assert case["status"] == C.TRANSFER_CREDIT_REVIEW
    assert case["payoff_method"] == C.PAYOFF_NONE
    assert case["payoff_quote_cents"] == 0

    reviewed = run_credit_review(api, case["id"])

    assert reviewed["status"] == C.TRANSFER_CREDIT_DECLINED
    assert _composite(reviewed) == 52.50
    assert reviewed["credit_decision"] == C.CREDIT_DECLINED
    assert reviewed["required_deposit_cents"] == 0
    assert reviewed["credit_fico_snapshot"] == 610
    assert float(reviewed["credit_dti_snapshot"]) == 0.00
    assert reviewed["credit_decided_by_user_id"] == U.CREDIT_1

    returned = read_agreement(api, agreement["id"])
    assert returned["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert returned["homeowner_id"] == seller["id"]


def test_a_cancelled_case_can_never_be_closed_afterwards(api):
    """Cancellation is terminal, so the buyout it abandoned cannot be revived.

    §3.8: "Cancelling returns the agreement `TRANSFER_PENDING → ACTIVE`". §3.8:
    "all moving the case to `CANCELLED`, which is terminal alongside `CLOSED` and
    `CREDIT_DECLINED`." §3.8: "Closing is available to a `ServicingAgent` or
    `PortfolioAdmin`, moves the case `TITLE_CLEARED → CLOSED`".

    Design: Corner/state_machines/cancelled_transfer_case_cannot_be_closed
    """
    _, agreement = _one_active_ppa(api)
    case = open_prepayment(api, agreement["id"], "2026-09-10")
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )

    cancelled = validate_success(
        api.cancel_transfer_case(case["id"], U.agent_headers()), 200
    )
    assert cancelled["status"] == C.TRANSFER_CANCELLED
    assert read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE

    validate_error(
        api.close_transfer_case(case["id"], U.agent_headers()),
        E.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    assert _read_case(api, case["id"])["status"] == C.TRANSFER_CANCELLED
    assert read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE


def test_a_second_closing_is_refused_until_the_first_one_is_terminal(api):
    """The open case earns the specific code, and cancelling it reopens the door.

    §3.8: "Only one transfer may be in flight per agreement: a second attempt
    while an existing case is `INITIATED`, `CREDIT_REVIEW`, `CREDIT_APPROVED` or
    `TITLE_CLEARED` is rejected with `ERR_TRANSFER_ALREADY_OPEN`". §2.10 rung 8:
    "`ERR_TRANSFER_ALREADY_OPEN` when a transfer case is opened while another for
    the same agreement is still in a non-terminal status".

    Design: Corner/validations/second_transfer_case_while_one_is_open_is_rejected_with_the_specific_code
    """
    _, agreement = _one_active_ppa(api)
    buyer = make_buyer(api)
    first = open_assumption(api, agreement["id"], "2026-09-15", buyer["id"])
    second_body = F.prepayment_payload(agreement["id"], "2026-10-01")

    validate_error(
        api.create_transfer_case(second_body, U.agent_headers()),
        E.ERR_TRANSFER_ALREADY_OPEN,
        409,
    )

    assert _read_case(api, first["id"])["status"] == C.TRANSFER_CREDIT_REVIEW
    assert (
        read_agreement(api, agreement["id"])["lifecycle_state"]
        == C.LIFECYCLE_TRANSFER_PENDING
    )
    rows, meta = validate_paginated(
        api.list_transfer_cases(U.agent_headers(), {"agreement_id": agreement["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]

    validate_success(api.cancel_transfer_case(first["id"], U.agent_headers()), 200)
    assert read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE

    replacement = validate_success(
        api.create_transfer_case(second_body, U.agent_headers()), 201
    )
    assert replacement["status"] == C.TRANSFER_INITIATED
    assert replacement["transfer_type"] == C.TYPE_PREPAYMENT


def test_the_field_matrix_is_enforced_in_all_four_directions(api):
    """Two optional fields, one required per type, and never the seller as buyer.

    §3.8: "`ASSUMPTION` hands the contract to a qualified buyer and requires
    `buyer_homeowner_id`, the purchasing homeowner, which must not be the
    agreement's current `homeowner_id`; it must not carry `new_site_address`.
    `PREPAYMENT` buys out the remaining term and carries neither of those two
    fields. `RELOCATION` moves the system to a new roof and requires
    `new_site_address` while forbidding `buyer_homeowner_id`. Any violation of that
    field matrix — a missing required field, a forbidden field supplied, or a buyer
    who is already the current homeowner — is rejected with
    `ERR_BUYER_FIELD_MISMATCH`." §2.10 rung 5: "HTTP 404 with the not-found code of
    the collection named by the unresolvable foreign key in the body".

    Design: Corner/validations/buyer_and_site_fields_that_contradict_the_transfer_type_are_rejected
    """
    seller, agreement = _one_active_ppa(api)
    buyer = make_buyer(api)
    before = read_agreement(api, agreement["id"])["version"]

    validate_error(
        api.create_transfer_case(
            {
                "agreement_id": agreement["id"],
                "transfer_type": C.TYPE_ASSUMPTION,
                "closing_date": "2026-09-15",
            },
            U.agent_headers(),
        ),
        E.ERR_BUYER_FIELD_MISMATCH,
        422,
    )
    validate_error(
        api.create_transfer_case(
            F.assumption_payload(agreement["id"], "2026-09-15", seller["id"]),
            U.agent_headers(),
        ),
        E.ERR_BUYER_FIELD_MISMATCH,
        422,
    )
    validate_error(
        api.create_transfer_case(
            F.assumption_payload(agreement["id"], "2026-09-15", NON_EXISTENT_UUID),
            U.agent_headers(),
        ),
        E.ERR_HOMEOWNER_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_transfer_case(
            F.prepayment_payload(
                agreement["id"], "2026-09-15", buyer_homeowner_id=buyer["id"]
            ),
            U.agent_headers(),
        ),
        E.ERR_BUYER_FIELD_MISMATCH,
        422,
    )
    validate_error(
        api.create_transfer_case(
            {
                "agreement_id": agreement["id"],
                "transfer_type": C.TYPE_RELOCATION,
                "closing_date": "2026-09-15",
            },
            U.agent_headers(),
        ),
        E.ERR_BUYER_FIELD_MISMATCH,
        422,
    )
    assert read_agreement(api, agreement["id"])["lifecycle_state"] == C.LIFECYCLE_ACTIVE
    assert read_agreement(api, agreement["id"])["version"] == before

    accepted = validate_success(
        api.create_transfer_case(
            F.relocation_payload(
                agreement["id"],
                "2026-09-15",
                new_site_address="55 Marina Blvd, Alameda, CA",
            ),
            U.agent_headers(),
        ),
        201,
    )
    assert accepted["status"] == C.TRANSFER_INITIATED
    assert accepted["new_site_address"] == "55 Marina Blvd, Alameda, CA"
    assert accepted["buyer_homeowner_id"] is None

    moved = read_agreement(api, agreement["id"])
    assert moved["lifecycle_state"] == C.LIFECYCLE_TRANSFER_PENDING
    assert moved["version"] == before + 1


def test_a_closing_date_is_checked_against_the_clock_twice(api):
    """A future closing at intake goes stale before the title agent gets to it.

    §3.8: "A `closing_date` strictly before the current clock date is rejected
    with `ERR_CLOSING_DATE_IN_PAST`." §3.8: "The `closing_date` is re-checked here
    against the clock and a closing that has slipped into the past is rejected with
    `ERR_CLOSING_DATE_IN_PAST`." §3.8: "On the prepayment and relocation arms the
    case moves directly `INITIATED → TITLE_CLEARED`, skipping credit review entirely
    because there is no buyer to underwrite".

    Design: Corner/errors/closing_date_before_the_clock_is_rejected_at_creation_and_again_at_clearance
    """
    _, agreement = _one_active_ppa(api)
    before = read_agreement(api, agreement["id"])["version"]

    validate_error(
        api.create_transfer_case(
            F.prepayment_payload(agreement["id"], "2026-07-31"), U.agent_headers()
        ),
        E.ERR_CLOSING_DATE_IN_PAST,
        422,
    )

    case = open_prepayment(api, agreement["id"], "2026-08-01")
    assert case["status"] == C.TRANSFER_INITIATED
    assert case["closing_date"] == "2026-08-01"
    after_creation = read_agreement(api, agreement["id"])
    assert after_creation["version"] == before + 1
    assert after_creation["lifecycle_state"] == C.LIFECYCLE_TRANSFER_PENDING

    set_clock(api, "2026-08-02T00:00:00Z")
    validate_error(
        api.clear_title(case["id"], U.title_headers()),
        E.ERR_CLOSING_DATE_IN_PAST,
        422,
    )

    stuck = _read_case(api, case["id"])
    assert stuck["status"] == C.TRANSFER_INITIATED
    assert stuck["title_cleared_by_user_id"] is None
    assert stuck["version"] == case["version"]
    assert read_agreement(api, agreement["id"])["version"] == before + 1
