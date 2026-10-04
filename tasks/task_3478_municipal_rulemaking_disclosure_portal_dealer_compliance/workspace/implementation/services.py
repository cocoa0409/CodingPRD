"""Shared business operations and calculation constants (SCAFFOLD section 1.3)."""
from datetime import timedelta

import store

# --- calculations.late_report_tally_and_posture ---
LATE_TRADE_WINDOW_DAYS = 30
LATE_WATCH_THRESHOLD = 5

# --- calculations.ce_cycle_satisfaction ---
CE_CYCLE_DAYS = 365
CE_GRACE_DAYS = 60
CE_TOTAL_REQUIRED = 12
CE_ETHICS_REQUIRED = 2

# --- calculations.exam_pass_result ---
PASS_SCORES = {"MSRB_50": 70, "MSRB_52": 72, "MSRB_53": 75, "MSRB_54": 80}
REQUIRED_SERIES = {
    "MUNICIPAL_ADVISOR_REP": ["MSRB_50"],
    "MUNICIPAL_DEALER_REP": ["MSRB_52"],
    "MUNICIPAL_PRINCIPAL": ["MSRB_53", "MSRB_54"],
}
RETAKE_WINDOW_DAYS = 30

# --- calculations.trade_timeliness / disseminated_par_publication ---
REPORT_LIMIT_SECONDS = 900
LARGE_TRADE_PAR_CAP = 5000000

# --- calculations.event_notice_timeliness ---
EVENT_NOTICE_LIMIT_DAYS = 10

# --- calculations.rule_effectiveness_delay ---
STANDARD_DELAY_DAYS = 30
EXPEDITED_DELAY_DAYS = 10


def bump(entity):
    """Every mutation of a versioned resource increments version by exactly one."""
    entity["version"] = entity.get("version", 0) + 1
    entity["updated_at"] = store.now()


def recompute_may_transact(prof):
    prof["may_transact"] = (
        prof["qualification_status"] == "QUALIFIED" and prof["standing"] == "ACTIVE"
    )


def qualify(prof):
    """Enter QUALIFIED with fresh CE anchors and zeroed credit buckets."""
    now = store.now()
    prof["qualification_status"] = "QUALIFIED"
    prof["qualified_at"] = now
    prof["ce_cycle_end"] = now + timedelta(days=CE_CYCLE_DAYS)
    prof["ce_grace_end"] = now + timedelta(days=CE_CYCLE_DAYS + CE_GRACE_DAYS)
    prof["ce_credits_total"] = 0
    prof["ce_ethics_credits"] = 0
    prof["_lapsed_at"] = None
    recompute_may_transact(prof)
    bump(prof)


def recompute_posture(org):
    """Recompute one organization's late_report_count and compliance_posture.

    Window is half-open (now - 30 days, now]: a trade exactly 30 days old is
    excluded. WATCH at count >= 5 (boundary inclusive). On a CLEAR -> WATCH
    transition, every PENDING DataSubscription of this licensee is REJECTED
    (terminal; never resurrected). Returns the number of state changes applied
    (posture flips + subscription rejections). Organization derived-counter
    recomputation is not a versioned mutation of the organization (PRD 2.8).
    """
    now = store.now()
    window_start = now - timedelta(days=LATE_TRADE_WINDOW_DAYS)
    count = 0
    for trade in store.trade_reports.values():
        if (
            trade["dealer_org_id"] == org["id"]
            and trade["late_flag"]
            and trade["status"] == "DISSEMINATED"
            and window_start < trade["reported_at"] <= now
        ):
            count += 1
    org["late_report_count"] = count
    new_posture = "WATCH" if count >= LATE_WATCH_THRESHOLD else "CLEAR"
    effects = 0
    old_posture = org["compliance_posture"]
    if new_posture != old_posture:
        org["compliance_posture"] = new_posture
        effects += 1
        if old_posture == "CLEAR" and new_posture == "WATCH":
            for sub in store.data_subscriptions.values():
                if sub["licensee_org_id"] == org["id"] and sub["status"] == "PENDING":
                    sub["status"] = "REJECTED"
                    bump(sub)
                    effects += 1
    return effects
