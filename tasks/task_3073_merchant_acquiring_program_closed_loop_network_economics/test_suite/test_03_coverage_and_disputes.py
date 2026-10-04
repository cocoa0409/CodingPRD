"""Coverage evidence, acceptance complaints, and the dispute lifecycle."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_industry_category,
    create_merchant,
    create_merchant_in_state,
    create_and_activate_merchant,
    create_cardmember,
    create_active_cardmember,
    submit_declined_attempt,
    rollup_gap,
    open_dispute,
    respond_to_dispute,
    resolve_dispute,
    file_complaint,
    take_up_complaint,
    get_complaint,
    get_dispute,
    get_merchant_risk_state,
    get_cardmember,
    list_acceptance_gaps,
    set_clock,
)
from test_helpers.fixtures import (
    ACQ,
    SERVICE,
    make_merchant_headers,
    make_cardmember_headers,
    setup_acceptance_gap_with_declines,
)

WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-31T00:00:00Z"


# ═══ Difficulty: acceptance-gap threshold crossing ═══════

def test_gap_below_the_decline_minimum_is_below_threshold(api):
    """PRD §3.2: "A count of one or two lands the gap at `BELOW_THRESHOLD`, and a
    count of zero lands it at `DORMANT`."

    Design: Difficulty/boundary_precision_check/acceptance_gap_qualifies_exactly_at_decline_minimum
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], region_code="US-NE")
    rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)
    for day in (10, 11):
        submit_declined_attempt(
            merchant["id"], attempted_amount_cents=100000,
            decline_reason="MERCHANT_NOT_ACCEPTED",
            occurred_at=f"2026-08-{day:02d}T00:00:00Z")
    gap = rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)

    assert gap["decline_count"] == 2
    assert gap["qualified_status"] == "BELOW_THRESHOLD", (
        "two declines sit one short of the inclusive threshold of three")


def test_gap_at_the_decline_minimum_qualifies_for_prospecting(api):
    """PRD §3.2: "A count of three or more qualifies the gap as `PROSPECTING` —
    the threshold is inclusive, so exactly three qualifies."

    Design: Difficulty/boundary_precision_check/acceptance_gap_qualifies_exactly_at_decline_minimum
    """
    set_clock()
    _, _, gap = setup_acceptance_gap_with_declines(decline_count=3)

    assert gap["decline_count"] == 3
    assert gap["qualified_status"] == "PROSPECTING", (
        "exactly three declines satisfies the >= threshold")


def test_gap_declined_volume_sums_the_attempted_amounts(api):
    """PRD §3.2: "`decline_count` is how many such attempts there were and
    `declined_volume_cents` is the sum of their `attempted_amount_cents`."

    Design: Difficulty/boundary_precision_check/acceptance_gap_qualifies_exactly_at_decline_minimum
    """
    set_clock()
    _, _, gap = setup_acceptance_gap_with_declines(
        decline_count=3, decline_amount_cents=100000)

    assert gap["decline_count"] == 3
    assert gap["declined_volume_cents"] == 300000


# ═══ Corner: gap input-set filtering ═════════════════════

def test_gap_excludes_declines_that_are_not_acceptance_failures(api):
    """PRD §3.2: "Only one of those reasons is evidence of a coverage hole, and
    only that one feeds the acceptance-gap engine: a `MERCHANT_NOT_ACCEPTED`
    decline counts toward a gap, while the other three reasons are recorded but
    never counted."

    Design: Corner/calculations/acceptance_gap_excludes_non_acceptance_decline_reasons
    """
    set_clock()
    category = create_industry_category()
    merchant = create_merchant(category["id"], region_code="US-NE")
    submit_declined_attempt(
        merchant["id"], attempted_amount_cents=100000,
        decline_reason="MERCHANT_NOT_ACCEPTED", occurred_at="2026-08-10T00:00:00Z")
    submit_declined_attempt(
        merchant["id"], attempted_amount_cents=100000,
        decline_reason="MERCHANT_NOT_ACCEPTED", occurred_at="2026-08-11T00:00:00Z")
    submit_declined_attempt(
        merchant["id"], attempted_amount_cents=1000000, card_product="GOLD",
        decline_reason="FRAUD_SUSPECT", occurred_at="2026-08-12T00:00:00Z")
    submit_declined_attempt(
        merchant["id"], attempted_amount_cents=1000000, card_product="GOLD",
        decline_reason="FRAUD_SUSPECT", occurred_at="2026-08-13T00:00:00Z")

    gap = rollup_gap("US-NE", category["id"], WINDOW_START, WINDOW_END, 30)
    assert gap["decline_count"] == 2, "only the two acceptance failures count"
    assert gap["declined_volume_cents"] == 200000, (
        "the 2000000 of fraud declines is excluded from the volume")
    assert gap["qualified_status"] == "BELOW_THRESHOLD"


