"""Settlement fee accrual and the enforcement ladder — PRD §2.6, §3.6, §3.8.
"""

from test_helpers import (
    STATUTORY_CAP_CENTS,
    ApiErrorId,
    compute_entry_fee_cents,
    compute_escalation_tier,
    compute_fine_base_cents,
    compute_fine_total_cents,
    create_active_participant,
    create_enforcement_action,
    create_payment_entry,
    create_upheld_actions,
    get_originator,
    get_payment_entry,
    make_platform_admin_headers,
    originate_entries,
    pay_enforcement,
    run_settlement,
    set_clock,
    setup_escalated_inquiry_action,
    setup_origination_stack,
    transition_enforcement,
    validate_error,
    validate_success,
)


def test_settlement_fee_round_per_entry_then_sum(api, admin_headers):
    """PRD §3.6: "The raw fee is five ten-millionths of the entry's
    `amount_cents` — equivalently, five cents per one hundred thousand dollars
    of entry amount — rounded half-up to a whole cent, with a one-cent minimum,
    and a fifty-cent surcharge added when the entry was flagged `same_day`."
    PRD §2.6: "The per-entry network settlement fee is rounded half-up to a
    whole cent **per entry** before any accumulation into a participant's
    period totals — summing raw fees across entries and rounding the total
    afterward is a different, explicitly rejected reading."

    Design: Difficulty/combinatorial_formula/settlement_fee_round_per_entry_then_sum
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    code = stack["transaction_code"]
    window = stack["window"]
    originator = stack["originator"]

    entries = originate_entries(originator, code, [15000000, 15000000])
    run = run_settlement(window["id"], at_iso="2026-09-01T18:00:00Z")
    assert run["settled_count"] == 2

    expected_fee = compute_entry_fee_cents(15000000)
    assert expected_fee == 8  # round_half_up(15000000 * 5 / 10000000) == 8
    for entry in entries:
        settled = get_payment_entry(entry["id"])
        assert settled["entry_fee_cents"] == expected_fee

    after = validate_success(api.get_participant(participant["id"], admin_headers))
    assert after["current_period_fees_cents"] == 2 * expected_fee
    assert after["current_period"] == "2026-09"


def test_enforcement_fine_tiered_escalation_with_late_accrual(api, admin_headers):
    """PRD §3.8: "The `escalation_tier` is the count of the participant's prior
    enforcement actions already in `UPHELD` or `PAID` status at creation time,
    capped at three."
    PRD §3.8: "The `fine_base_cents` is the tier's base amount — $50,000 for
    tier 0, $100,000 for tier 1, $250,000 for tier 2, and $500,000 for tier 3 —
    multiplied by 1.0 for an `ODFI` participant, 0.5 for an `RDFI`, or 1.5 for
    a `BOTH` participant (products that always land on whole cents), and then
    capped at the statutory maximum of $1,000,000."
    PRD §3.8: "Payment computes and freezes `fine_total_cents`: the base fine
    plus $1,000 for every day of lateness beyond a thirty-day grace period
    after `issued_date` — the overdue day count is the number of days between
    the paid date and `issued_date`, minus thirty, floored at zero — with the
    total again capped at $1,000,000, and `paid_at` stamped from the logical
    clock."

    Design: Difficulty/combinatorial_formula/enforcement_fine_tiered_escalation_with_late_accrual
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="RDFI")

    first = create_enforcement_action(participant, "MISSING_ACCOUNT_VALIDATION")
    assert first["escalation_tier"] == compute_escalation_tier(0)
    assert first["fine_base_cents"] == compute_fine_base_cents(0, "RDFI")
    assert first["fine_base_cents"] == 2500000

    paid = pay_enforcement(first["id"], at_iso="2026-10-16T09:00:00Z")
    expected_total = compute_fine_total_cents(
        first["fine_base_cents"], first["issued_date"], "2026-10-16"
    )
    assert expected_total == 4000000  # 2500000 + max(0, 45 - 30) * 100000
    assert paid["fine_total_cents"] == expected_total

    second = create_enforcement_action(participant, "LATE_ATTESTATION")
    assert second["escalation_tier"] == compute_escalation_tier(1)
    assert second["fine_base_cents"] == compute_fine_base_cents(1, "RDFI")
    assert second["fine_base_cents"] == 5000000
    assert second["fine_total_cents"] is None


