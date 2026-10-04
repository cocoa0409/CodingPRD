"""Outcome measurements, attributed savings and downstream claim lines.

Sources: SCAFFOLD 1.2 machine M10, 1.3 `attributed_savings_severity_bucket`;
PRD 3.6.
"""

from db import STORE, create
from errors import ApiError, invalid_reference, invalid_state, not_found
from services import common, intake
from utils import d, fmt, parse_iso, week_of


# ---------------------------------------------------------------------------
# M10 -- OutcomeMeasurement
# ---------------------------------------------------------------------------
def measurement(ident):
    return STORE.need("OutcomeMeasurement", ident, "OutcomeMeasurement")


def _refresh_measurement_count(item):
    item["measurement_count"] = len(common.measurements_of(item["id"]))


def record_measurement(payload, acting_member_id=None):
    item = intake.enrollment(payload.get("enrollment_id"))
    week = payload.get("measurement_week")
    if week is None:
        raise invalid_reference("measurement_week is required.")
    week = int(week)
    pain = payload.get("pain_score")
    function = payload.get("function_score")
    if pain is None or function is None:
        raise invalid_reference("pain_score and function_score are required.")
    pain, function = d(pain), d(function)
    if pain < 0 or pain > 10 or function < 0 or function > 100:
        raise ApiError(
            "ERR_VITALS_OUT_OF_RANGE",
            "pain_score must be within [0, 10] and function_score within [0, 100].",
        )
    for existing in common.measurements_of(item["id"]):
        if existing["measurement_week"] != week:
            continue
        if existing["measurement_status"] in ("RECORDED", "FINALIZED"):
            raise ApiError(
                "ERR_MEASUREMENT_WEEK_DUPLICATE",
                "This enrollment already carries a measurement for that week.",
            )

    row = create("OutcomeMeasurement", {
        "enrollment_id": item["id"],
        "measurement_week": week,
        "pain_score": float(pain),
        "function_score": float(function),
        "measurement_status": "RECORDED",
        "claim_window_rank": 1,
        "window_start_week": None,
        "window_end_week": None,
        "baseline_pain_score": 0.0,
        "baseline_function_score": 0.0,
        "pain_delta_points": 0.0,
        "function_delta_points": 0.0,
        "attributed_savings_cents": 0,
    })
    common.seed_window(item, row)
    common.measurement_deltas(row)
    common.recompute_measurement_savings(item, row)
    common.recompute_enrollment_savings(item)
    _refresh_measurement_count(item)
    STORE.touch("Enrollment", item)
    return row


def supersede_measurement(measurement_id, payload):
    row = measurement(measurement_id)
    replacement_id = payload.get("replacement_measurement_id")
    replacement = measurement(replacement_id)
    if row["measurement_status"] == "FINALIZED":
        raise ApiError(
            "ERR_MEASUREMENT_FINALIZED",
            "A FINALIZED measurement is locked and cannot be superseded.",
        )
    if row["measurement_status"] != "RECORDED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a RECORDED measurement can be superseded."
        )
    if (replacement["enrollment_id"] != row["enrollment_id"]
            or replacement["claim_window_rank"] != row["claim_window_rank"]):
        raise ApiError(
            "ERR_INVALID_REFERENCE",
            "The replacement must belong to the same enrollment and claim window.",
        )
    item = intake.enrollment(row["enrollment_id"])
    row["measurement_status"] = "SUPERSEDED"
    row["attributed_savings_cents"] = 0
    STORE.touch("OutcomeMeasurement", row)
    common.recompute_enrollment_savings(item)
    _refresh_measurement_count(item)
    STORE.touch("Enrollment", item)
    return row


def finalize_measurement(measurement_id):
    row = measurement(measurement_id)
    if row["measurement_status"] == "FINALIZED":
        raise ApiError(
            "ERR_MEASUREMENT_LIMIT_REACHED",
            "This enrollment already carries a FINALIZED measurement.",
        )
    if row["measurement_status"] != "RECORDED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a RECORDED measurement can be finalized."
        )
    if row["window_end_week"] >= week_of(STORE.clock):
        raise ApiError(
            "ERR_MEASUREMENT_WINDOW_OPEN",
            "The claim window is still open.",
        )
    item = intake.enrollment(row["enrollment_id"])
    if item["enrollment_status"] != "ACTIVE":
        raise invalid_state("The enrollment must be ACTIVE to finalize a window.")
    for other in common.measurements_of(item["id"], statuses=("FINALIZED",)):
        if other["id"] != row["id"]:
            raise ApiError(
                "ERR_MEASUREMENT_LIMIT_REACHED",
                "This enrollment already carries a FINALIZED measurement.",
            )
    row["measurement_status"] = "FINALIZED"
    STORE.touch("OutcomeMeasurement", row)
    item["pain_reduction_points"] = row["pain_delta_points"]
    item["function_gain_points"] = row["function_delta_points"]
    common.recompute_enrollment_savings(item)
    STORE.touch("Enrollment", item)
    return row


