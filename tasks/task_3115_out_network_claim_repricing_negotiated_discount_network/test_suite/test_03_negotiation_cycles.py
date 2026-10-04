"""Difficulty queue: non-linear state machine — offer/counter cycle and the
settlement-void compensating action."""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_priced_claim, open_case, place_offer, counter_case,
    find_settlement_for_case,
)


def _setup_case_with_offer():
    """Priced 33000-fixture claim + case OPEN + payer offer 30000."""
    env = setup_priced_claim(claim_overrides={"external_claim_ref": "G1",
                                              "patient_responsibility_cents": 0})
    case = open_case(env["claim"]["id"], env["ctx"], opened_by="provider_rep")
    offered = get_success_data(place_offer(case["id"], 30000, case["version"],
                                           env["ctx"]))
    env["case"] = offered
    return env


def test_offer_counter_cycle_returns_to_offer_pending():
    """PRD §3.5: "From `COUNTERED`, a new payer offer returns the case to
    `OFFER_PENDING` and replaces `current_offer_cents`, again bounded above by
    `billed_amount_cents`."
    PRD §3.5: "The cycle `OPEN` to `OFFER_PENDING` to `COUNTERED` and back to
    `OFFER_PENDING` is intentionally non-linear and may repeat until agreement,
    withdrawal, or expiry."

    Design: Difficulty/non_linear_state_machine/negotiation_offer_counter_cycle_rounds
    """
    env = _setup_case_with_offer()
    ctx, case = env["ctx"], env["case"]
    get_success_data(counter_case(case["id"], 50000, ctx))
    reoffered = validate_success(
        place_offer(case["id"], 40000, case["version"] + 1, ctx), 200)
    assert reoffered["status"] == "OFFER_PENDING"
    assert reoffered["current_offer_cents"] == 40000


def test_round_count_increments_only_on_provider_counters():
    """PRD §3.5: "A valid counter moves the case from `OFFER_PENDING` to
    `COUNTERED`, sets `current_offer_cents` to the counter, and increments
    `round_count`."

    Design: Difficulty/non_linear_state_machine/negotiation_offer_counter_cycle_rounds
    """
    env = _setup_case_with_offer()
    ctx, case = env["ctx"], env["case"]
    first_counter = get_success_data(counter_case(case["id"], 50000, ctx))
    assert first_counter["round_count"] == 1
    reoffered = get_success_data(
        place_offer(case["id"], 40000, first_counter["version"], ctx))
    assert reoffered["round_count"] == 1, "payer offers must not increment round_count"
    second_counter = validate_success(counter_case(case["id"], 45000, ctx), 200)
    assert second_counter["status"] == "COUNTERED"
    assert second_counter["round_count"] == 2
    assert second_counter["current_offer_cents"] == 45000


def _setup_accepted_by_payer(ref="H1"):
    """Case: offer 30000, counter 50000, payer accepts -> ACCEPTED + settlement."""
    env = setup_priced_claim(claim_overrides={"external_claim_ref": ref,
                                              "patient_responsibility_cents": 0})
    case = open_case(env["claim"]["id"], env["ctx"])
    get_success_data(place_offer(case["id"], 30000, case["version"], env["ctx"]))
    get_success_data(counter_case(case["id"], 50000, env["ctx"]))
    get_success_data(api_client.accept_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]))
    settlement = find_settlement_for_case(case["id"], env["ctx"])
    env["case"] = get_success_data(api_client.get_negotiation_case(
        case["id"], env["ctx"]["payer_rep"]))
    env["settlement"] = settlement
    return env


def test_settlement_void_reverts_case_to_countered():
    """PRD §3.6: "If no signature has been recorded yet, a `PayerRep` may void
    the agreement instead: voiding moves the agreement to `VOIDED` and, as the
    compensating action, reverts the `NegotiationCase` from `ACCEPTED` back to
    `COUNTERED` with `current_offer_cents` unchanged."

    Design: Difficulty/non_linear_state_machine/settlement_void_compensates_case_back_to_countered
    """
    env = _setup_accepted_by_payer()
    voided = validate_success(
        api_client.void_settlement_agreement(env["settlement"]["id"],
                                             env["ctx"]["payer_rep"]), 200)
    assert voided["status"] == "VOIDED"
    case = validate_success(api_client.get_negotiation_case(
        env["case"]["id"], env["ctx"]["payer_rep"]), 200)
    assert case["status"] == "COUNTERED"
    assert case["current_offer_cents"] == 50000
    assert case["round_count"] == 1


def test_settlement_void_does_not_touch_claim_or_round_ledger():
    """PRD §3.6: "voiding moves the agreement to `VOIDED` and, as the
    compensating action, reverts the `NegotiationCase` from `ACCEPTED` back to
    `COUNTERED` with `current_offer_cents` unchanged."
    PRD §3.5: "A valid counter moves the case from `OFFER_PENDING` to
    `COUNTERED`, sets `current_offer_cents` to the counter, and increments
    `round_count`."

    Design: Difficulty/non_linear_state_machine/settlement_void_compensates_case_back_to_countered
    """
    env = _setup_accepted_by_payer(ref="H2")
    validate_success(api_client.void_settlement_agreement(
        env["settlement"]["id"], env["ctx"]["payer_rep"]), 200)
    case = validate_success(api_client.get_negotiation_case(
        env["case"]["id"], env["ctx"]["payer_rep"]), 200)
    assert case["round_count"] == 1, "void must not re-increment round_count"
    claim = validate_success(api_client.get_claim(
        env["claim"]["id"], env["ctx"]["payer_rep"]), 200)
    assert claim["status"] == "PRICED", "void before signature fires no settle cascade"
    assert claim["allowed_amount_cents"] == 33000