def test_third_upheld_violation_suspends_participant_originators_and_entries(
    api, admin_headers
):
    """PRD §3.8: "Upholding is also where the three-strike rule bites: if,
    counting the action just upheld, the participant's cumulative number of
    enforcement actions in `UPHELD` or `PAID` status has reached at least
    three, the participant transitions from `ACTIVE` to `SUSPENDED` with the
    full suspension cascade of §2.9 — its approved originators are suspended
    and their still-`ORIGINATED` entries are cancelled with exposure released."
    PRD §2.9: "Suspending a participant suspends every one of its approved
    originators and, through them, cancels every entry those originators still
    hold in the originated-but-unsettled state, releasing the cancelled amounts
    from the originators' exposure figures."

    Design: Difficulty/transitive_cascade/third_upheld_violation_suspends_participant_originators_and_entries
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    code = stack["transaction_code"]
    originator = stack["originator"]
    entry = create_payment_entry(originator, code, amount_cents=50000)

    create_upheld_actions(participant, 2)
    mid = validate_success(api.get_participant(participant["id"], admin_headers))
    assert mid["status"] == "ACTIVE"  # two strikes do not suspend

    third = create_enforcement_action(participant, "EXCESSIVE_UNAUTHORIZED_RETURNS")
    upheld = transition_enforcement(third["id"], "UPHELD")
    assert upheld["status"] == "UPHELD"

    participant_after = validate_success(
        api.get_participant(participant["id"], admin_headers)
    )
    assert participant_after["status"] == "SUSPENDED"

    originator_after = get_originator(originator["id"])
    assert originator_after["status"] == "SUSPENDED"
    assert originator_after["committed_exposure_cents"] == 0

    entry_after = get_payment_entry(entry["id"])
    assert entry_after["status"] == "CANCELLED"


def test_fee_minimum_floor_applies(api, admin_headers):
    """PRD §3.6: "The raw fee is five ten-millionths of the entry's
    `amount_cents` — equivalently, five cents per one hundred thousand dollars
    of entry amount — rounded half-up to a whole cent, with a one-cent minimum,
    and a fifty-cent surcharge added when the entry was flagged `same_day`."

    Design: Corner/calculations/fee_minimum_floor_applies
    """
    stack = setup_origination_stack(with_receiver=False)
    entry = create_payment_entry(
        stack["originator"], stack["transaction_code"], amount_cents=1000
    )
    run_settlement(stack["window"]["id"], at_iso="2026-09-01T18:00:00Z")

    settled = get_payment_entry(entry["id"])
    # raw = 1000 * 5 / 10000000 == 0.0005 -> rounds to 0 -> floor of 1 applies.
    assert compute_entry_fee_cents(1000) == 1
    assert settled["entry_fee_cents"] == compute_entry_fee_cents(1000)


def test_fee_month_rollover_resets_accumulator(api, admin_headers):
    """PRD §3.6: "The fee then accrues onto the originating participant's
    `current_period_fees_cents`, with a monthly reset: if the settlement month
    (in `YYYY-MM` form) differs from the participant's `current_period`, the
    participant's `current_period` is first set to the settlement month and
    `current_period_fees_cents` reset to zero, and only then is the new fee
    added."

    Design: Corner/calculations/fee_month_rollover_resets_accumulator
    """
    stack = setup_origination_stack(with_receiver=False)
    participant = stack["participant"]
    code = stack["transaction_code"]
    window = stack["window"]
    originator = stack["originator"]

    create_payment_entry(originator, code, amount_cents=1000)
    run_settlement(window["id"], at_iso="2026-09-01T18:00:00Z")

    create_payment_entry(originator, code, amount_cents=1000, at_iso="2026-10-01T09:00:00Z")
    run_settlement(window["id"], at_iso="2026-10-01T18:00:00Z")

    after = validate_success(api.get_participant(participant["id"], admin_headers))
    assert after["current_period"] == "2026-10"
    assert after["current_period_fees_cents"] == compute_entry_fee_cents(1000)


def test_same_day_surcharge_added_to_fee(api, admin_headers):
    """PRD §3.6: "The raw fee is five ten-millionths of the entry's
    `amount_cents` — equivalently, five cents per one hundred thousand dollars
    of entry amount — rounded half-up to a whole cent, with a one-cent minimum,
    and a fifty-cent surcharge added when the entry was flagged `same_day`."

    Design: Corner/calculations/same_day_surcharge_added_to_fee
    """
    stack = setup_origination_stack(with_receiver=False)
    entry = create_payment_entry(
        stack["originator"], stack["transaction_code"],
        at_iso="2026-09-01T16:00:00Z",
        amount_cents=15000000,
        same_day=True, settlement_window_id=stack["window"]["id"],
    )
    run_settlement(stack["window"]["id"], at_iso="2026-09-01T18:00:00Z")

    settled = get_payment_entry(entry["id"])
    assert compute_entry_fee_cents(15000000, same_day=True) == 58
    assert settled["entry_fee_cents"] == compute_entry_fee_cents(
        15000000, same_day=True
    )


def test_fine_statutory_cap_reached(api, admin_headers):
    """PRD §3.8: "Payment computes and freezes `fine_total_cents`: the base
    fine plus $1,000 for every day of lateness beyond a thirty-day grace period
    after `issued_date` — the overdue day count is the number of days between
    the paid date and `issued_date`, minus thirty, floored at zero — with the
    total again capped at $1,000,000, and `paid_at` stamped from the logical
    clock."
    PRD §3.8: "Upholding is also where the three-strike rule bites: if,
    counting the action just upheld, the participant's cumulative number of
    enforcement actions in `UPHELD` or `PAID` status has reached at least
    three, the participant transitions from `ACTIVE` to `SUSPENDED` with the
    full suspension cascade of §2.9"

    Design: Corner/calculations/fine_statutory_cap_reached
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH")

    create_upheld_actions(participant, 3)
    suspended = validate_success(api.get_participant(participant["id"], admin_headers))
    assert suspended["status"] == "SUSPENDED"

    action = create_enforcement_action(participant, "LATE_ATTESTATION")
    assert action["escalation_tier"] == compute_escalation_tier(3)
    assert action["fine_base_cents"] == compute_fine_base_cents(3, "BOTH")
    assert action["fine_base_cents"] == 75000000

    paid = pay_enforcement(action["id"], at_iso="2027-10-06T09:00:00Z")
    expected_total = compute_fine_total_cents(
        action["fine_base_cents"], action["issued_date"], "2027-10-06"
    )
    # 75000000 + 370 * 100000 == 112000000, clamped to the statutory cap.
    assert expected_total == STATUTORY_CAP_CENTS
    assert paid["fine_total_cents"] == expected_total