# ═══ Difficulty: dispute priority boundary ═══════════════

def _member_and_merchant():
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    return category, merchant, member


def test_dispute_one_cent_below_the_boundary_is_standard_priority(api):
    """PRD §3.7: "its `priority` is set at creation and never changes
    thereafter: `HIGH` when the amount is at least fifty thousand cents, and
    `STANDARD` otherwise."

    Design: Difficulty/boundary_precision_check/dispute_priority_crosses_at_exact_amount
    """
    set_clock()
    _, merchant, member = _member_and_merchant()
    dispute = open_dispute(member["id"], merchant["id"], amount_cents=49999)

    assert dispute["amount_cents"] == 49999
    assert dispute["priority"] == "STANDARD", (
        "49999 cents sits one below the fifty-thousand-cent boundary")


def test_dispute_at_the_boundary_is_high_priority(api):
    """PRD §3.7: "`HIGH` when the amount is at least fifty thousand cents, and
    `STANDARD` otherwise."

    Design: Difficulty/boundary_precision_check/dispute_priority_crosses_at_exact_amount
    """
    set_clock()
    _, merchant, member = _member_and_merchant()
    dispute = open_dispute(member["id"], merchant["id"], amount_cents=50000)

    assert dispute["amount_cents"] == 50000
    assert dispute["priority"] == "HIGH", (
        "the boundary is inclusive: exactly 50000 cents is HIGH")


# ═══ Difficulty: dispute resolution points evaluation order ═══

def _support_points_for(amount_cents: int) -> int:
    """The member's credit for a resolution worth ``amount_cents``: the gross
    resolution rounded half up (one point per dollar) less the merchant share,
    which is the amount times MERCHANT_SHARE_BPS (two fifths) over ten thousand
    and rounded half up."""
    from decimal import Decimal, ROUND_HALF_UP

    def rhu(x):
        return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    resolution = rhu(Decimal(amount_cents) / Decimal(100))
    share = rhu(Decimal(amount_cents) * Decimal(4000) / Decimal(10000) / Decimal(100))
    return resolution - share


def test_won_dispute_credits_points_in_the_pinned_evaluation_order(api):
    """PRD §3.7: "First, the dispute resolution points are the resolved amount
    divided by one hundred and rounded half up — one point per dollar. Second,
    the merchant share is the resolved amount multiplied by `MERCHANT_SHARE_BPS`,
    which is two fifths, divided by ten thousand and rounded half up, when the
    dispute was adjudicated against the merchant, and is zero otherwise. Third,
    the net points are the resolution points less the merchant share."

    Design: Difficulty/combinatorial_formula/dispute_outcome_points_evaluation_order_mode_c
    """
    set_clock()
    category = create_industry_category()
    merchant_1 = create_and_activate_merchant(category["id"], merchant_name="Points Merchant 1")
    merchant_2 = create_and_activate_merchant(category["id"], merchant_name="Points Merchant 2")
    member = create_cardmember(member_name="Member Points")

    amount = 60050
    dispute = open_dispute(member["id"], merchant_1["id"], merchant_2["id"], amount_cents=amount)
    # Only a HIGH-priority dispute (>= 50000 cents) is contestable on the merits,
    # so the response carries an explicit amount above the minimum; the point
    # arithmetic under test is driven by the dispute's disputed amount.
    respond_to_dispute(dispute, merchant_1["id"])
    # The credit lands on the branch adjudicated against the merchant with an
    # apology credit granted to the member (PRD §3.7).
    resolved = resolve_dispute(dispute["id"], "LOST_WITH_MEMBER_CREDIT")
    assert resolved["dispute_status"] == "LOST"

    member_after = get_cardmember(member["id"])
    assert member_after["reward_points_balance"] == _support_points_for(amount), (
        "601 resolution points less the 240-point merchant share")


def test_won_dispute_rounding_the_net_directly_is_the_forbidden_order(api):
    """PRD §3.7: "The rounding is applied to the gross resolution first and to
    the merchant share second; rounding the net directly — applying the
    complement of the share to the amount and rounding once — is the forbidden
    order and drifts by a point for amounts such as 60050 cents."

    Design: Difficulty/combinatorial_formula/dispute_outcome_points_evaluation_order_mode_c
    """
    set_clock()
    category = create_industry_category()
    merchant_1 = create_and_activate_merchant(category["id"], merchant_name="Points Merchant 1")
    merchant_2 = create_and_activate_merchant(category["id"], merchant_name="Points Merchant 2")
    member = create_cardmember(member_name="Member Points")

    amount = 60050
    dispute = open_dispute(member["id"], merchant_1["id"], merchant_2["id"], amount_cents=amount)
    respond_to_dispute(dispute, merchant_1["id"])
    resolve_dispute(dispute["id"], "LOST_WITH_MEMBER_CREDIT")

    credited = get_cardmember(member["id"])["reward_points_balance"]
    # The forbidden order rounds round_half_up(60050 * 6000 / 10000) = 360 in one step.
    assert credited != 360, (
        "the net must be rounded per step, not computed by rounding the complement")
    assert credited == _support_points_for(amount)


