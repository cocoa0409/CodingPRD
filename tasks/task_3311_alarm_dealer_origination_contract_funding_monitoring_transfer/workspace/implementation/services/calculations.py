"""Calculation rules — SCAFFOLD §1.3, PRD §3. All money is integer cents.

Rounding is round-half-up at every named step (PRD §2.7).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from services import queries
from util import (add_days, add_months, coerce_dt, month_label, round_half_up,
                  round_percent2, whole_calendar_days, whole_calendar_months,
                  within_trailing_months)

# --- constants (SCAFFOLD §1.3) -------------------------------------------
BASE_FEE_CENTS_BY_CONFIG = {"BASE": 14900, "PREMIUM": 24900, "ELITE": 34900}
DEALER_FUNDING_POINTS_BY_TIER = {"TIER_1": 1.03, "TIER_2": 1.00, "TIER_3": 0.97}
MONITORING_SHARE_PCT = Decimal("0.60")
EQUIPMENT_SHARE_PCT = Decimal("0.02")
DEALER_ONBOARDING_FEE_CENTS = 149
DEALER_CHARGEBACK_RATE_CAP_PERCENT = Decimal("12.00")
TRAILING_WINDOW_MONTHS = 12
KNOWN_ALARM_RATE_CAP_PERCENT = Decimal("35.00")
TRAILING_WINDOW_DAYS = 30
POST_WARRANTY_SERVICE_SWEEP_PCT = Decimal("0.20")
DEALER_VISIT_FEE_CENTS = 89
POST_WARRANTY_SWEEP_THRESHOLD_CENTS = 15000
HOLDBACK_CEILING_PCT = Decimal("0.15")
DEALER_CHARGEBACK_PCT = Decimal("0.10")
DEFERRED_MONITORING_PCT = Decimal("0.10")
AMORTISATION_WINDOW_MONTHS = 3
DEALER_SUSPEND_BALANCE_THRESHOLD_CENTS = 500000
FUNDING_WINDOW_DAYS = 10
RESCISSION_WINDOW_DAYS = 5
CREDIT_FLOOR = 620
TERM_FLOOR = 36
EQUIPMENT_PERMITTED = {"DIRECT": {"BASE", "PREMIUM", "ELITE"}, "DEALER": {"BASE", "PREMIUM"}}
CREDIT_FLOOR_FREEZE_CODE = "ERR_CREDIT_SCORE_BELOW_FLOOR"
RELOCATION_RADIUS = {"TX", "OK", "NM", "AR", "LA"}
DEALER_BACKLOG_THRESHOLD = 8
MASS_CANCEL_LIMIT = 3
VERIFIED_WINDOW_BEFORE_SECONDS = 30
VERIFIED_WINDOW_AFTER_SECONDS = 120
ABORT_WINDOW_SECONDS = 60


def _rh(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def capex_for_config(config_code):
    return BASE_FEE_CENTS_BY_CONFIG[config_code]


# --- funding_fee ----------------------------------------------------------

def funding_fee(contract, dealer):
    """SCAFFOLD funding_fee: capex, holdback, funding amount and funding points."""
    capex_cents = capex_for_config(contract["equipment_config_code"])
    contract["capex_cents"] = capex_cents
    contract["post_warranty_cents"] = 3 * capex_cents
    if contract["source_channel"] == "DEALER" and dealer is not None:
        holdback_cents = _rh(Decimal(capex_cents) * Decimal(str(dealer["holdback_rate"])))
        contract["funding_points"] = DEALER_FUNDING_POINTS_BY_TIER[dealer["quality_tier"]]
    else:
        holdback_cents = 0
        contract["funding_points"] = 0
    contract["holdback_cents"] = holdback_cents
    contract["holdback_remaining_cents"] = holdback_cents
    contract["funding_amount_cents"] = capex_cents - holdback_cents
    return contract


# --- equipment_financing_split -------------------------------------------

def equipment_financing_split(contract, persist_equipment=True):
    """SCAFFOLD equipment_financing_split. The installment is rounded FIRST."""
    capex_cents = contract["capex_cents"]
    monitoring_share_cents = _rh(Decimal(capex_cents) * MONITORING_SHARE_PCT) + DEALER_ONBOARDING_FEE_CENTS
    raw_equipment_cents = _rh(Decimal(monitoring_share_cents) * EQUIPMENT_SHARE_PCT)
    term = contract["contract_term_months"]
    equipment_payment_cents = _rh(Decimal(raw_equipment_cents) / Decimal(term))
    total_of_payments_cents = equipment_payment_cents * term
    monitored_service_cents = monitoring_share_cents - raw_equipment_cents
    if persist_equipment:
        contract["equipment_financed_cents"] = raw_equipment_cents
    return {
        "monitoring_share_cents": monitoring_share_cents,
        "equipment_financed_cents": raw_equipment_cents,
        "monitored_service_cents": monitored_service_cents,
        "equipment_payment_cents": equipment_payment_cents,
        "total_of_payments_cents": total_of_payments_cents,
    }


# --- dealer_chargeback_rate ----------------------------------------------

def exists_valid_inadvertent_alarm(contract):
    """An alarm with verified_at non-null, outcome in {VERIFIED, FALSE_ALARM},
    whose occurred_at lies in [activated_at, cancelled_at] inclusive."""
    activated_at = coerce_dt(contract.get("activated_at"))
    cancelled_at = coerce_dt(contract.get("cancelled_at"))
    account = queries.account_for_contract(contract["id"])
    if account is None:
        return False
    for alarm in db.state.alarm_events.values():
        if alarm.get("monitoring_account_id") != account["id"]:
            continue
        if alarm.get("verified_at") is None:
            continue
        if alarm.get("verification_outcome") not in ("VERIFIED", "FALSE_ALARM"):
            continue
        occurred_at = coerce_dt(alarm.get("occurred_at"))
        if occurred_at is None:
            continue
        if activated_at is not None and occurred_at < activated_at:
            continue
        if cancelled_at is not None and occurred_at > cancelled_at:
            continue
        return True
    return False


def account_is_deployed(contract_id):
    """The provisioning gate needs the account's site_id on file (PRD §3.5)."""
    return queries.current_site_for_contract(contract_id) is not None


