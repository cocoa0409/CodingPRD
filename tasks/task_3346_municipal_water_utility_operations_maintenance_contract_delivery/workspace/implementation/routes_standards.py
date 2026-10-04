"""Performance standards and measurement endpoints — PRD 3.1, 3.4."""
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, body, create, dec, endpoint, field,
                  get, now, now_iso, ordered, own, owner_contract, paginate,
                  parse_dt, set_status, str_field)

METRIC_TYPES = ("TREATMENT_EFFLUENT", "COLLECTION_OVERFLOW", "RESPONSE_TIME",
                "PM_COMPLETION", "WORK_ORDER_CLOSURE", "STAFFING_LEVEL")
AT_LEAST_METRICS = ("RESPONSE_TIME", "PM_COMPLETION", "WORK_ORDER_CLOSURE", "STAFFING_LEVEL")
AT_MOST_METRICS = ("TREATMENT_EFFLUENT", "COLLECTION_OVERFLOW")

# The permit reporting cadence: a monitoring interval may not be shortened below it.
REPORTING_FREQUENCY_DAYS = 30


def standard_or_404(standard_id):
    return get("standards", standard_id, "ERR_STANDARD_NOT_FOUND")


def measurement_or_404(measurement_id):
    return get("measurements", measurement_id, "ERR_MEASUREMENT_NOT_FOUND")


def standard_under(contract_id, standard_id):
    standard = standard_or_404(standard_id)
    if standard["contract_id"] != contract_id:
        raise ApiError("ERR_STANDARD_NOT_FOUND")
    return standard


def measurements_of(standard_id, status=None):
    return [m for m in DB["measurements"].values()
            if m["performance_standard_id"] == standard_id
            and (status is None or m["status"] == status)]


def confirmed_count(standard_id):
    return len(measurements_of(standard_id, "CONFIRMED"))


def refresh_breach_reason(standard):
    reason = ""
    for measurement in measurements_of(standard["id"]):
        if measurement.get("in_breach"):
            reason = standard["metric_type"]
            break
    apply(standard, breach_reason_code=reason)


# --------------------------------------------------------------------------
# standards
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/performance-standards", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_standards(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    items = services.standards_of(contract["id"], status)
    return paginate(ordered(items))


@endpoint("/contracts/<id>/performance-standards", ["POST"], ["OperatorAdmin"], status=201)
def create_standard(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    code = str_field(data, "code")
    title = str_field(data, "title")
    metric_type = str_field(data, "metric_type")
    direction = str_field(data, "threshold_direction")
    if metric_type not in METRIC_TYPES:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown metric_type.")
    if direction not in ("AT_LEAST", "AT_MOST"):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown threshold_direction.")
    for existing in services.standards_of(contract["id"]):
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_STANDARD_CODE")
    if metric_type in AT_LEAST_METRICS and direction != "AT_LEAST":
        raise ApiError("ERR_THRESHOLD_DIRECTION_INVALID")
    if metric_type in AT_MOST_METRICS and direction != "AT_MOST":
        raise ApiError("ERR_THRESHOLD_DIRECTION_INVALID")
    weight = dec(field(data, "criticality_weight"))
    if weight <= 0 or weight > 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "criticality_weight must be greater than 0.0 and at most 1.0.")
    threshold = dec(field(data, "threshold_value"))
    try:
        penalty = int(field(data, "breach_penalty_cents"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "breach_penalty_cents must be an integer.")
    if penalty < 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "breach_penalty_cents must be zero or greater.")
    return create("standards",
                  contract_id=contract["id"],
                  code=code,
                  title=title,
                  metric_type=metric_type,
                  criticality_weight=float(weight),
                  threshold_value=float(threshold),
                  threshold_direction=direction,
                  breach_penalty_cents=penalty,
                  status="DRAFT",
                  breach_reason_code="")