def test_won_dispute_reseats_the_chargeback_onto_the_final_merchant(api):
    """PRD §3.7: "Resolution in the merchant's favour is the liability-redirecting
    outcome: liability moves from the `original_merchant_id` to the
    `final_merchant_id`, the originating merchant's rolling chargeback count on
    both the acquirer liability ledger and its `MerchantRiskState` falls by one
    while the final merchant's rises by one"

    Design: Difficulty/combinatorial_formula/dispute_outcome_points_evaluation_order_mode_c
    """
    set_clock()
    category = create_industry_category()
    merchant_1 = create_and_activate_merchant(category["id"], merchant_name="Points Merchant 1")
    merchant_2 = create_and_activate_merchant(category["id"], merchant_name="Points Merchant 2")
    member = create_cardmember(member_name="Member Points")

    dispute = open_dispute(member["id"], merchant_1["id"], merchant_2["id"], amount_cents=60050)
    respond_to_dispute(dispute, merchant_1["id"])
    resolve_dispute(dispute["id"], "WON")

    assert get_merchant_risk_state(merchant_1["id"])["rolling_chargeback_count"] == 0
    assert get_merchant_risk_state(merchant_2["id"])["rolling_chargeback_count"] == 1


# ═══ Corner: dispute response precondition ═══════════════

def test_dispute_below_the_response_minimum_cannot_be_contested(api):
    """PRD §3.7: "the dispute's `amount_cents` must be at least fifty thousand
    cents. A response attempted on a dispute below that amount is refused with
    `ERR_RESPOND_AMOUNT_TOO_LOW` (HTTP 403), which is why only `HIGH`-priority
    disputes can be contested on the merits."

    Design: Corner/state_machines/dispute_response_below_amount_minimum_returns_forbidden
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember()
    dispute = open_dispute(member["id"], merchant["id"], amount_cents=10000)
    assert dispute["priority"] == "STANDARD"

    res = api_client.respond_to_dispute(
        dispute["id"], make_merchant_headers(merchant["id"]))
    validate_error(res, ApiErrorId.ERR_RESPOND_AMOUNT_TOO_LOW.value, expected_status=403)
    assert get_dispute(dispute["id"])["dispute_status"] == "OPEN"


# ═══ Corner: complaint lifecycle ═════════════════════════

def test_complaint_starts_filed_and_rejects_a_second_take_up(api):
    """PRD §3.8: "A complaint is filed against a `merchant_id` by a
    `cardmember_id` with a `complaint_type` of `MERCHANT_NOT_ACCEPTED`,
    `STAFF_ATTITUDE`, `TERMINAL_TECHNICAL`, or `PRICING_SURCHARGE`, and it opens
    in `FILED`."
    PRD §3.8: "Taking the complaint up moves it from `FILED` to `UNDER_REVIEW`"

    Design: Corner/state_machines/complaint_created_starts_filed_and_take_up_is_idempotent_guarded
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember(card_product="GOLD")
    complaint = file_complaint(merchant["id"], member["id"])
    assert complaint["complaint_status"] == "FILED"

    taken_up = take_up_complaint(complaint["id"])
    assert taken_up["complaint_status"] == "UNDER_REVIEW"

    res = api_client.take_up_complaint(complaint["id"], SERVICE)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_take_up_reports_the_new_state_on_the_same_response(api):
    """PRD §3.8: "Taking the complaint up moves it from `FILED` to
    `UNDER_REVIEW`, and from there the desk has three ways forward."

    Design: Corner/endpoints/complaint_take_up_moves_filed_to_under_review
    """
    set_clock()
    category = create_industry_category()
    merchant = create_and_activate_merchant(category["id"])
    member = create_active_cardmember(card_product="GREEN")
    complaint = file_complaint(
        merchant["id"], member["id"], complaint_type="STAFF_ATTITUDE")

    taken_up = take_up_complaint(complaint["id"])
    assert taken_up["complaint_status"] == "UNDER_REVIEW"

    re_read = get_complaint(complaint["id"])
    assert re_read["complaint_status"] == "UNDER_REVIEW"
    assert re_read["complaint_type"] == "STAFF_ATTITUDE"