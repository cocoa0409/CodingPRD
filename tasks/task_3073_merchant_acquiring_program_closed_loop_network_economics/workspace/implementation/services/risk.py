"""Merchant risk state: derived rolling counts and the suppression flag (PRD §3.7).

`rolling_chargeback_count`, `rolling_dispute_amount_cents`,
`unresolved_chargeback_count` and `suppression_flag` are derived, not stored
opinions, so they are recomputed from the dispute population on every read.
"""

from errors import ERR_NO_RISK_STATE, ApiError

# Ceilings.  The PRD names `UNRESOLVED_CB_CEILING` and "the unfavourable
# chargeback ratio" but publishes no figure for either.
UNRESOLVED_CB_CEILING = 3
CHARGEBACK_RATIO_CEILING_BPS = 100


def merchant_of_record(dispute):
    """final_merchant_id when the dispute is WON, else original_merchant_id."""
    if dispute["dispute_status"] == "WON":
        return dispute["final_merchant_id"]
    return dispute["original_merchant_id"]


def recompute(store, risk_state):
    """Recompute every derived field on one MerchantRiskState row."""
    merchant_id = risk_state["merchant_id"]
    rolling_count = 0
    rolling_amount = 0
    unresolved = 0
    for dispute in store.disputes.values():
        if merchant_of_record(dispute) != merchant_id:
            continue
        if dispute.get("chargeback_count_reserved", 0) == 1:
            rolling_count += 1
            rolling_amount += dispute["amount_cents"]
        if dispute["dispute_status"] in ("OPEN", "MERCHANT_RESPONDED"):
            unresolved += 1

    risk_state["rolling_chargeback_count"] = rolling_count
    risk_state["rolling_dispute_amount_cents"] = rolling_amount
    risk_state["unresolved_chargeback_count"] = unresolved
    risk_state["suppression_flag"] = (
        unresolved > UNRESOLVED_CB_CEILING
        or rolling_count * 10000 > CHARGEBACK_RATIO_CEILING_BPS * (unresolved + rolling_count)
    )
    return risk_state


def recompute_all(store):
    for risk_state in store.merchant_risk_states.values():
        recompute(store, risk_state)


def risk_state_of(store, merchant_id, required=True):
    risk_state = store.risk_state_for(merchant_id)
    if risk_state is None and required:
        raise ApiError(ERR_NO_RISK_STATE)
    return risk_state


def suppression_flag_of(store, merchant_id):
    risk_state = store.risk_state_for(merchant_id)
    return bool(risk_state and risk_state["suppression_flag"])


def create_risk_state(store, merchant_id):
    risk_state_id = store.new_id()
    now = store.clock.now()
    risk_state = {
        "id": risk_state_id,
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "_seq": store.next_created_seq(),
        "merchant_id": merchant_id,
        "rolling_chargeback_count": 0,
        "rolling_dispute_amount_cents": 0,
        "unresolved_chargeback_count": 0,
        "suppression_flag": False,
    }
    store.merchant_risk_states[risk_state_id] = risk_state
    store.risk_states_by_merchant[merchant_id] = risk_state_id
    return risk_state