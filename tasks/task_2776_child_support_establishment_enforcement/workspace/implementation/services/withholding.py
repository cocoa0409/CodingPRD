"""Income-withholding arithmetic: the four movements and the aggregate cap
(PRD 3.4).  Percentages are held as Decimals and rendered as JSON numbers.
"""
from decimal import Decimal

import db
import util
from errors import ApiError
from services import interest

DISPOSABLE_DEDUCTION_PCT = Decimal("0.22")
ARREARS_RECOVERY_PCT = Decimal("0.20")
FEDERAL_CAP_BASE_PCT = Decimal("0.60")
FEDERAL_CAP_SECOND_FAMILY_PCT = Decimal("0.50")
FEDERAL_CAP_ARREARS_BUMP_PCT = Decimal("0.05")
ARREARS_BUMP_MULTIPLE = 3

# statutory_cap_pct is derived from the employer's state (PRD 3.4).
STATE_STATUTORY_CAP_PCT = {
    "TX": Decimal("0.50"),
    "WI": Decimal("0.50"),
}


def statutory_cap_pct(state_code):
    return STATE_STATUTORY_CAP_PCT.get(state_code)


def derive_disposable(reported, ncp):
    """Movement 1 — the supplied figure, else gross less a 22 percent deduction."""
    if reported is not None:
        return reported
    gross = ncp.get("monthly_gross_income_cents") or 0
    return gross - util.mul_round_half_up(gross, DISPOSABLE_DEDUCTION_PCT)


def compute(order, case, ncp, employer, reported_disposable):
    monthly = order.get("monthly_obligation_cents") or 0
    medical = order.get("medical_support_monthly_cents") or 0

    # Movement 1 — disposable income.
    disposable = derive_disposable(reported_disposable, ncp)

    # Movement 2 — what the order asks for.
    arrears_principal = interest.arrears_principal(case["id"])
    if arrears_principal > 0:
        arrears_recovery = util.mul_round_half_up(monthly, ARREARS_RECOVERY_PCT)
    else:
        arrears_recovery = 0
    requested = monthly + medical + arrears_recovery

    # Movement 3 — the consumer-credit ceiling.
    if ncp.get("supports_second_family"):
        federal = FEDERAL_CAP_SECOND_FAMILY_PCT
    else:
        federal = FEDERAL_CAP_BASE_PCT
    if arrears_principal >= ARREARS_BUMP_MULTIPLE * monthly:
        federal = federal + FEDERAL_CAP_ARREARS_BUMP_PCT
    state_cap = employer.get("statutory_cap_pct")
    ccpa = min(federal, state_cap) if state_cap is not None else federal
    ccpa_amount = util.mul_floor(disposable, ccpa)

    # Movement 4 — the employer fee shares the capped room.
    cap_room = ccpa_amount - (employer.get("remittance_fee_cents") or 0)
    withholding = max(0, min(requested, cap_room))
    employer_fee = (employer.get("remittance_fee_cents") or 0) if withholding > 0 else 0

    return {
        "reported_disposable_income_cents": disposable,
        "arrears_recovery_cents": arrears_recovery,
        "requested_amount_cents": requested,
        "federal_cap_pct": federal,
        "ccpa_cap_pct": ccpa,
        "ccpa_cap_amount_cents": ccpa_amount,
        "withholding_amount_cents": withholding,
        "employer_fee_cents": employer_fee,
    }


def obligor_live_iwos(obligor_id, exclude_id=None):
    """Every non-TERMINATED withholding order touching this obligor."""
    rows = []
    for iwo in db.withholding_orders.values():
        if exclude_id is not None and iwo["id"] == exclude_id:
            continue
        if iwo["service_status"] == "TERMINATED":
            continue
        order = db.orders.get(iwo["order_id"])
        if order is None:
            continue
        case = db.cases.get(order["case_id"])
        if case is None or case["noncustodial_party_id"] != obligor_id:
            continue
        rows.append(iwo)
    return rows


def enforce_aggregate_cap(obligor_id, candidate):
    """The aggregate cap binds on issuance and on every amendment (PRD 3.4)."""
    rows = obligor_live_iwos(obligor_id, exclude_id=candidate.get("id"))
    rows = rows + [candidate]
    total_disposable = sum(r.get("reported_disposable_income_cents") or 0 for r in rows)
    binding_pct = min(r["ccpa_cap_pct"] for r in rows)
    aggregate_cap = util.mul_floor(total_disposable, binding_pct)
    total_withholding = sum(r["withholding_amount_cents"] for r in rows)
    if total_withholding > aggregate_cap:
        raise ApiError("ERR_AGGREGATE_WITHHOLDING_EXCEEDS_CAP")


def recount_active_iwos(employer):
    """active_iwo_count counts ISSUED, SERVED and AMENDED rows (PRD 3.4)."""
    return len([i for i in db.withholding_orders.values()
                if i["employer_id"] == employer["id"]
                and i["service_status"] in ("ISSUED", "SERVED", "AMENDED")])
