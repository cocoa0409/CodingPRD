"""Asset, condition-assessment and asset-scoped listing endpoints — PRD 3.2."""
from datetime import datetime, timedelta, timezone

import calc
import services
from core import (ApiError, DB, apply, arg, body, create, dec, endpoint, field,
                  g, get, now, now_iso, ordered, own, paginate, parse_dt,
                  set_status, str_field)

ASSET_CLASSES = ("MAIN", "PUMP", "VALVE", "TREATMENT_UNIT", "BLOWER", "FILTER",
                 "LIFT_STATION", "RESERVOIR")


def asset_or_404(asset_id):
    return get("assets", asset_id, "ERR_ASSET_NOT_FOUND")


def assessment_or_404(assessment_id):
    return get("assessments", assessment_id, "ERR_ASSESSMENT_NOT_FOUND")


def assessments_of(asset_id, status=None):
    return [a for a in DB["assessments"].values()
            if a["asset_id"] == asset_id and (status is None or a["status"] == status)]


def _life_end_instant(asset):
    end_year = int(asset["install_year"]) + int(asset["useful_life_years"])
    return datetime(end_year, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# assets
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/assets", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_contract_assets(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    asset_class = arg("asset_class")
    items = [a for a in services.assets_of(contract["id"], status)
             if asset_class is None or a["asset_class"] == asset_class]
    return paginate(ordered(items))


@endpoint("/contracts/<id>/assets", ["POST"], ["MunicipalityAdmin"], status=201)
def register_asset(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    tag = str_field(data, "asset_tag")
    asset_class = str_field(data, "asset_class")
    if asset_class not in ASSET_CLASSES:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown asset_class.")
    for existing in services.assets_of(contract["id"]):
        if existing["asset_tag"] == tag:
            raise ApiError("ERR_DUPLICATE_ASSET_TAG")
    try:
        install_year = int(field(data, "install_year"))
        useful_life = int(field(data, "useful_life_years"))
        rank = int(field(data, "criticality_rank"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "install_year, useful_life_years and criticality_rank must be integers.")
    if install_year < 1900 or install_year > 2100:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "install_year must be between 1900 and 2100.")
    if useful_life < 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "useful_life_years must be at least 1.")
    if rank < 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "criticality_rank must be at least 1.")
    return create("assets",
                  contract_id=contract["id"],
                  asset_tag=tag,
                  asset_class=asset_class,
                  install_year=install_year,
                  useful_life_years=useful_life,
                  criticality_rank=rank,
                  condition_score=100.0,
                  condition_band="EXCELLENT",
                  status="REGISTERED",
                  replacement_flagged_at=None)


