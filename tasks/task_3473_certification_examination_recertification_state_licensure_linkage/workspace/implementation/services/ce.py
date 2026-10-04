"""ce_credit_waterfall + audit_sampling_selector (PRD §3.6)."""

from db import (STORE, AUDIT_SEQ_MOD, SINGLE_PROVIDER_FLAG_HOURS,
                PRIOR_FAIL_LOOKBACK_MONTHS)
from errors import raise_err
from util import add_months, ceil_half

COMPONENTS = ("NATIONAL", "LOCAL", "INDIVIDUAL")


def eligible_entries(app, statuses):
    """Entries of the application in the given statuses whose course_date lies
    inside [cycle_window_start, cert_expires_on_at_creation] (day precision)."""
    start = app["cycle_window_start"].date()
    end = app["cert_expires_on_at_creation"].date()
    return [
        e for e in STORE.ce_entries.values()
        if e["recert_application_id"] == app["id"]
        and e["status"] in statuses
        and start <= e["course_date"] <= end
    ]


def waterfall(app, level, entries):
    """Compute credited hours. Returns dict with national/local/individual/
    total credited hours (HOURLY: components ignored, only total is meaningful)."""
    if app["model"] == "HOURLY":
        dist = sum(float(e["hours"]) for e in entries if e["delivery_method"] == "DISTRIBUTED")
        in_person = sum(float(e["hours"]) for e in entries if e["delivery_method"] == "IN_PERSON")
        cap = ceil_half(level["hourly_model_total_hours"])
        total = min(dist, cap) + in_person
        return {"national_credited_hours": 0, "local_credited_hours": 0,
                "individual_credited_hours": 0, "total_credited_hours": total}

    mins = {"NATIONAL": float(level["ce_national_min_hours"]),
            "LOCAL": float(level["ce_local_min_hours"]),
            "INDIVIDUAL": float(level["ce_individual_min_hours"])}
    claimed = {}
    for comp in COMPONENTS:
        dist = sum(float(e["hours"]) for e in entries
                   if e["component"] == comp and e["delivery_method"] == "DISTRIBUTED")
        in_person = sum(float(e["hours"]) for e in entries
                        if e["component"] == comp and e["delivery_method"] == "IN_PERSON")
        credited_dist = min(dist, ceil_half(mins[comp]))
        claimed[comp] = credited_dist + in_person

    spill_n = max(0.0, claimed["NATIONAL"] - mins["NATIONAL"])
    spill_l = max(0.0, claimed["LOCAL"] - mins["LOCAL"])
    national = min(claimed["NATIONAL"], mins["NATIONAL"])
    local = min(claimed["LOCAL"], mins["LOCAL"])
    individual = min(claimed["INDIVIDUAL"] + spill_n + spill_l, mins["INDIVIDUAL"])
    return {
        "national_credited_hours": national,
        "local_credited_hours": local,
        "individual_credited_hours": individual,
        "total_credited_hours": national + local + individual,
    }


def check_sufficiency(app, level, credited):
    """Raise the first sufficiency failure in pinned order (NCCP: NATIONAL,
    LOCAL, INDIVIDUAL, then total; HOURLY: total only)."""
    if app["model"] == "HOURLY":
        if credited["total_credited_hours"] < float(level["hourly_model_total_hours"]):
            raise_err("ERR_CE_TOTAL_SHORTFALL",
                      "Credited total %s is below the required %s"
                      % (credited["total_credited_hours"], level["hourly_model_total_hours"]))
        return
    if credited["national_credited_hours"] < float(level["ce_national_min_hours"]):
        raise_err("ERR_CE_COMPONENT_SHORTFALL", "NATIONAL component minimum unmet")
    if credited["local_credited_hours"] < float(level["ce_local_min_hours"]):
        raise_err("ERR_CE_COMPONENT_SHORTFALL", "LOCAL component minimum unmet")
    if credited["individual_credited_hours"] < float(level["ce_individual_min_hours"]):
        raise_err("ERR_CE_COMPONENT_SHORTFALL", "INDIVIDUAL component minimum unmet")
    if credited["total_credited_hours"] < float(level["ce_total_hours"]):
        raise_err("ERR_CE_TOTAL_SHORTFALL",
                  "Credited total %s is below the required %s"
                  % (credited["total_credited_hours"], level["ce_total_hours"]))


def compute_recert_seq(app):
    """1 + count of OTHER applications for this certification that ever reached
    SUBMITTED (a persistent flag set at each submit transition)."""
    cert_id = app["certification_id"]
    prior = sum(1 for a in STORE.recerts.values()
                if a["certification_id"] == cert_id and a["id"] != app["id"]
                and a.get("_ever_submitted"))
    return 1 + prior


def audit_select(app, candidate_id, entries, recert_seq, now):
    """Deterministic audit selector; returns (audit_selected, audit_reasons)."""
    reasons = []
    if recert_seq % AUDIT_SEQ_MOD == 0:
        reasons.append("SEQ_MOD")
    lookback_start = add_months(now, -PRIOR_FAIL_LOOKBACK_MONTHS)
    for other in STORE.recerts.values():
        if (other["id"] != app["id"]
                and other["candidate_id"] == candidate_id
                and other["status"] == "AUDIT_FAILED"
                and other.get("decided_at") is not None
                and lookback_start <= other["decided_at"] <= now):
            reasons.append("PRIOR_AUDIT_FAILURE")
            break
    per_provider = {}
    for e in entries:
        per_provider[e["provider_name"]] = per_provider.get(e["provider_name"], 0.0) + float(e["hours"])
    if per_provider and max(per_provider.values()) >= SINGLE_PROVIDER_FLAG_HOURS:
        reasons.append("SINGLE_PROVIDER_CONCENTRATION")
    return (len(reasons) > 0, reasons)