def dealer_chargeback_rate(dealer):
    """SCAFFOLD dealer_chargeback_rate — trailing 12 logical months."""
    now = db.now()
    packages = [p for p in db.state.dealer_packages.values() if p.get("dealer_id") == dealer["id"]]
    L = 0
    for p in packages:
        if p.get("package_status") == "FUNDED" and within_trailing_months(p.get("closed_at"), now, TRAILING_WINDOW_MONTHS):
            L += 1
    D = 0
    for c in db.state.contracts.values():
        if c.get("dealer_id") != dealer["id"]:
            continue
        if c.get("contract_status") != "CANCELLED":
            continue
        if c.get("cancelled_from_status") != "ACTIVE":
            continue
        if c.get("activated_at") is None:
            continue
        if not exists_valid_inadvertent_alarm(c):
            continue
        if within_trailing_months(c.get("cancelled_at"), now, TRAILING_WINDOW_MONTHS):
            D += 1
    dealer["chargeback_rate_12mo_sum"] = L
    dealer["funding_package_count_12mo"] = D
    if D > 0:
        percent = Decimal(100) * Decimal(L) / Decimal(D)
        rate_percent = round_percent2(percent)
    else:
        rate_percent = 0.0
    dealer["chargeback_rate_percent"] = rate_percent
    return rate_percent


def dealer_rate_from_counters(dealer):
    """The trailing rate recomputed from the two retained counters."""
    D = dealer.get("funding_package_count_12mo", 0)
    L = dealer.get("chargeback_rate_12mo_sum", 0)
    if D and D > 0:
        return round_percent2(Decimal(100) * Decimal(L) / Decimal(D))
    return dealer.get("chargeback_rate_percent", 0.0)


# --- dealer_standing_derivation ------------------------------------------