# ---------------------------------------------------------------------------
# ClaimLine
# ---------------------------------------------------------------------------
def claim_line(ident):
    return STORE.need("ClaimLine", ident, "ClaimLine")


def _window_containing(item, service_week):
    for row in common.measurements_of(item["id"]):
        if row["window_start_week"] <= service_week <= row["window_end_week"]:
            return row
    return None


def record_claim_line(payload):
    item = intake.enrollment(payload.get("enrollment_id"))
    week = payload.get("claim_service_week")
    if week is None:
        raise invalid_reference("claim_service_week is required.")
    week = int(week)
    service_date = parse_iso(payload.get("claim_service_date"))
    if service_date is None:
        raise invalid_reference("claim_service_date must be an ISO 8601 instant.")
    severity = payload.get("claim_severity")
    if severity not in ("LOW", "MODERATE", "HIGH"):
        raise invalid_reference("claim_severity is not recognised.")
    amount = payload.get("amount_cents")
    if amount is None:
        raise invalid_reference("amount_cents is required.")
    amount = int(amount)
    if amount < 0:
        raise invalid_reference("amount_cents must not be negative.")
    source = payload.get("claim_source")
    if source not in ("MEDICAL", "PHARMACY"):
        raise invalid_reference("claim_source must be MEDICAL or PHARMACY.")

    window = _window_containing(item, week)
    if window is not None and window["window_end_week"] < week_of(STORE.clock):
        raise ApiError(
            "ERR_CLAIM_LINE_WINDOW_CLOSED",
            "That attribution window has already lapsed.",
        )

    row = create("ClaimLine", {
        "enrollment_id": item["id"],
        "claim_service_date": fmt(service_date),
        "claim_service_week": week,
        "claim_severity": severity,
        "amount_cents": amount,
        "claim_source": source,
        "claim_superseded": False,
        "claim_withdrawn": False,
        "line_instance_version": 1,
    })
    common.recompute_windows_containing(item, week)
    STORE.touch("Enrollment", item)
    return row


def supersede_claim_line(claim_id, payload):
    row = claim_line(claim_id)
    item = intake.enrollment(row["enrollment_id"])
    amount = payload.get("replacement_amount_cents")
    severity = payload.get("replacement_claim_severity")
    if amount is None or severity is None:
        raise invalid_reference(
            "replacement_amount_cents and replacement_claim_severity are required."
        )
    if severity not in ("LOW", "MODERATE", "HIGH"):
        raise invalid_reference("replacement_claim_severity is not recognised.")
    if int(amount) < 0:
        raise invalid_reference("replacement_amount_cents must not be negative.")

    row["claim_superseded"] = True
    STORE.touch("ClaimLine", row)

    replacement = create("ClaimLine", {
        "enrollment_id": row["enrollment_id"],
        "claim_service_date": row["claim_service_date"],
        "claim_service_week": row["claim_service_week"],
        "claim_severity": severity,
        "amount_cents": int(amount),
        "claim_source": row["claim_source"],
        "claim_superseded": False,
        "claim_withdrawn": False,
        "line_instance_version": row["line_instance_version"] + 1,
    })
    common.recompute_windows_containing(item, row["claim_service_week"])
    STORE.touch("Enrollment", item)
    return replacement


def reinstate_claim_line(claim_id, payload):
    """Withdraw a named instance from its window and report the recomposition."""
    row = claim_line(claim_id)
    item = intake.enrollment(row["enrollment_id"])
    version = payload.get("withdraw_instance_version")
    if version is None:
        raise invalid_reference("withdraw_instance_version is required.")
    version = int(version)

    family = [c for c in common.claim_lines_of(item["id"])
              if c["claim_service_week"] == row["claim_service_week"]
              and c["claim_source"] == row["claim_source"]]
    target = None
    for candidate in family:
        if candidate["line_instance_version"] == version:
            target = candidate
            break
    if target is None:
        raise invalid_reference("No such line instance version in this window.")
    target["claim_withdrawn"] = True
    target["claim_superseded"] = True
    STORE.touch("ClaimLine", target)

    common.recompute_windows_containing(item, row["claim_service_week"])
    STORE.touch("Enrollment", item)

    window = _window_containing(item, row["claim_service_week"])
    if window is not None:
        low, high = window["window_start_week"], window["window_end_week"]
    else:
        low = high = row["claim_service_week"]
    live = [c for c in common.claim_lines_of(item["id"])
            if low <= c["claim_service_week"] <= high
            and not c["claim_superseded"] and not c["claim_withdrawn"]]
    weeks = sorted({c["claim_service_week"] for c in live})
    out = dict(target)
    out["version"] = target["version"]
    out["line_instance_count"] = len(live)
    out["window_claim_week_span"] = [weeks[0], weeks[-1]] if weeks else []
    out["window_claim_count"] = len(live)
    out["distinct_weeks_on_claim_head"] = len(weeks)
    return out