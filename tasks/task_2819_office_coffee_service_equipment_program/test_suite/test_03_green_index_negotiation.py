"""Green coffee repricing: the pass-through cap, the negotiation cycle, and the
basis-point threshold that decides whether a proposal exists at all.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_account, assert_price_adjustment
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    create_account,
    list_adjustments,
    propose_adjustment,
    read_account,
    read_adjustment,
    respond_adjustment,
    revise_adjustment,
    set_clock,
    set_market_index,
)
from test_helpers.test_users import TEST_USERS

BS = TEST_USERS["billing_specialist_headers"]


def _account_at_baseline(legal_name="Northgate Holdings LLC"):
    """A never-repriced customer whose signing index is 2000000 micro-dollars."""
    set_clock(ANCHOR_MONDAY)
    return create_account(
        legal_name=legal_name,
        billing_mode="CONSOLIDATED",
        green_index_baseline_micros=2000000,
        price_protection_days=90,
    )


def test_pass_through_cap_binds_and_the_proposal_alone_moves_no_prices():
    """A five-thousand-basis-point market move would pass through three thousand
    points, but the stored figure sits exactly on the cap and the account is
    untouched while the proposal is merely outstanding.

    "**Pass-through** is deliberately partial: we absorb some of the market. The
    raw pass-through is the movement multiplied by 6000 basis points — sixty
    percent — divided by 10000, rounded half up."

    "The stored `adjustment_pct_bps` is that raw pass-through clamped to the
    closed range from -1500 to 1500 basis points, so no single adjustment can
    move a customer's prices by more than fifteen percent in either direction."

    "A new proposal is created with `adj_status` `PROPOSED`, `revision_count` 0,
    `dispute_reason` null and `accepted_at` null, and nothing on the account
    changes yet."

    Design: Difficulty/combinatorial_formula/green_index_cap_binds_when_pass_through_exceeds_1500_bps
    """
    account = _account_at_baseline()
    set_market_index(3000000)

    adjustment = propose_adjustment(account["id"], effective_at="2026-09-01T00:00:00Z")
    assert_price_adjustment(adjustment)
    assert adjustment["index_baseline_micros"] == 2000000
    assert adjustment["index_current_micros"] == 3000000
    # A million micro-dollars over a two-million baseline is fifty percent.
    assert adjustment["movement_bps"] == 5000
    # Sixty percent of 5000 is 3000, which the cap cuts back to 1500.
    assert adjustment["adjustment_pct_bps"] == 1500
    assert adjustment["adjustment_pct_bps"] != 3000
    assert adjustment["adj_status"] == "PROPOSED"
    assert adjustment["revision_count"] == 0
    assert adjustment["dispute_reason"] is None
    assert adjustment["accepted_at"] is None

    unchanged = read_account(account["id"])
    assert_account(unchanged)
    assert unchanged["green_price_factor_bps"] == 10000
    assert unchanged["green_index_baseline_micros"] == 2000000
    assert unchanged["price_protection_until"] is None
    assert unchanged["version"] == account["version"]


def test_accepting_the_capped_adjustment_reprices_and_protects_the_account():
    """Acceptance lands the factor on the capped figure rather than the raw one,
    rebases the signing index, and opens a protection window that blocks the
    next proposal.

    "The account's `green_price_factor_bps` becomes 10000 plus the adjustment's
    `adjustment_pct_bps` — an **absolute** figure measured against the
    unmodified baseline of 10000, never compounded onto the previous factor, so
    two successive acceptances of 1000 basis points each leave the factor at
    11000 rather than 12100."

    "The account's `green_index_baseline_micros` is **re-based** to the
    adjustment's `index_current_micros`, so the next proposal measures movement
    from here rather than from the original signing index."

    "No new adjustment may be proposed while the account's
    `price_protection_until` is still ahead of the current instant; an attempt is
    rejected with `ERR_PRICE_PROTECTION_ACTIVE` (HTTP 422)."

    Design: Difficulty/combinatorial_formula/green_index_cap_binds_when_pass_through_exceeds_1500_bps
    """
    account = _account_at_baseline()
    set_market_index(3000000)
    adjustment = propose_adjustment(account["id"], effective_at="2026-09-01T00:00:00Z")

    accepted = respond_adjustment(adjustment["id"], account["id"], "ACCEPT")
    assert_price_adjustment(accepted)
    assert accepted["adj_status"] == "ACCEPTED"
    assert accepted["accepted_at"] == ANCHOR_MONDAY
    assert accepted["adjustment_pct_bps"] == 1500
    assert accepted["revision_count"] == 0

    repriced = read_account(account["id"])
    # 10000 plus the capped 1500, not 10000 plus the raw 3000.
    assert repriced["green_price_factor_bps"] == 11500
    assert repriced["green_price_factor_bps"] != 13000
    assert repriced["green_index_baseline_micros"] == 3000000
    # Ninety protection days from the anchor Monday.
    assert repriced["price_protection_until"] == "2026-11-01T08:00:00Z"
    assert repriced["version"] == account["version"] + 1

    set_market_index(6000000)
    response = api_client.create_price_adjustment(
        f.create_price_adjustment_payload(repriced["id"]), BS
    )
    validate_error(response, "ERR_PRICE_PROTECTION_ACTIVE", 422)
    assert len(list_adjustments(account_id=account["id"])) == 1


def _proposal_at_eight_hundred_bps():
    """A customer facing an exactly-adjustable rise, with one open proposal."""
    account = _account_at_baseline()
    set_market_index(2160000)
    adjustment = propose_adjustment(account["id"], effective_at="2026-09-01T00:00:00Z")
    assert adjustment["movement_bps"] == 800
    assert adjustment["adjustment_pct_bps"] == 480
    return account, adjustment


def test_dispute_revise_and_reproposal_end_in_acceptance_of_the_revised_figure():
    """The customer disputes, the operator moves toward the customer, and the
    second look is accepted — so the factor reflects the revised figure and not
    the original pass-through.

    "**Disputing** moves the adjustment `PROPOSED` → `DISPUTED`, stamps
    `dispute_reason`, and leaves every price on the account untouched."

    "A `BillingSpecialist` supplies a `revised_adjustment_pct_bps`, which
    replaces `adjustment_pct_bps`, increases `revision_count` by 1, and moves
    the adjustment `DISPUTED` → `PROPOSED` so the customer can look again."

    "**Accepting** moves the adjustment `PROPOSED` → `ACCEPTED`, stamps
    `accepted_at` with the current instant, and reprices the account in four
    coordinated writes."

    Design: Difficulty/non_linear_state_machine/price_adjustment_dispute_revise_reproposal_cycle_then_acceptance
    """
    account, adjustment = _proposal_at_eight_hundred_bps()

    disputed = respond_adjustment(
        adjustment["id"],
        account["id"],
        "DISPUTE",
        dispute_reason="Roast spec changed mid-quarter",
    )
    assert disputed["adj_status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Roast spec changed mid-quarter"
    assert disputed["adjustment_pct_bps"] == 480
    assert disputed["revision_count"] == 0
    # A dispute leaves every price alone.
    assert read_account(account["id"])["green_price_factor_bps"] == 10000

    revised = revise_adjustment(adjustment["id"], 240)
    assert revised["adj_status"] == "PROPOSED"
    assert revised["adjustment_pct_bps"] == 240
    assert revised["revision_count"] == 1
    # The movement is a market fact and a revision does not restate it.
    assert revised["movement_bps"] == 800

    accepted = respond_adjustment(adjustment["id"], account["id"], "ACCEPT")
    assert_price_adjustment(accepted)
    assert accepted["adj_status"] == "ACCEPTED"
    assert accepted["movement_bps"] == 800
    assert accepted["adjustment_pct_bps"] == 240
    assert accepted["accepted_at"] == ANCHOR_MONDAY

    repriced = read_account(account["id"])
    # The revised 240, not the originally proposed 480.
    assert repriced["green_price_factor_bps"] == 10240
    assert repriced["green_index_baseline_micros"] == 2160000
    assert repriced["price_protection_until"] == "2026-11-01T08:00:00Z"
    assert repriced["version"] == account["version"] + 1


def test_the_negotiation_cycle_may_run_a_second_round_before_acceptance():
    """Nothing limits how many times the customer may push back: a second
    dispute-and-revise round counts up and each revision must move further
    toward the customer.

    "The `PROPOSED` → `DISPUTED` → `PROPOSED` cycle has no fixed round limit;
    `revision_count` simply records how many rounds it has taken."

    "The revised figure may only move **toward** the customer: it must lie in
    the closed interval between 0 and the current `adjustment_pct_bps` inclusive
    — so for a current increase of 1200 basis points any value from 0 through
    1200 is acceptable and 1201 is not, and for a current reduction of -1200
    basis points the mirrored bound applies, admitting any value from -1200
    through 0."

    "A figure outside that interval is rejected with
    `ERR_REVISION_OUT_OF_BOUNDS` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/price_adjustment_dispute_revise_reproposal_cycle_then_acceptance
    """
    account, adjustment = _proposal_at_eight_hundred_bps()

    respond_adjustment(
        adjustment["id"], account["id"], "DISPUTE", dispute_reason="Roast spec changed mid-quarter"
    )
    # 481 is outside the closed interval running from 0 to the current 480.
    validate_error(
        api_client.revise_price_adjustment(adjustment["id"], f.revise_payload(481), BS),
        "ERR_REVISION_OUT_OF_BOUNDS",
        422,
    )
    still_disputed = read_adjustment(adjustment["id"])
    assert still_disputed["adj_status"] == "DISPUTED"
    assert still_disputed["adjustment_pct_bps"] == 480
    assert still_disputed["revision_count"] == 0

    first_round = revise_adjustment(adjustment["id"], 240)
    assert first_round["revision_count"] == 1

    respond_adjustment(
        adjustment["id"], account["id"], "DISPUTE", dispute_reason="Still above our budget"
    )
    # The interval has narrowed with the figure: 241 no longer qualifies.
    validate_error(
        api_client.revise_price_adjustment(adjustment["id"], f.revise_payload(241), BS),
        "ERR_REVISION_OUT_OF_BOUNDS",
        422,
    )
    second_round = revise_adjustment(adjustment["id"], 120)
    assert second_round["adj_status"] == "PROPOSED"
    assert second_round["adjustment_pct_bps"] == 120
    assert second_round["revision_count"] == 2

    accepted = respond_adjustment(adjustment["id"], account["id"], "ACCEPT")
    assert accepted["adj_status"] == "ACCEPTED"
    assert accepted["revision_count"] == 2
    assert read_account(account["id"])["green_price_factor_bps"] == 10120


def test_movement_of_799_800_and_801_bps_around_the_adjustable_threshold():
    """Three market quotes two hundred micro-dollars apart straddle the
    admissibility threshold, and the point just over it rounds its pass-through
    up rather than down.

    "A proposal is only admissible when the **magnitude** of that movement is at
    least 800 basis points — an eight-percent move in either direction. A
    movement of 799 basis points is not adjustable and is rejected with
    `ERR_INDEX_MOVEMENT_BELOW_THRESHOLD` (HTTP 422); a movement of exactly 800
    basis points is adjustable."

    "**Movement** is the signed difference between the current index and the
    baseline, multiplied by 10000 and divided by the baseline, rounded half up,
    and is stored in `movement_bps`."

    Design: Difficulty/boundary_precision_check/index_movement_at_799_800_and_801_bps_around_the_adjustable_threshold
    """
    account_a = _account_at_baseline()
    account_b = _account_at_baseline(legal_name="Southgate Partners LLC")
    payload_a = f.create_price_adjustment_payload(
        account_a["id"], effective_at="2026-09-01T00:00:00Z"
    )

    # 159800 over a 2000000 baseline is exactly 799 basis points.
    set_market_index(2159800)
    validate_error(
        api_client.create_price_adjustment(payload_a, BS),
        "ERR_INDEX_MOVEMENT_BELOW_THRESHOLD",
        422,
    )
    assert list_adjustments(account_id=account_a["id"]) == []

    # 160000 over the same baseline is exactly the 800-point threshold.
    set_market_index(2160000)
    at_threshold = validate_success(api_client.create_price_adjustment(payload_a, BS), 201)
    assert_price_adjustment(at_threshold)
    assert at_threshold["movement_bps"] == 800
    assert at_threshold["adjustment_pct_bps"] == 480
    assert at_threshold["adj_status"] == "PROPOSED"
    assert at_threshold["revision_count"] == 0
    assert at_threshold["index_baseline_micros"] == 2000000
    assert at_threshold["index_current_micros"] == 2160000

    # One point over the threshold: 801 * 0.6 = 480.6, which rounds half up.
    set_market_index(2160200)
    just_over = validate_success(
        api_client.create_price_adjustment(
            f.create_price_adjustment_payload(
                account_b["id"], effective_at="2026-09-01T00:00:00Z"
            ),
            BS,
        ),
        201,
    )
    assert just_over["movement_bps"] == 801
    assert just_over["adjustment_pct_bps"] == 481
    assert just_over["adjustment_pct_bps"] != 480

    # An outstanding proposal never moves a price on either customer.
    assert read_account(account_a["id"])["green_price_factor_bps"] == 10000
    assert read_account(account_b["id"])["green_price_factor_bps"] == 10000
    assert len(list_adjustments(account_id=account_a["id"])) == 1


def test_the_threshold_is_a_magnitude_so_the_falling_side_mirrors_it():
    """The same three distances measured downward behave identically, and the
    resulting pass-through carries the market's sign.

    "Its sign is preserved: a falling market produces a negative movement and,
    ultimately, a price reduction."

    "A proposal is only admissible when the **magnitude** of that movement is at
    least 800 basis points — an eight-percent move in either direction."

    Design: Difficulty/boundary_precision_check/index_movement_at_799_800_and_801_bps_around_the_adjustable_threshold
    """
    account_a = _account_at_baseline()
    account_b = _account_at_baseline(legal_name="Southgate Partners LLC")
    payload_a = f.create_price_adjustment_payload(
        account_a["id"], effective_at="2026-09-01T00:00:00Z"
    )

    # 159800 below the baseline is a movement of -799 basis points.
    set_market_index(1840200)
    validate_error(
        api_client.create_price_adjustment(payload_a, BS),
        "ERR_INDEX_MOVEMENT_BELOW_THRESHOLD",
        422,
    )
    assert list_adjustments(account_id=account_a["id"]) == []

    set_market_index(1840000)
    at_threshold = validate_success(api_client.create_price_adjustment(payload_a, BS), 201)
    assert at_threshold["movement_bps"] == -800
    assert at_threshold["adjustment_pct_bps"] == -480

    set_market_index(1839800)
    just_over = validate_success(
        api_client.create_price_adjustment(
            f.create_price_adjustment_payload(
                account_b["id"], effective_at="2026-09-01T00:00:00Z"
            ),
            BS,
        ),
        201,
    )
    assert just_over["movement_bps"] == -801
    assert just_over["adjustment_pct_bps"] == -481

    # A reduction is a real repricing: acceptance lands the factor below unity.
    accepted = respond_adjustment(at_threshold["id"], account_a["id"], "ACCEPT")
    assert accepted["adj_status"] == "ACCEPTED"
    reduced = read_account(account_a["id"])
    assert reduced["green_price_factor_bps"] == 9520
    assert reduced["green_index_baseline_micros"] == 1840000