@endpoint("/assets", ["GET"], ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_assets():
    asset_class = arg("asset_class")
    status = arg("status")
    band = arg("condition_band")
    items = [a for a in DB["assets"].values()
             if (asset_class is None or a["asset_class"] == asset_class)
             and (status is None or a["status"] == status)
             and (band is None or a["condition_band"] == band)]
    return paginate(ordered(items))


@endpoint("/assets/<id>", ["GET"], ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_asset(id):
    asset = asset_or_404(id)
    own(asset)
    return asset


@endpoint("/assets/<id>/baseline-assessments", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_assessments(id):
    asset = asset_or_404(id)
    own(asset)
    status = arg("status")
    return paginate(ordered(assessments_of(asset["id"], status)))


@endpoint("/assets/<id>/baseline-assessments", ["POST"],
          ["OperatorAdmin", "MunicipalityAdmin"], status=201)
def record_assessment(id):
    asset = asset_or_404(id)
    own(asset)
    data = body()
    assessed_at = parse_dt(field(data, "assessed_at"))
    score = dec(field(data, "assessed_score"))
    if score < 0 or score > 100:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "assessed_score must be between 0.0 and 100.0.")
    party = str_field(data, "assessor_party")
    if party not in ("OPERATOR", "MUNICIPALITY", "JOINT"):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown assessor_party.")
    is_baseline = bool(data.get("is_baseline"))
    assessment = create("assessments",
                        asset_id=asset["id"],
                        assessed_at=assessed_at.isoformat().replace("+00:00", "Z"),
                        assessed_score=float(score),
                        is_baseline=is_baseline,
                        assessor_party=party,
                        status="SUBMITTED",
                        baseline_binding=False,
                        _submitted_by=g.actor_id)
    services.set_condition(asset, score)
    if asset["status"] == "REGISTERED":
        operator_baseline = any(a["assessor_party"] == "OPERATOR" and a.get("is_baseline")
                                for a in assessments_of(asset["id"]) if a is not assessment)
        if party == "MUNICIPALITY" and operator_baseline:
            set_status(asset, "BASELINE_DISPUTED")
        elif party in ("OPERATOR", "JOINT"):
            set_status(asset, "BASELINE_ASSESSED")
    return assessment


@endpoint("/assets/<id>/flag-replacement", ["POST"], ["OperatorAdmin"])
def flag_replacement(id):
    asset = asset_or_404(id)
    own(asset)
    if asset["status"] != "IN_SERVICE":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    contract = DB["contracts"][asset["contract_id"]]
    if not contract["baseline_frozen"]:
        raise ApiError("ERR_ASSET_INVALID_STATE")
    if not calc.condition_below(asset.get("condition_score"), 40.0):
        raise ApiError("ERR_ASSET_INVALID_STATE")
    if now() < _life_end_instant(asset):
        raise ApiError("ERR_ASSET_INVALID_STATE")
    services.flag_asset(asset)
    return asset


@endpoint("/assets/<id>/clear-replacement-flag", ["POST"], ["MunicipalityAdmin"])
def clear_replacement_flag(id):
    asset = asset_or_404(id)
    own(asset)
    if asset["status"] != "REPLACEMENT_FLAGGED":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    if not calc.condition_at_least(asset.get("condition_score"), 40.0):
        raise ApiError("ERR_ASSET_INVALID_STATE")
    work_order = services.draft_capital_work_order(asset)
    if work_order is not None and work_order["status"] == "DRAFT":
        set_status(work_order, "CANCELLED")
    set_status(asset, "IN_SERVICE", replacement_flagged_at=None)
    return asset


@endpoint("/assets/<id>/complete-replacement", ["POST"], ["OperatorAdmin"])
def complete_replacement(id):
    asset = asset_or_404(id)
    own(asset)
    data = body()
    try:
        install_year = int(field(data, "install_year"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "install_year must be an integer.")
    if asset["status"] != "REPLACEMENT_FLAGGED":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    work_order = services.draft_capital_work_order(asset)
    if work_order is None or work_order["status"] != "CLOSED":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    set_status(asset, "REPLACED", install_year=install_year)
    services.set_condition(asset, 100.0)
    for schedule in services.schedules_of(asset_id=asset["id"]):
        if schedule["status"] in ("ACTIVE", "DUE", "OVERDUE"):
            services.advance_schedule(schedule)
    return asset


@endpoint("/assets/<id>/take-out-of-service", ["POST"], ["OperatorAdmin"])
def take_out_of_service(id):
    asset = asset_or_404(id)
    own(asset)
    if asset["status"] != "IN_SERVICE":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    for work_order in DB["work_orders"].values():
        if work_order["asset_id"] == asset["id"] and work_order["status"] in (
                "SCHEDULED", "IN_PROGRESS", "PAUSED", "AWAITING_PARTS"):
            raise ApiError("ERR_OPEN_WORK_ORDER_BLOCKS")
    for schedule in services.schedules_of(asset_id=asset["id"]):
        if schedule["status"] in ("ACTIVE", "DUE", "OVERDUE"):
            set_status(schedule, "SUSPENDED")
    set_status(asset, "OUT_OF_SERVICE")
    return asset


@endpoint("/assets/<id>/return-to-service", ["POST"], ["OperatorAdmin"])
def return_to_service(id):
    asset = asset_or_404(id)
    own(asset)
    if asset["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    contract = DB["contracts"][asset["contract_id"]]
    if contract["status"] not in ("OPERATING", "UNDER_REVIEW", "RENEWED"):
        raise ApiError("ERR_ASSET_INVALID_STATE")
    if not calc.condition_at_least(asset.get("condition_score"), 40.0):
        raise ApiError("ERR_ASSET_INVALID_STATE")
    if not services.baseline_accepted(asset["id"]):
        raise ApiError("ERR_ASSET_BASELINE_UNRESOLVED")
    for schedule in services.schedules_of(asset_id=asset["id"], status="SUSPENDED"):
        set_status(schedule, "ACTIVE")
    set_status(asset, "IN_SERVICE")
    return asset


@endpoint("/assets/<id>/retire", ["POST"], ["MunicipalityAdmin"])
def retire_asset(id):
    asset = asset_or_404(id)
    own(asset)
    if asset["status"] == "RETIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if asset["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    contract = DB["contracts"][asset["contract_id"]]
    if contract["status"] not in ("HANDING_BACK", "TRANSITIONED"):
        raise ApiError("ERR_ASSET_INVALID_STATE")
    set_status(asset, "RETIRED")
    return asset


# --------------------------------------------------------------------------
# asset condition assessments
# --------------------------------------------------------------------------
@endpoint("/asset-assessments/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_assessment(id):
    assessment = assessment_or_404(id)
    own(assessment)
    return assessment


@endpoint("/asset-assessments/<id>/dispute", ["POST"], ["MunicipalityAdmin"])
def dispute_assessment(id):
    assessment = assessment_or_404(id)
    own(assessment)
    str_field(body(), "dispute_basis")
    if assessment["status"] == "ACCEPTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if assessment["status"] not in ("SUBMITTED", "REVISED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    asset = DB["assets"][assessment["asset_id"]]
    contract = DB["contracts"][asset["contract_id"]]
    if contract["baseline_frozen"]:
        raise ApiError("ERR_BASELINE_FROZEN")
    assessed_at = parse_dt(assessment.get("assessed_at"))
    if assessed_at is None or now() >= assessed_at + timedelta(days=30):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(assessment, "DISPUTED")
    if assessment.get("is_baseline") and asset["status"] in (
            "REGISTERED", "BASELINE_ASSESSED", "BASELINE_DISPUTED"):
        set_status(asset, "BASELINE_DISPUTED")
    return assessment


@endpoint("/asset-assessments/<id>/revise", ["POST"], ["OperatorAdmin"])
def revise_assessment(id):
    assessment = assessment_or_404(id)
    own(assessment)
    data = body()
    score = dec(field(data, "assessed_score"))
    if score < 0 or score > 100:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "assessed_score must be between 0.0 and 100.0.")
    if assessment["status"] != "DISPUTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    asset = DB["assets"][assessment["asset_id"]]
    contract = DB["contracts"][asset["contract_id"]]
    if contract["baseline_frozen"]:
        raise ApiError("ERR_BASELINE_FROZEN")
    set_status(assessment, "REVISED", assessed_score=float(score))
    services.set_condition(asset, score)
    return assessment


@endpoint("/asset-assessments/<id>/accept", ["POST"], ["MunicipalityAdmin"])
def accept_assessment(id):
    assessment = assessment_or_404(id)
    own(assessment)
    if assessment["status"] == "ACCEPTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    asset = DB["assets"][assessment["asset_id"]]
    contract = DB["contracts"][asset["contract_id"]]
    if assessment["status"] == "SUBMITTED":
        if contract["status"] not in ("AWARDED", "MOBILIZING", "OPERATING", "UNDER_REVIEW"):
            raise ApiError("ERR_ALREADY_TERMINAL")
    elif assessment["status"] != "REVISED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if assessment.get("_submitted_by") and assessment["_submitted_by"] == g.actor_id:
        raise ApiError("ERR_CROSS_TENANT_DENIED")
    if assessment.get("is_baseline"):
        for other in assessments_of(asset["id"]):
            if other is not assessment and other["status"] == "ACCEPTED" and other.get("baseline_binding"):
                raise ApiError("ERR_BASELINE_ALREADY_FROZEN")
    set_status(assessment, "ACCEPTED",
               baseline_binding=bool(assessment.get("is_baseline")))
    if assessment.get("is_baseline"):
        if asset["status"] == "REGISTERED":
            set_status(asset, "BASELINE_ASSESSED")
        elif asset["status"] == "BASELINE_DISPUTED" and contract["status"] == "MOBILIZING":
            set_status(asset, "IN_SERVICE")
    return assessment


@endpoint("/assets/<id>/emergency-events", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_asset_emergencies(id):
    asset = asset_or_404(id)
    own(asset)
    status = arg("status")
    event_type = arg("event_type")
    return paginate(ordered(services.emergencies_of(
        asset_id=asset["id"], status=status, event_type=event_type)))