def test_enforcement_uphold_by_escalating_admin_rejected(api, admin_headers):
    """PRD §3.8: "Upholding is segregation-of-duties protected: when the action
    was born of an escalation, the admin who escalated the parent inquiry may
    not be the one to uphold it, so an `X-User-ID` equal to
    `escalated_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` — a null
    `escalated_by_user_id` (direct filings) clears the check for any admin."
    PRD §3.8: "Either escalation moves the inquiry to `ESCALATED` (terminal)
    and creates an **EnforcementAction** in `ISSUED` status with the
    `participant_id` copied, the `inquiry_case_id` set to the escalated
    inquiry, a `violation_code` derived from the inquiry's `return_class` —
    `UNAUTHORIZED` maps to `EXCESSIVE_UNAUTHORIZED_RETURNS`, `ADMINISTRATIVE`
    to `EXCESSIVE_ADMINISTRATIVE_RETURNS`, and `OVERALL` also to
    `EXCESSIVE_UNAUTHORIZED_RETURNS` — and `escalated_by_user_id` recording the
    escalating admin's `X-User-ID`."

    Design: Corner/rbac/enforcement_uphold_by_escalating_admin_rejected
    """
    built = setup_escalated_inquiry_action(escalating_admin_id="pa-1")
    action = built["action"]
    assert action["violation_code"] == "EXCESSIVE_UNAUTHORIZED_RETURNS"
    assert action["escalated_by_user_id"] == "pa-1"
    assert action["inquiry_case_id"] == built["inquiry"]["id"]

    transition_enforcement(
        action["id"], "CONTESTED",
        admin_headers=make_platform_admin_headers("pa-1"),
    )

    refused = api.transition_enforcement_action(
        action["id"], {"to_state": "UPHELD"}, make_platform_admin_headers("pa-1")
    )
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    upheld = transition_enforcement(
        action["id"], "UPHELD",
        admin_headers=make_platform_admin_headers("pa-2"),
    )
    assert upheld["status"] == "UPHELD"

    # One upheld action is below the three-strike line: no suspension cascade.
    participant = validate_success(
        api.get_participant(built["stack"]["participant"]["id"], admin_headers)
    )
    assert participant["status"] == "ACTIVE"
