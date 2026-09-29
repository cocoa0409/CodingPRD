"""Abstraction evaluation and certification-report figures (PRD 3.9)."""
import db
from constants import (
    DTI_TARGET_MIN,
    DTN_TARGET_MIN,
    REPORTED_MEASURE_CODES,
    TELESTROKE_RESPONSE_TARGET_SEC,
)
from services import calculations as calc


def checklist_for_case(case_id):
    for checklist in db.DB["checklists"].values():
        if checklist["case_id"] == case_id:
            return checklist
    return None


def consults_for_case(case_id):
    return [c for c in db.all_of("consults") if c["case_id"] == case_id]


def numerator_flag(measure_code, case):
    if measure_code == "STK_DTI_45":
        value = case["door_to_imaging_minutes"]
        return value is not None and value <= DTI_TARGET_MIN
    if measure_code == "STK_DTN_60":
        value = case["door_to_needle_minutes"]
        return value is not None and value <= DTN_TARGET_MIN
    if measure_code == "STK_4_THROMBOLYTIC_THERAPY":
        return case["needle_at"] is not None
    if measure_code == "STK_TELESTROKE_RESPONSE":
        for consult in consults_for_case(case["id"]):
            latency = consult["response_latency_seconds"]
            if (consult["status"] == "COMPLETED"
                    and latency is not None
                    and latency <= TELESTROKE_RESPONSE_TARGET_SEC
                    and consult["valid_video_session_count"] >= 1):
                return True
        return False
    return False


def exclusion_reason(case):
    """Ordered clauses; the first match wins (PRD 3.9)."""
    if case["status"] == "ABORTED":
        return "ABORTED_CASE"
    checklist = checklist_for_case(case["id"])
    absolute_count = checklist["absolute_contraindication_count"] if checklist else 0
    if absolute_count > 0:
        return "DOCUMENTED_ABSOLUTE_CONTRAINDICATION"
    if case["thrombolytic_window_class"] == "OUT_OF_WINDOW":
        return "OUT_OF_WINDOW"
    if case["disposition"] == "TRANSFER_ONLY":
        return "TRANSFER_ONLY"
    return "NONE"


def evaluate_abstraction(abstraction, case, variant):
    abstraction["numerator_flag"] = numerator_flag(abstraction["measure_code"], case)
    abstraction["exclusion_reason"] = exclusion_reason(case)
    if variant == "PROVISIONAL":
        abstraction["denominator_included"] = True
    else:
        abstraction["denominator_included"] = abstraction["exclusion_reason"] == "NONE"


# --- report period helpers --------------------------------------------------

def in_period(report, instant_raw):
    instant = db.parse_iso(instant_raw)
    if instant is None:
        return False
    start = db.parse_iso(report["period_start"])
    end = db.parse_iso(report["period_end"])
    return start <= instant < end


def closed_cases_in_period(report):
    return [
        case for case in db.all_of("cases")
        if case["center_id"] == report["center_id"]
        and case["status"] == "CLOSED"
        and in_period(report, case["door_at"])
    ]


def attached_abstractions(report):
    return [a for a in db.all_of("abstractions") if a["report_id"] == report["id"]]


def draft_report_for_case(case):
    matches = [
        report for report in db.all_of("reports")
        if report["center_id"] == case["center_id"]
        and report["status"] == "DRAFT"
        and in_period(report, case["door_at"])
    ]
    if len(matches) == 1:
        return matches[0]
    return None


# --- report figures ---------------------------------------------------------

def compute_rate(report, measure_code, variant):
    allowed = ("DRAFT", "FINALIZED") if variant == "PROVISIONAL" else ("FINALIZED",)
    pool = [a for a in attached_abstractions(report)
            if a["measure_code"] == measure_code and a["status"] in allowed]
    denominator = [a for a in pool if a["denominator_included"]]
    numerator = [a for a in denominator if a["numerator_flag"]]
    return calc.compliance_rate(len(numerator), len(denominator))


RATE_FIELDS = {
    "STK_DTN_60": "dtn_60_compliance_pct",
    "STK_DTI_45": "dti_45_compliance_pct",
    "STK_TELESTROKE_RESPONSE": "telestroke_response_compliance_pct",
}


def recompute_rates(report, variant):
    for measure_code in REPORTED_MEASURE_CODES:
        db.setf(report, RATE_FIELDS[measure_code],
                compute_rate(report, measure_code, variant))


def recompute_mean_dtn_excess(report):
    values = []
    for abstraction in attached_abstractions(report):
        if abstraction["measure_code"] != "STK_DTN_60":
            continue
        if abstraction["status"] != "FINALIZED":
            continue
        case = db.get("cases", abstraction["case_id"])
        if case is None or case["door_to_needle_minutes"] is None:
            continue
        values.append(calc.per_case_dtn_excess_percent(case["door_to_needle_minutes"]))
    db.setf(report, "mean_dtn_excess_pct", calc.mean_dtn_excess(values))


def recompute_counts(report):
    included = sum(1 for a in attached_abstractions(report) if a["status"] == "FINALIZED")
    db.setf(report, "included_abstraction_count", included)
    db.setf(report, "closed_case_count_in_period", len(closed_cases_in_period(report)))


def recompute_substantiated_counts(report):
    case_ids = set(case["id"] for case in closed_cases_in_period(report))
    major = 0
    sentinel = 0
    for deviation in db.DB["deviations"].values():
        if deviation["status"] != "SUBSTANTIATED":
            continue
        if deviation["case_id"] not in case_ids:
            continue
        if deviation["severity"] == "MAJOR":
            major += 1
        elif deviation["severity"] == "SENTINEL":
            sentinel += 1
    db.setf(report, "substantiated_major_count", major)
    db.setf(report, "substantiated_sentinel_count", sentinel)


def recompute_report(report, counts=True, rates=True, mean=True, substantiated=False,
                     variant=None):
    if counts:
        recompute_counts(report)
    if rates:
        recompute_rates(report, variant or report["rate_variant"])
    if mean:
        recompute_mean_dtn_excess(report)
    if substantiated:
        recompute_substantiated_counts(report)


def substantiation_targets(case):
    """DRAFT/RETURNED reports at the case's facility covering its door_at."""
    return [
        report for report in db.all_of("reports")
        if report["center_id"] == case["center_id"]
        and report["status"] in ("DRAFT", "RETURNED")
        and in_period(report, case["door_at"])
    ]