@endpoint("/performance-standards/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_standard(id):
    standard = standard_or_404(id)
    own(standard)
    return standard


@endpoint("/contracts/<id>/performance-standards/<sid>/activate", ["POST"], ["OperatorAdmin"])
def activate_standard(id, sid):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    standard = standard_under(contract["id"], sid)
    if standard["status"] != "DRAFT":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if dec(standard["criticality_weight"]) <= 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "criticality_weight must be greater than 0.0.")
    if standard.get("threshold_value") is None:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "threshold_value is required.")
    set_status(standard, "ACTIVE")
    services.recompute_staffing_floor(contract)
    return standard


@endpoint("/performance-standards/<id>/suspend", ["POST"], ["OperatorAdmin"])
def suspend_standard(id):
    standard = standard_or_404(id)
    own(standard)
    if standard["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if standard["status"] != "BREACHED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if not standard.get("breach_reason_code"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if confirmed_count(standard["id"]) < 2:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(standard, "SUSPENDED")
    for measurement in measurements_of(standard["id"]):
        if measurement["status"] in ("RECORDED", "ASSESSED"):
            set_status(measurement, "WAIVED")
    services.recompute_staffing_floor(DB["contracts"][standard["contract_id"]])
    return standard


@endpoint("/performance-standards/<id>/clear-breach", ["POST"], ["MunicipalityAdmin"])
def clear_breach(id):
    standard = standard_or_404(id)
    own(standard)
    if standard["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if standard["status"] != "BREACHED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    changed = parse_dt(standard.get("status_changed_at"))
    if changed is None or now() < changed + timedelta(days=30):
        raise ApiError("ERR_ALREADY_TERMINAL")
    latest = services.latest_measurement(standard["id"])
    if latest is not None and latest.get("in_breach"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    services.mark_cleared(standard)
    return standard


@endpoint("/performance-standards/<id>/reactivate", ["POST"], ["OperatorAdmin"])
def reactivate_standard(id):
    standard = standard_or_404(id)
    own(standard)
    if standard["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if standard["status"] != "SUSPENDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][standard["contract_id"]]
    if contract["status"] not in ("MOBILIZING", "OPERATING", "UNDER_REVIEW", "RENEWED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(standard, "ACTIVE", breach_reason_code="")
    services.recompute_staffing_floor(contract)
    return standard


@endpoint("/performance-standards/<id>/retire", ["POST"], ["MunicipalityAdmin"])
def retire_standard(id):
    standard = standard_or_404(id)
    own(standard)
    if standard["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if standard["status"] != "ACTIVE":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if confirmed_count(standard["id"]) < 1:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if measurements_of(standard["id"], "RECORDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(standard, "RETIRED")
    services.recompute_staffing_floor(DB["contracts"][standard["contract_id"]])
    return standard


# --------------------------------------------------------------------------
# measurements
# --------------------------------------------------------------------------
@endpoint("/performance-standards/<id>/measurements", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_measurements(id):
    standard = standard_or_404(id)
    own(standard)
    status = arg("status")
    return paginate(ordered(measurements_of(standard["id"], status)))


@endpoint("/performance-standards/<id>/measurements", ["POST"], ["OperatorAdmin"], status=201)
def record_measurement(id):
    standard = standard_or_404(id)
    own(standard)
    data = body()
    start = parse_dt(field(data, "period_start"))
    end = parse_dt(field(data, "period_end"))
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_WINDOW")
    measured = dec(field(data, "measured_value"))
    interval_days = (end - start).total_seconds() / 86400.0
    if interval_days < REPORTING_FREQUENCY_DAYS:
        raise ApiError("ERR_REPORTING_FREQUENCY_VIOLATION")
    for existing in measurements_of(standard["id"]):
        other_start = parse_dt(existing.get("period_start"))
        other_end = parse_dt(existing.get("period_end"))
        if other_start is None or other_end is None:
            continue
        if start < other_end and other_start < end:
            raise ApiError("ERR_MEASUREMENT_PERIOD_OVERLAP")
    breached = calc.in_breach_value(standard, measured)
    contract = DB["contracts"][standard["contract_id"]]
    if breached and standard["status"] != "BREACHED":
        prospective = services.breach_penalty_total(contract["id"]) + int(standard["breach_penalty_cents"])
        if prospective > int(contract["annual_fee_cents"]):
            raise ApiError("ERR_PENALTY_CAP_EXCEEDED")
    return create("measurements",
                  performance_standard_id=standard["id"],
                  period_start=start.isoformat().replace("+00:00", "Z"),
                  period_end=end.isoformat().replace("+00:00", "Z"),
                  measured_value=float(measured),
                  in_breach=breached,
                  weighted_breach_score=0.0,
                  status="RECORDED")


@endpoint("/performance-measurements/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_measurement(id):
    measurement = measurement_or_404(id)
    own(measurement)
    return measurement


@endpoint("/performance-measurements/<id>/assess", ["POST"], ["OperatorAdmin"])
def assess_measurement(id):
    measurement = measurement_or_404(id)
    own(measurement)
    if measurement["status"] != "RECORDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    standard = DB["standards"][measurement["performance_standard_id"]]
    breached = calc.in_breach_value(standard, measurement["measured_value"])
    score = calc.weighted_breach_score(standard, measurement["measured_value"], breached)
    set_status(measurement, "ASSESSED", in_breach=breached, weighted_breach_score=score)
    if breached and score >= 0.60 and standard["status"] == "ACTIVE":
        services.mark_breached(standard, standard["metric_type"])
    return measurement


@endpoint("/performance-measurements/<id>/dispute", ["POST"], ["MunicipalityAdmin"])
def dispute_measurement(id):
    measurement = measurement_or_404(id)
    own(measurement)
    data = body()
    disputed_value = dec(field(data, "disputed_measured_value"))
    if measurement["status"] != "ASSESSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if not measurement.get("in_breach"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    period_end = parse_dt(measurement["period_end"])
    if period_end is None or now() >= period_end + timedelta(days=30):
        raise ApiError("ERR_ALREADY_TERMINAL")
    from core import g
    set_status(measurement, "DISPUTED",
               _disputed_value=float(disputed_value), _disputed_by=g.actor_id)
    return measurement


@endpoint("/performance-measurements/<id>/revise", ["POST"], ["OperatorAdmin"])
def revise_measurement(id):
    measurement = measurement_or_404(id)
    own(measurement)
    data = body()
    new_value = dec(field(data, "measured_value"))
    if measurement["status"] != "DISPUTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if measurement.get("_disputed_value") is not None \
            and dec(measurement["measured_value"]) != dec(measurement["_disputed_value"]):
        raise ApiError("ERR_ALREADY_TERMINAL")
    standard = DB["standards"][measurement["performance_standard_id"]]
    breached = calc.in_breach_value(standard, new_value)
    score = calc.weighted_breach_score(standard, new_value, breached)
    set_status(measurement, "ASSESSED", measured_value=float(new_value),
               in_breach=breached, weighted_breach_score=score)
    return measurement


@endpoint("/performance-measurements/<id>/confirm", ["POST"], ["MunicipalityAdmin"])
def confirm_measurement(id):
    measurement = measurement_or_404(id)
    own(measurement)
    if measurement["status"] != "ASSESSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    standard = DB["standards"][measurement["performance_standard_id"]]
    if standard["status"] == "BREACHED" and confirmed_count(standard["id"]) < 2:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(measurement, "CONFIRMED")
    return measurement


@endpoint("/performance-measurements/<id>/waive", ["POST"], ["MunicipalityAdmin"])
def waive_measurement(id):
    measurement = measurement_or_404(id)
    own(measurement)
    from core import g
    data = body()
    str_field(data, "waiver_basis")
    if measurement["status"] != "ASSESSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if measurement.get("_disputed_by") and measurement["_disputed_by"] == g.actor_id:
        raise ApiError("ERR_CROSS_TENANT_DENIED")
    if not measurement.get("in_breach"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract_id = owner_contract(measurement)
    if not any(p["status"] == "NOTICE_OF_VIOLATION" for p in services.permits_of(contract_id)):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(measurement, "WAIVED", in_breach=False)
    standard = DB["standards"][measurement["performance_standard_id"]]
    refresh_breach_reason(standard)
    return measurement
