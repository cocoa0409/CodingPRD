"""SurveyComponent derivations: variance, coverage, per-FTE expense, edit checks."""
from db import (ALL_METRIC_KEYS, FULL_COVERAGE_PCT, METRIC_DOMAINS,
                PY_VARIANCE_FATAL_PCT, PY_VARIANCE_WARNING_PCT, stamp_new, store)
from svc_common import checks_of, metrics_of
from util import D, num1, rhu, whole


def variance_pct(metric):
    """calculations.prior_year_variance_pct — 1 decimal place, round half up."""
    prior = metric.get("prior_year_value")
    if prior is None:
        return None
    if D(prior) == 0:
        return None
    delta = abs(D(metric["reported_value"]) - D(prior))
    return num1(delta / D(prior) * D(100))


def mapping_coverage_pct(component, cycle):
    """calculations.mapping_coverage_pct — empty required set is fully covered."""
    required = [d for d in store.definitions.values()
                if d["survey_component"] == component["component_code"]
                and d["required"] is True
                and d["effective_cycle_code"] == cycle["cycle_code"]]
    if not required:
        return float(FULL_COVERAGE_PCT)
    covered = 0
    for definition in required:
        for mapping in store.mappings.values():
            if (mapping["definition_id"] == definition["id"]
                    and mapping["cycle_id"] == component["cycle_id"]
                    and mapping["status"] == "VALIDATED"):
                covered += 1
                break
    return num1(D(covered) / D(len(required)) * D(100))


def core_expense_per_fte_cents(component):
    """calculations.core_expense_per_fte_cents — round per category, THEN sum."""
    if component["component_code"] != "FINANCE":
        return None
    values = {}
    for metric in metrics_of(component["id"]):
        values[metric["metric_key"]] = metric["reported_value"]
    needed = ("INSTRUCTION_EXPENSES_CENTS", "ACADEMIC_SUPPORT_EXPENSES_CENTS",
              "STUDENT_SERVICES_EXPENSES_CENTS", "FTE_ENROLLMENT")
    for key in needed:
        if key not in values or values[key] is None:
            return None
    fte = D(values["FTE_ENROLLMENT"])
    if fte == 0:
        return None
    total = 0
    for key in needed[:3]:
        total += int(rhu(D(values[key]) / fte, 0))
    return total


def metric_domain_ok(component_code, metric_key):
    return metric_key in METRIC_DOMAINS.get(component_code, ())


def known_metric_key(metric_key):
    return metric_key in ALL_METRIC_KEYS


def derive_edit_status(component, force_cleared_if_empty=False):
    """calculations.edit_status_derivation. The caller owns the version bump."""
    checks = checks_of(component["id"])
    live = [c for c in checks if c["status"] != "VOIDED"]
    if not checks or not live:
        status = "CLEARED" if force_cleared_if_empty else "NOT_RUN"
    elif any(c["status"] in ("OPEN", "REJECTED") for c in live):
        status = "OPEN_EDITS"
    elif any(c["status"] == "EXPLAINED" for c in live):
        status = "EXPLAINED"
    else:
        status = "CLEARED"
    component["edit_status"] = status
    component["fatal_open_count"] = len(
        [c for c in checks
         if c["severity"] == "FATAL" and c["status"] in ("OPEN", "EXPLAINED", "REJECTED")])
    return status


def _new_check(component, code, severity, metric_key, observed, prior, variance, seq):
    row = {
        "component_id": component["id"],
        "check_code": code,
        "sequence_no": seq,
        "severity": severity,
        "metric_key": metric_key,
        "observed_value": observed,
        "prior_year_value": prior,
        "variance_pct": variance,
        "status": "OPEN",
        "explanation_text": None,
        "prior_year_comparison_note": None,
        "explained_by_user_id": None,
        "adjudicated_by_user_id": None,
        "adjudication_note": None,
        "explanation_round": 0,
    }
    stamp_new(row)
    store.edit_checks[row["id"]] = row
    return row


def generate_checks(component, coverage_pct):
    """calculations.edit_check_generation — at most one check per metric, metric_key ASC."""
    metrics = sorted(metrics_of(component["id"]), key=lambda m: m["metric_key"])
    seq = 0
    created = []
    warn = D(PY_VARIANCE_WARNING_PCT)
    fatal = D(PY_VARIANCE_FATAL_PCT)
    for metric in metrics:
        prior = metric.get("prior_year_value")
        reported = metric["reported_value"]
        var = metric.get("variance_pct")
        key = metric["metric_key"]
        if prior is not None and D(prior) == 0 and D(reported) > 0:
            seq += 1
            created.append(_new_check(component, "PY_ZERO_BASE_" + key, "FATAL", key,
                                      reported, prior, None, seq))
        elif var is not None and D(var) >= fatal:
            seq += 1
            created.append(_new_check(component, "PY_VAR_" + key, "FATAL", key,
                                      reported, prior, var, seq))
        elif var is not None and D(var) >= warn:
            seq += 1
            created.append(_new_check(component, "PY_VAR_" + key, "WARNING", key,
                                      reported, prior, var, seq))
        elif prior is None and D(reported) == 0:
            seq += 1
            created.append(_new_check(component, "ZERO_NO_BASE_" + key, "WARNING", key,
                                      reported, prior, None, seq))
    if coverage_pct is not None and D(coverage_pct) < D(FULL_COVERAGE_PCT):
        seq += 1
        created.append(_new_check(component, "UNMAPPED_ELEMENTS", "FATAL", "ALL",
                                  None, None, None, seq))
    return created


def serialize_component(row):
    from db import public
    out = public(row)
    out["mapping_coverage_pct"] = None if row.get("mapping_coverage_pct") is None \
        else num1(row["mapping_coverage_pct"])
    out["core_expense_per_fte_cents"] = None if row.get("core_expense_per_fte_cents") is None \
        else whole(row["core_expense_per_fte_cents"])
    return out