def dealer_standing_derivation(dealer):
    """SCAFFOLD dealer_standing_derivation — derived, never assigned directly."""
    if dealer.get("chargeback_balance_due_cents", 0) > DEALER_SUSPEND_BALANCE_THRESHOLD_CENTS:
        standing = "SUSPENDED"
    else:
        rate = dealer_rate_from_counters(dealer)
        if dealer.get("funding_package_count_12mo", 0) > 0 and Decimal(str(rate)) > DEALER_CHARGEBACK_RATE_CAP_PERCENT:
            standing = "WATCH"
        else:
            standing = "ACTIVE"
    dealer["standing"] = standing
    return standing


# --- allowed_holdback_rate_floor_ceiling_binding -------------------------

def allowed_holdback_rate_floor_ceiling_binding(package, dealer):
    """SCAFFOLD allowed_holdback_rate_floor_ceiling_binding."""
    children = queries.children_of_package(package["id"])
    package_capex_cents = sum(c.get("capex_cents", 0) for c in children)
    ceiling = min(
        _rh(Decimal(package_capex_cents) * HOLDBACK_CEILING_PCT),
        _rh(Decimal(str(dealer["holdback_rate"])) * Decimal(package_capex_cents)),
    )
    submitted_holdback_cents = 0
    for c in children:
        submitted_holdback_cents += _rh(Decimal(str(dealer["holdback_rate"])) * Decimal(c.get("capex_cents", 0)))
    if submitted_holdback_cents > ceiling:
        approved_holdback_cents = ceiling
    else:
        approved_holdback_cents = submitted_holdback_cents
    package["allowed_holdback_rate_ceiling_cents"] = ceiling
    package["approved_holdback_cents"] = approved_holdback_cents
    return ceiling, approved_holdback_cents


# --- package_funding_posture --------------------------------------------

def package_funding_posture(package):
    """SCAFFOLD package_funding_posture — decides the whole-package verdict."""
    children = queries.children_of_package(package["id"])
    funded_children = [c for c in children if c.get("contract_status") != "CANCELLED"]
    declined_children = [c for c in children if c.get("contract_status") == "CANCELLED"
                         and c.get("cancelled_from_status") == "PENDING_VALIDATION"]
    if any(c.get("validation_failure_code") == CREDIT_FLOOR_FREEZE_CODE for c in declined_children):
        posture = "DECLINED"
    else:
        posture = "FUNDED" if funded_children else "DECLINED"
    package_holdback_cents = sum(c.get("holdback_cents", 0) for c in funded_children)
    package["package_posture"] = posture
    package["package_holdback_cents"] = package_holdback_cents
    return posture, package_holdback_cents


def refresh_package_rollups(package):
    """The package's aggregate rollups move only through children that reached FUNDED."""
    children = queries.children_of_package(package["id"])
    funded = [c for c in children if c.get("contract_status") != "CANCELLED"]
    declined = [c for c in children if c.get("contract_status") == "CANCELLED"
                and c.get("cancelled_from_status") == "PENDING_VALIDATION"]
    package["funded_count"] = len(funded)
    package["declined_count"] = len(declined)
    package["submitted_contract_count"] = len(children)
    package["package_capex_cents"] = sum(c.get("capex_cents", 0) for c in funded)
    package["package_funding_amount_cents"] = sum(c.get("funding_amount_cents", 0) for c in funded)
    package["package_holdback_cents"] = sum(c.get("holdback_cents", 0) for c in funded)


# --- chargeback_decision -------------------------------------------------

