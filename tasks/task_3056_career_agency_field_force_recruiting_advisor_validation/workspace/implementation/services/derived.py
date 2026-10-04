"""Derived postures, parallel licensing dimensions and the rollup ledger.

PRD §2.9 (four parallel dimensions + one derived posture), §2.7 (the three
ledger invariants) and §1.3 override_allocation / team production.
"""

from db import db
from errors import err, ERR_CREDIT_NOT_FOUND
from services import calc

PRIMARY_CHANNELS = ("PRIMARY", "SPLIT_LEAD", "SPLIT_SUPPORT")
ATTAINMENT_CHANNELS = ("PRIMARY", "SPLIT_LEAD", "SPLIT_SUPPORT", "RENEWAL")
LIVE_ATTAINMENT_STATUSES = ("ACCRUED", "PAID", "CHARGED_BACK")


# ---------------------------------------------------------------------------
# Logical clock side effects (PRD §2.5: "re-evaluates licence and registration
# expiry and the derived postures on the next read")
# ---------------------------------------------------------------------------
def sweep_expiries():
    now = db.now()
    for lic in db.licenses.values():
        if lic["status"] == "ACTIVE" and now >= lic["expires_at"]:
            lic["status"] = "LAPSED"
            db.touch(lic)
            refresh_license_dimension(lic["advisor_id"])
    for reg in db.registrations.values():
        if reg["status"] == "ACTIVE" and now >= reg["expires_at"]:
            reg["status"] = "SUSPENDED"
            db.touch(reg)
            refresh_registration_dimension(reg["advisor_id"])


def refresh_all_dimensions():
    for adv in db.advisors.values():
        refresh_license_dimension(adv["id"])
        refresh_registration_dimension(adv["id"])
        refresh_appointment_dimension(adv["id"])


def _aggregate(candidates, precedence):
    for value in precedence:
        if value in candidates:
            return value
    return precedence[-1]


def refresh_license_dimension(advisor_id):
    adv = db.advisors.get(advisor_id)
    if adv is None:
        return
    statuses = {l["status"] for l in db.licenses.values() if l["advisor_id"] == advisor_id}
    value = _aggregate(statuses, ("ACTIVE", "PENDING", "LAPSED", "NONE"))
    _set(adv, "insurance_license_status", value)


def refresh_registration_dimension(advisor_id):
    adv = db.advisors.get(advisor_id)
    if adv is None:
        return
    statuses = {r["status"] for r in db.registrations.values()
                if r["advisor_id"] == advisor_id}
    value = _aggregate(statuses, ("ACTIVE", "PENDING", "SUSPENDED", "NONE"))
    _set(adv, "securities_registration_status", value)


def refresh_appointment_dimension(advisor_id):
    adv = db.advisors.get(advisor_id)
    if adv is None:
        return
    statuses = {a["appointment_status"] for a in db.appointments.values()
                if a["advisor_id"] == advisor_id}
    value = _aggregate(statuses, ("APPROVED", "REQUESTED", "TERMINATED", "NONE"))
    _set(adv, "appointment_status", value)


def _set(adv, field, value):
    if adv.get(field) != value:
        adv[field] = value
        db.touch(adv)


# ---------------------------------------------------------------------------
# Sponsoring chain
# ---------------------------------------------------------------------------
def chain_above(advisor_id):
    """Ids of every ancestor reached by walking sponsoring_advisor_id upward."""
    seen = []
    current = db.advisors.get(advisor_id)
    while current is not None and current.get("sponsoring_advisor_id"):
        parent_id = current["sponsoring_advisor_id"]
        if parent_id in seen:
            break
        seen.append(parent_id)
        current = db.advisors.get(parent_id)
    return seen


def downline_closure(advisor_id):
    """Every advisor whose sponsoring chain reaches advisor_id, plus itself."""
    result = [advisor_id]
    for adv in db.advisors.values():
        if adv["id"] != advisor_id and advisor_id in chain_above(adv["id"]):
            result.append(adv["id"])
    return result


# ---------------------------------------------------------------------------
# Credit amounts (PRD §3.6 waterfall, §2.7 invariants)
# ---------------------------------------------------------------------------
def net_of(credit):
    return int(credit["gross_commission_cents"]) - int(credit.get("chargeback_assessed_cents", 0))


