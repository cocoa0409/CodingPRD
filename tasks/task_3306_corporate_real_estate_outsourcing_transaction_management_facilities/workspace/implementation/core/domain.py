"""Cross-cutting domain helpers: recompute pipelines, gates and guards."""
from datetime import timedelta

from core import calc
from core.db import DB, dec, rhu_int, touch
from core.errors import ApiError

# Endpoints guarded by the lifecycle/per-account structural matrix.
MATRIX_GATED = {
    "create_lease", "create_transaction_request", "create_scorecard",
    "create_broker_engagement", "create_facility_site", "create_facilities_vendor",
    "create_service_level_kpi", "create_consolidation_project",
    "create_discipline_audit", "create_audit_review_for_audit",
}
TERMINAL_BLOCKED = {
    "create_lease", "create_transaction_request", "create_data_license",
    "close_account", "close_account_converted",
}
OFFBOARDING_BLOCKED = {
    "create_lease", "create_transaction_request", "begin_transition",
}
# Endpoints that must not be blocked while the account is OFFBOARDING (PRD 3.8).
OFFBOARDING_EXEMPT = {
    "create_transition_task", "start_transition_task", "complete_transition_task",
    "fail_transition_task", "expire_transition_task", "create_audit_review_for_audit",
}


def account_of(resource):
    if resource is None:
        return None
    if resource.get("account_id"):
        return DB.get("accounts", resource["account_id"])
    return None


def lifecycle_gate(account, endpoint_name):
    if account is None:
        return
    state = account.get("lifecycle_state")
    if endpoint_name in OFFBOARDING_BLOCKED and state == "OFFBOARDING":
        raise ApiError("ERR_OFFBOARDING_PENDING",
                       "The account is offboarding; this operation is blocked.")
    if endpoint_name in TERMINAL_BLOCKED and state in ("CLOSED_CONVERTED", "CLOSED_TERMINATED"):
        raise ApiError("ERR_ACCOUNT_CLOSED", "The account is closed; the mutation is blocked.")
    if endpoint_name in MATRIX_GATED and state != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                       "Child creation and mutation require an ACTIVE account.")


def read_gate(account, endpoint_name):
    """Existence-only guard for on-demand recompute endpoints."""
    if account is None:
        return
    state = account.get("lifecycle_state")
    if endpoint_name in TERMINAL_BLOCKED and state in ("CLOSED_CONVERTED", "CLOSED_TERMINATED"):
        raise ApiError("ERR_ACCOUNT_CLOSED", "The account is closed; the mutation is blocked.")


def active_failed_audits(account_id):
    return [a for a in DB.children("discipline_audits", account_id)
            if a.get("audit_state") == "FAILED" and a.get("remediation_required") is True]


def unresolved_failed_audit(account_id):
    return len(active_failed_audits(account_id)) >= 1


def cooling_off_active(account_id):
    for a in active_failed_audits(account_id):
        until = a.get("cooling_off_until")
        if until is not None and until > DB.clock:
            return True
    return False


def consent_gate(account_id):
    if unresolved_failed_audit(account_id):
        raise ApiError("ERR_CONSENT_REQUIRED",
                       "An unresolved failed audit requires remediation.")


def cooling_off_gate(account_id):
    if cooling_off_active(account_id):
        raise ApiError("ERR_COOLING_OFF_ACTIVE",
                       "A failed audit's cooling-off window is still open.")


# ---------------------------------------------------------------------------
# Recompute pipelines
# ---------------------------------------------------------------------------

def recompute_governance(account):
    posture, open_count = calc.governance_posture_rollup(account["id"])
    account["governance_posture"] = posture
    account["open_escalation_count"] = open_count


def recompute_fee(account):
    result = calc.commission_credit_nets_fee(account)
    account["annual_net_fee_cents"] = result["annual_net_fee_cents"]
    account["fee_ledger_credit_cents"] = calc.fee_ledger_credit_cents(account["id"])
    account["broker_pool_allocated_cents"] = calc.broker_pool_allocated_cents(account["id"])
    account["portfolio_leased_sqft"] = calc.portfolio_leased_sqft(account["id"])
    return result


def recompute_posture(account):
    recompute_governance(account)
    touch(account)


def settle_kpi(kpi):
    """Apply kpi_net_adjustment then escalation_threshold_check to one row."""
    adj = calc.kpi_net_adjustment(kpi)
    kpi["gainshare_cents"] = rhu_int(adj["gainshare_cents"])
    kpi["penalty_cents"] = rhu_int(adj["penalty_cents"])
    kpi["net_adjustment_cents"] = rhu_int(adj["net_adjustment_cents"])
    kpi["escalation_status"] = calc.escalation_threshold_check(kpi)
    return kpi


def recompute_vendor_track(vendor):
    vendor["kpi_track"] = calc.level_for_vendor(vendor)


def refresh_account_derived(account):
    recompute_fee(account)
    recompute_governance(account)


# ---------------------------------------------------------------------------
# Date / temporal guards
# ---------------------------------------------------------------------------

def premises_cooldown_end(lease):
    return lease.get("lease_end_date") + timedelta(days=30)


def lease_premises_conflict(account_id, property_address, start, end, exclude_id=None):
    for other in DB.children("leases", account_id):
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other.get("property_address") != property_address:
            continue
        o_start = other.get("lease_start_date")
        o_end = other.get("lease_end_date")
        if o_start is None or o_end is None:
            continue
        if start < o_end and o_start < end:
            return True
        if start >= o_end and start < o_end + timedelta(days=30):
            return True
    return False


def consolidation_interval_conflict(account_id, start, end, exclude_id=None):
    if start is None or end is None:
        return False
    for site in DB.children("facility_sites", account_id):
        if exclude_id is not None and site["id"] == exclude_id:
            continue
        s_start = site.get("consolidation_window_start")
        s_end = site.get("consolidation_window_end")
        if s_start is None or s_end is None:
            continue
        if start < s_end and s_start < end:
            return True
    from core.db import utcnow
    return False


def site_consolidation_credit(site):
    """Credit committed when a site enters consolidation (positive figure)."""
    rate = DB.get("facilities_vendors", site.get("vendor_id")) or {}
    service_rate = rate.get("service_rate_cents_per_sqft")
    if service_rate is None:
        return dec(0)
    return dec(site.get("sqft_reduction") or 0) * dec(service_rate)