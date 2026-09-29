"""Dual-variant risk scoring (PRD 3.1).

Six components, each floored to an integer in 0..100, then one weighted sum
rounded half up.  Two weight vectors produce two different numbers from the same
components.  A custodial party always scores 0 / LOW on both.
"""
from decimal import Decimal

import db
import util
from services import interest

ENFORCEMENT_WEIGHTS = {
    "arrears": 40,
    "delinquency": 25,
    "payment_history": 20,
    "locate": 10,
    "interstate": 5,
    "enforcement_history": 0,
}

COMPROMISE_WEIGHTS = {
    "payment_history": 40,
    "arrears": 25,
    "delinquency": 20,
    "enforcement_history": 15,
    "locate": 0,
    "interstate": 0,
}

_DELINQUENCY = {"NOT_DUE": 0, "CURRENT": 0, "DELINQUENT": 60, "DEFAULTED": 100}
_LOCATE = {"NOT_NEEDED": 0, "LOCATED": 0, "PENDING": 50, "UNLOCATABLE": 100}
_WORST_ORDER = ["NOT_DUE", "CURRENT", "DELINQUENT", "DEFAULTED"]


def live_obligor_cases(participant_id):
    return [c for c in db.obligor_cases(participant_id)
            if c["case_status"] != "CLOSED"]


def reference_obligation_cents(participant_id):
    """monthly_obligation_cents of the newest ENTERED CURRENT_SUPPORT order."""
    case_ids = {c["id"] for c in live_obligor_cases(participant_id)}
    candidates = [o for o in db.orders.values()
                  if o["case_id"] in case_ids
                  and o["status"] == "ENTERED"
                  and o["order_type"] == "CURRENT_SUPPORT"]
    if not candidates:
        return 0
    newest = max(candidates, key=lambda o: (o["created_at"], o["_seq"]))
    return newest.get("monthly_obligation_cents") or 0


def components(participant):
    pid = participant["id"]
    live = live_obligor_cases(pid)
    case_ids = {c["id"] for c in live}

    arrears_total = sum(interest.arrears_principal(c["id"]) for c in live)
    reference = reference_obligation_cents(pid)
    arrears = min(100, int(Decimal(arrears_total * 100) // max(1, reference * 12)))

    worst = None
    for iwo in db.withholding_orders.values():
        order = db.orders.get(iwo["order_id"])
        if order is None or order["case_id"] not in case_ids:
            continue
        if iwo["service_status"] == "TERMINATED":
            continue
        status = iwo["remittance_status"]
        if worst is None or _WORST_ORDER.index(status) > _WORST_ORDER.index(worst):
            worst = status
    delinquency = _DELINQUENCY.get(worst, 0) if worst is not None else 0

    charged = sum(c["total_charged_principal_cents"] for c in live)
    collected = sum(c["total_collected_principal_cents"] for c in live)
    if charged == 0:
        payment_history = 0
    else:
        payment_history = 100 - int(Decimal(collected * 100) // max(1, charged))
        payment_history = max(0, min(100, payment_history))

    locate = _LOCATE.get(participant["locate_status"], 0)

    action_count = 0
    for action in db.enforcement_actions.values():
        if action["case_id"] in case_ids and action["status"] in ("ACTIVE", "RELEASED"):
            action_count += 1
    enforcement_history = min(100, 25 * action_count)

    interstate_flag = 100 if any(c["interstate_role"] != "NONE" for c in live) else 0

    return {
        "arrears": arrears,
        "delinquency": delinquency,
        "payment_history": payment_history,
        "locate": locate,
        "enforcement_history": enforcement_history,
        "interstate": interstate_flag,
    }


def _score(parts, weights):
    total = sum(weights[name] * parts[name] for name in weights)
    return util.round_half_up(Decimal(total) / Decimal(100))


def tier(score):
    if score >= 67:
        return "HIGH"
    if score >= 34:
        return "MEDIUM"
    return "LOW"


def scores(participant):
    if participant["role_type"] == "CUSTODIAL_PARTY":
        return 0, "LOW", 0, "LOW"
    parts = components(participant)
    enforcement = _score(parts, ENFORCEMENT_WEIGHTS)
    compromise = _score(parts, COMPROMISE_WEIGHTS)
    return enforcement, tier(enforcement), compromise, tier(compromise)


def open_case_count(participant_id):
    return len([c for c in db.participant_cases(participant_id)
                if c["case_status"] != "CLOSED"])