def chargeback_decision(contract, dealer, apply=True):
    """SCAFFOLD chargeback_decision. Returns (amount_cents, decision_code)."""
    if contract.get("chargeback_exempt"):
        return 0, "EXEMPT"
    if contract.get("cancelled_from_status") != "ACTIVE":
        return 0, "NOT_IN_WINDOW"
    cancelled_at = coerce_dt(contract.get("cancelled_at"))
    activated_at = coerce_dt(contract.get("activated_at"))
    if activated_at is None or cancelled_at is None:
        return 0, "NOT_IN_WINDOW"
    if cancelled_at > add_days(activated_at, CHARGEBACK_WINDOW_DAYS):
        return 0, "NOT_IN_WINDOW"
    amount = max(0, _rh(Decimal(contract.get("capex_cents", 0)) * DEALER_CHARGEBACK_PCT))
    if apply and dealer is not None and not contract.get("chargeback_adjudicated"):
        # The decision fires once per contract: on the cancellation itself and again
        # through POST /contracts/{id}/chargeback, which reports the same adjudication.
        holdback_recovery = min(dealer.get("holdback_reserve_cents", 0), amount)
        dealer["holdback_reserve_cents"] -= holdback_recovery
        dealer["chargeback_balance_due_cents"] = dealer.get("chargeback_balance_due_cents", 0) + (amount - holdback_recovery)
        contract["chargeback_adjudicated"] = True
        dealer_standing_derivation(dealer)
    return amount, "CHARGEBACK"


CHARGEBACK_WINDOW_DAYS = 30


def chargeback_preview(contract, dealer):
    """GET /contracts/{id}/chargeback-preview — the same decision, read-only."""
    if contract.get("chargeback_exempt"):
        return {"chargeback_recovery_cents": 0, "holdback_application_cents": 0,
                "amount_due_cents": 0, "decision_code": "EXEMPT"}
    if contract.get("cancelled_from_status") != "ACTIVE":
        return {"chargeback_recovery_cents": 0, "holdback_application_cents": 0,
                "amount_due_cents": 0, "decision_code": "NOT_IN_WINDOW"}
    cancelled_at = coerce_dt(contract.get("cancelled_at"))
    activated_at = coerce_dt(contract.get("activated_at"))
    if activated_at is None or cancelled_at is None or cancelled_at > add_days(activated_at, CHARGEBACK_WINDOW_DAYS):
        return {"chargeback_recovery_cents": 0, "holdback_application_cents": 0,
                "amount_due_cents": 0, "decision_code": "NOT_IN_WINDOW"}
    amount = max(0, _rh(Decimal(contract.get("capex_cents", 0)) * DEALER_CHARGEBACK_PCT))
    reserve = dealer.get("holdback_reserve_cents", 0) if dealer else 0
    applied = min(reserve, amount)
    return {"chargeback_recovery_cents": amount, "holdback_application_cents": applied,
            "amount_due_cents": amount - applied, "decision_code": "CHARGEBACK"}


# --- post_warranty_service_sweep ----------------------------------------

def post_warranty_service_sweep(contract, dealer, billable_base_cents=None):
    """SCAFFOLD post_warranty_service_sweep — the reserve waterfall."""
    if billable_base_cents is None:
        billable_base_cents = contract.get("post_warranty_cents", 0)
    draw = _rh(Decimal(billable_base_cents) * POST_WARRANTY_SERVICE_SWEEP_PCT)
    applied = min(draw, dealer.get("holdback_reserve_cents", 0))
    dealer["holdback_reserve_cents"] = dealer.get("holdback_reserve_cents", 0) - applied
    contract["holdback_remaining_cents"] = dealer["holdback_reserve_cents"]
    contract["dealer_holdback_sweep_cents"] = contract.get("dealer_holdback_sweep_cents", 0) + applied
    remaining_due = draw - applied
    if remaining_due > 0:
        dealer["chargeback_balance_due_cents"] = dealer.get("chargeback_balance_due_cents", 0) + remaining_due
        case_type = "CASH"
    else:
        case_type = "HOLDBACK_ONLY"
    dealer_standing_derivation(dealer)
    resolve_service_required(queries.account_for_contract(contract["id"]))
    return {"draw_cents": draw, "applied_cents": applied, "remaining_due_cents": remaining_due,
            "case_type": case_type}