def refresh_credit_amounts(credit):
    credit["net_commission_cents"] = net_of(credit)


def helper_credits_of_policy(policy_id):
    return [c for c in db.credits.values() if c["policy_id"] == policy_id]


def channel_credits(advisor_id):
    return [c for c in db.credits.values()
            if c["advisor_id"] == advisor_id
            and c["credit_type"] in PRIMARY_CHANNELS
            and c["status"] != "VOIDED"]


# ---------------------------------------------------------------------------
# team production / overrides / balances (§1.3 override_allocation)
# ---------------------------------------------------------------------------
def recompute_team_production(advisor_id):
    """Sum of gross_commission_cents over PRIMARY / SPLIT_LEAD / SPLIT_SUPPORT
    credits with status != VOIDED, for the advisor and every advisor whose
    sponsoring chain reaches them.

    A terminated advisor's production leaves the live set: a terminated
    representative's credits are never voided (the per-policy conservation
    invariant in PRD §2.7 requires the sum to stay on the credits), so the
    team-production rollup of its sponsors must instead cease counting them.
    """
    adv = db.advisors.get(advisor_id)
    if adv is None:
        return
    total = 0
    for member_id in downline_closure(advisor_id):
        member = db.advisors.get(member_id)
        if member is None or member.get("contract_status") == "TERMINATED":
            continue
        for credit in channel_credits(member_id):
            total += int(credit["gross_commission_cents"])
    if adv.get("team_production_cents") != total:
        adv["team_production_cents"] = total
        db.touch(adv)


def recompute_all_team_production():
    for adv in list(db.advisors.values()):
        recompute_team_production(adv["id"])


def accruing_credits_under(ancestor_id):
    """(descendant_advisor, credit) pairs eligible to pass override up (§3.6)."""
    result = []
    for adv in db.advisors.values():
        if adv["id"] == ancestor_id:
            continue
        if adv.get("contract_status") != "VALIDATED":
            continue
        if ancestor_id not in chain_above(adv["id"]):
            continue
        for credit in channel_credits(adv["id"]):
            result.append((adv["id"], credit))
    return result


def recompute_overrides():
    """Full recomputation of every advisor's override income, then the office
    ledgers. Never increments — recomputation is what makes reversal exact."""
    for adv in db.advisors.values():
        office = db.district_offices.get(adv.get("district_office_id"))
        cap = office["override_cap_cents"] if office else calc.DEFAULT_OVERRIDE_CAP_CENTS
        pairs = accruing_credits_under(adv["id"])
        value = calc.override_income(adv, [c["gross_commission_cents"] for _, c in pairs], cap)
        if adv.get("override_income_cents") != value:
            adv["override_income_cents"] = value
            db.touch(adv)
    recompute_office_ledgers()


def recompute_office_ledgers():
    for office in db.district_offices.values():
        total = sum(adv.get("override_income_cents", 0) for adv in db.advisors.values()
                    if adv.get("district_office_id") == office["id"])
        if office.get("override_paid_cents") != total:
            office["override_paid_cents"] = total
            db.touch(office)


def recompute_chargeback_balance(advisor_id):
    adv = db.advisors.get(advisor_id)
    if adv is None:
        return
    total = sum(int(c["chargeback_assessed_cents"]) - int(c.get("recovered_cents", 0))
                for c in db.credits.values()
                if c["advisor_id"] == advisor_id and c["status"] == "CHARGED_BACK")
    if adv.get("chargeback_balance_cents") != total:
        adv["chargeback_balance_cents"] = total
        db.touch(adv)


def recompute_all_chargebacks():
    for adv in db.advisors.values():
        recompute_chargeback_balance(adv["id"])


# ---------------------------------------------------------------------------
# Credit construction
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Broad recomputation cascade (§3.6 triggers)
# ---------------------------------------------------------------------------
def cascade_rollups():
    recompute_all_team_production()
    recompute_overrides()


def credit_by_id(credit_id):
    credit = db.credits.get(credit_id)
    if credit is None:
        raise err(ERR_CREDIT_NOT_FOUND, "no commission credit with id %s" % credit_id)
    return credit