def resolve_service_required(account):
    """Auto-transition any open SERVICE_REQUIRED reduction action of the account."""
    if account is None:
        return None
    resolved = None
    for action in db.state.alarm_reduction_actions.values():
        if action.get("monitoring_account_id") != account["id"]:
            continue
        if action.get("action_type") == "SERVICE_REQUIRED" and action.get("action_status") == "OPEN":
            action["action_status"] = "RESOLVED"
            action["resolved_at"] = db.now()
            db.bump(action)
            resolved = action
    return resolved


# --- equipment_and_rescission_refund_floor -------------------------------

def equipment_and_rescission_refund_floor(contract, dealer, abuse_flag_open=False):
    """SCAFFOLD equipment_and_rescission_refund_floor."""
    months_since = whole_calendar_months(contract.get("activated_at"), db.now())
    split = equipment_financing_split(contract, persist_equipment=False)
    if contract.get("equipment_financing_disclosed") is True:
        equipment_balance_floor_cents = contract.get("equipment_financed_cents", 0) + contract.get("financed_charge_at_apr_cents", 0)
    else:
        equipment_balance_floor_cents = 0
    deferred_monitoring_amount_cents = _rh(Decimal(contract.get("capex_cents", 0)) * DEFERRED_MONITORING_PCT) + contract.get("financed_charge_at_apr_cents", 0)
    if abuse_flag_open:
        deferred_monitoring_amount_cents = 0
    amortised_capex_recovery_cents = _rh(
        Decimal(contract.get("capex_cents", 0)) * Decimal(min(months_since, AMORTISATION_WINDOW_MONTHS)) / Decimal(contract["contract_term_months"])
    )
    adjudication_amount_cents = max(
        equipment_balance_floor_cents,
        deferred_monitoring_amount_cents + amortised_capex_recovery_cents,
    )
    dealer_recovery = min(contract.get("holdback_remaining_cents", 0), adjudication_amount_cents)
    if dealer is not None:
        dealer["chargeback_balance_due_cents"] = dealer.get("chargeback_balance_due_cents", 0) + (adjudication_amount_cents - dealer_recovery)
        if dealer_recovery > 0:
            dealer["holdback_reserve_cents"] = max(0, dealer.get("holdback_reserve_cents", 0) - dealer_recovery)
        dealer_standing_derivation(dealer)
    company_net_cents = deferred_monitoring_amount_cents + amortised_capex_recovery_cents - dealer_recovery
    return {
        "equipment_balance_floor_cents": equipment_balance_floor_cents,
        "deferred_monitoring_amount_cents": deferred_monitoring_amount_cents,
        "amortised_capex_recovery_cents": amortised_capex_recovery_cents,
        "adjudication_amount_cents": adjudication_amount_cents,
        "dealer_recovery": dealer_recovery,
        "company_net_cents": company_net_cents,
        "split": split,
    }


# --- false_alarm_ratio ---------------------------------------------------

def false_alarm_ratio(account):
    """SCAFFOLD false_alarm_ratio — trailing 30 logical days."""
    now = db.now()
    window_start = now - timedelta(days=TRAILING_WINDOW_DAYS)
    known_alarms = 0
    verified_sigs = 0
    for alarm in db.state.alarm_events.values():
        if alarm.get("monitoring_account_id") != account["id"]:
            continue
        occurred_at = coerce_dt(alarm.get("occurred_at"))
        if occurred_at is None or not (window_start <= occurred_at <= now):
            continue
        known_alarms += 1
        if (alarm.get("verified_at") is not None
                and alarm.get("verification_outcome") in ("VERIFIED", "FALSE_ALARM")
                and alarm.get("counted_for_false_alarm")):
            verified_sigs += 1
    if known_alarms > 0:
        ratio_percent = round_percent2(Decimal(100) * Decimal(verified_sigs) / Decimal(known_alarms))
    else:
        ratio_percent = 0.0
    return {"ratio_percent": ratio_percent, "known_alarm_count": known_alarms,
            "verified_signal_count": verified_sigs}


def reference_chargeback_rate_percent(L, D):
    if D > 0:
        return round_percent2(Decimal(100) * Decimal(L) / Decimal(D))
    return 0.0