"""Permit and penalty allocation endpoints — PRD 3.4, 3.5."""
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, body, create, dec, endpoint, field,
                  get, now, ordered, own, paginate, parse_dt, set_status,
                  str_field)

PERMIT_TYPES = ("NPDES_DISCHARGE", "WATER_ALLOCATION", "SLUDGE_LAND_APPLICATION",
                "AIR_EMISSIONS")
REGULATORS = ("STATE_PRIMACY_AGENCY", "USEPA_REGION", "LOCAL_HEALTH_DEPARTMENT")
CONTEST_WINDOW_DAYS = 60
RENEWAL_WINDOW_DAYS = 180
RENEWAL_EXTENSION_DAYS = 365


def permit_or_404(permit_id):
    return get("permits", permit_id, "ERR_PERMIT_NOT_FOUND")


def allocation_or_404(allocation_id):
    return get("allocations", allocation_id, "ERR_ALLOCATION_NOT_FOUND")


def allocations_of(permit_id, status=None):
    return [a for a in DB["allocations"].values()
            if a["permit_id"] == permit_id and (status is None or a["status"] == status)]


def _adjust_totals(allocation, operator_delta):
    contract = DB["contracts"][allocation["contract_id"]]
    apply(contract, total_operator_penalty_cents=max(
        0, int(contract.get("total_operator_penalty_cents") or 0) + operator_delta))
    municipality = DB["municipalities"].get(contract["municipality_id"])
    if municipality is not None:
        apply(municipality, total_operator_penalty_cents=max(
            0, int(municipality.get("total_operator_penalty_cents") or 0) + operator_delta))


# --------------------------------------------------------------------------
# permits
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/permits", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_permits(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    permit_type = arg("permit_type")
    items = [p for p in services.permits_of(contract["id"], status)
             if permit_type is None or p["permit_type"] == permit_type]
    return paginate(ordered(items))


@endpoint("/contracts/<id>/permits", ["POST"], ["OperatorAdmin"], status=201)
def create_permit(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    number = str_field(data, "permit_number")
    permit_type = str_field(data, "permit_type")
    regulator = str_field(data, "regulator")
    if permit_type not in PERMIT_TYPES:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown permit_type.")
    if regulator not in REGULATORS:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "Unknown regulator.")
    effective = parse_dt(field(data, "effective_date"))
    expiration = parse_dt(field(data, "expiration_date"))
    if expiration <= effective:
        raise ApiError("ERR_INVALID_DATE_WINDOW")
    for existing in services.permits_of(contract["id"]):
        if existing["permit_type"] == permit_type and existing["status"] != "EXPIRED":
            raise ApiError("ERR_DUPLICATE_ACTIVE_PERMIT_TYPE")
    return create("permits",
                  contract_id=contract["id"],
                  permit_number=number,
                  permit_type=permit_type,
                  regulator=regulator,
                  effective_date=effective.isoformat().replace("+00:00", "Z"),
                  expiration_date=expiration.isoformat().replace("+00:00", "Z"),
                  status="APPLICATION_DRAFTED")


@endpoint("/permits/<id>", ["GET"], ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_permit(id):
    permit = permit_or_404(id)
    own(permit)
    return permit


@endpoint("/permits/<id>/submit-application", ["POST"], ["OperatorAdmin"])
def submit_application(id):
    permit = permit_or_404(id)
    own(permit)
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] != "APPLICATION_DRAFTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if parse_dt(permit["expiration_date"]) <= parse_dt(permit["effective_date"]):
        raise ApiError("ERR_INVALID_DATE_WINDOW")
    set_status(permit, "SUBMITTED")
    return permit


@endpoint("/permits/<id>/issue", ["POST"], ["MunicipalityAdmin"])
def issue_permit(id):
    permit = permit_or_404(id)
    own(permit)
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] != "SUBMITTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][permit["contract_id"]]
    if not contract["baseline_frozen"]:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(permit, "ISSUED")
    return permit


@endpoint("/permits/<id>/activate", ["POST"], ["OperatorAdmin"])
def activate_permit(id):
    permit = permit_or_404(id)
    own(permit)
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] != "ISSUED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if now() < parse_dt(permit["effective_date"]):
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][permit["contract_id"]]
    if contract["status"] not in ("OPERATING", "UNDER_REVIEW", "RENEWED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(permit, "ACTIVE")
    return permit


@endpoint("/permits/<id>/notices-of-violation", ["POST"], ["MunicipalityAdmin"])
def notice_of_violation(id):
    permit = permit_or_404(id)
    own(permit)
    data = body()
    str_field(data, "citation_code")
    parse_dt(field(data, "cited_at"))
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_ALREADY_TERMINAL")
    offending = None
    for allocation in allocations_of(permit["id"]):
        if allocation["status"] in ("ALLOCATED", "CONTESTED", "ADJUSTED"):
            offending = allocation
            break
    if offending is None:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(permit, "NOTICE_OF_VIOLATION")
    if offending["status"] == "ALLOCATED":
        set_status(offending, "CONTESTED")
    return permit


@endpoint("/permits/<id>/clear-violation", ["POST"], ["MunicipalityAdmin"])
def clear_violation(id):
    permit = permit_or_404(id)
    own(permit)
    if permit["status"] != "NOTICE_OF_VIOLATION":
        raise ApiError("ERR_ALREADY_TERMINAL")
    for allocation in allocations_of(permit["id"]):
        if allocation["status"] not in ("SETTLED", "VOIDED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(permit, "ACTIVE")
    return permit


@endpoint("/permits/<id>/file-renewal", ["POST"], ["OperatorAdmin"])
def file_renewal(id):
    permit = permit_or_404(id)
    own(permit)
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_ALREADY_TERMINAL")
    expiration = parse_dt(permit["expiration_date"])
    if now() < expiration - timedelta(days=RENEWAL_WINDOW_DAYS):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(permit, "RENEWAL_FILED")
    permit["effective_date"] = (parse_dt(permit["effective_date"])
                                + timedelta(days=RENEWAL_EXTENSION_DAYS)).isoformat().replace("+00:00", "Z")
    permit["expiration_date"] = (expiration
                                 + timedelta(days=RENEWAL_EXTENSION_DAYS)).isoformat().replace("+00:00", "Z")
    return permit


@endpoint("/permits/<id>/activate-renewal", ["POST"], ["MunicipalityAdmin"])
def activate_renewal(id):
    permit = permit_or_404(id)
    own(permit)
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] != "RENEWAL_FILED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(permit, "ACTIVE")
    return permit


@endpoint("/permits/<id>/suspend", ["POST"], ["MunicipalityAdmin"])
def suspend_permit(id):
    permit = permit_or_404(id)
    own(permit)
    data = body()
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] == "ACTIVE":
        str_field(data, "suspension_basis")
        for schedule in services.schedules_of(contract_id=permit["contract_id"], status="ACTIVE"):
            asset = DB["assets"].get(schedule["asset_id"])
            if asset is not None and asset["asset_class"] == "TREATMENT_UNIT":
                set_status(schedule, "SUSPENDED")
        set_status(permit, "SUSPENDED")
    elif permit["status"] == "RENEWAL_FILED":
        if not allocations_of(permit["id"], "CONTESTED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
        set_status(permit, "SUSPENDED")
    else:
        raise ApiError("ERR_ALREADY_TERMINAL")
    return permit


@endpoint("/permits/<id>/reinstate", ["POST"], ["MunicipalityAdmin"])
def reinstate_permit(id):
    permit = permit_or_404(id)
    own(permit)
    if permit["status"] == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if permit["status"] != "SUSPENDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    for allocation in allocations_of(permit["id"]):
        if allocation["status"] in ("ALLOCATED", "CONTESTED"):
            raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(permit, "ACTIVE")
    return permit


# --------------------------------------------------------------------------
# penalty allocations
# --------------------------------------------------------------------------
@endpoint("/permits/<id>/penalty-allocations", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_permit_allocations(id):
    permit = permit_or_404(id)
    own(permit)
    status = arg("status")
    return paginate(ordered(allocations_of(permit["id"], status)))


@endpoint("/contracts/<id>/penalty-allocations", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_contract_allocations(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    return paginate(ordered(services.allocations_of(contract["id"], status)))


@endpoint("/permits/<id>/penalty-allocations", ["POST"], ["MunicipalityAdmin"], status=201)
def create_allocation(id):
    permit = permit_or_404(id)
    own(permit)
    data = body()
    violation_code = str_field(data, "violation_code")
    try:
        total = int(field(data, "total_penalty_cents"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "total_penalty_cents must be an integer.")
    if total < 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "total_penalty_cents must be zero or greater.")
    contract = DB["contracts"][permit["contract_id"]]
    allocation = create("allocations",
                        permit_id=permit["id"],
                        contract_id=contract["id"],
                        violation_code=violation_code,
                        total_penalty_cents=total,
                        operator_share_cents=0,
                        municipality_share_cents=0,
                        state_baseline_share_cents=0,
                        status="ALLOCATED")
    operator, municipality, baseline = services.recompute_allocation(allocation, total)
    apply(allocation, operator_share_cents=operator,
          municipality_share_cents=municipality,
          state_baseline_share_cents=baseline)
    _adjust_totals(allocation, operator)
    return allocation


@endpoint("/penalty-allocations/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_allocation(id):
    allocation = allocation_or_404(id)
    own(allocation)
    return allocation


@endpoint("/penalty-allocations/<id>/contest", ["POST"], ["MunicipalityAdmin"])
def contest_allocation(id):
    allocation = allocation_or_404(id)
    own(allocation)
    str_field(body(), "contest_basis")
    if allocation["status"] in ("SETTLED", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if allocation["status"] not in ("ALLOCATED", "ADJUSTED"):
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")
    changed = parse_dt(allocation.get("status_changed_at"))
    if changed is None or now() >= changed + timedelta(days=CONTEST_WINDOW_DAYS):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(allocation, "CONTESTED")
    return allocation


@endpoint("/penalty-allocations/<id>/adjust", ["POST"], ["MunicipalityAdmin"])
def adjust_allocation(id):
    allocation = allocation_or_404(id)
    own(allocation)
    data = body()
    try:
        total = int(field(data, "total_penalty_cents"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "total_penalty_cents must be an integer.")
    if total < 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "total_penalty_cents must be zero or greater.")
    if allocation["status"] in ("SETTLED", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if allocation["status"] not in ("CONTESTED", "ADJUSTED"):
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")
    previous = int(allocation["operator_share_cents"])
    apply(allocation, total_penalty_cents=total)
    operator, municipality, baseline = services.recompute_allocation(allocation, total)
    apply(allocation, operator_share_cents=operator,
          municipality_share_cents=municipality,
          state_baseline_share_cents=baseline)
    set_status(allocation, "ADJUSTED")
    _adjust_totals(allocation, operator - previous)
    return allocation


@endpoint("/penalty-allocations/<id>/void", ["POST"], ["MunicipalityAdmin"])
def void_allocation(id):
    allocation = allocation_or_404(id)
    own(allocation)
    str_field(body(), "void_basis")
    if allocation["status"] in ("SETTLED", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if allocation["status"] != "CONTESTED":
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")
    for sibling in allocations_of(allocation["permit_id"]):
        if sibling["status"] == "SETTLED":
            raise ApiError("ERR_ALREADY_TERMINAL")
    previous = int(allocation["operator_share_cents"])
    set_status(allocation, "VOIDED")
    _adjust_totals(allocation, -previous)
    return allocation


@endpoint("/penalty-allocations/<id>/settle", ["POST"], ["MunicipalityAdmin"])
def settle_allocation(id):
    allocation = allocation_or_404(id)
    own(allocation)
    status = allocation["status"]
    if status in ("SETTLED", "VOIDED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][allocation["contract_id"]]
    municipality = DB["municipalities"].get(contract["municipality_id"])
    if status == "ADJUSTED":
        if municipality is not None:
            expected = 0
            for sibling in DB["allocations"].values():
                if sibling["contract_id"] in [c["id"] for c in DB["contracts"].values()
                                              if c["municipality_id"] == municipality["id"]]:
                    if sibling["status"] != "VOIDED":
                        expected += int(sibling["operator_share_cents"])
            if int(municipality.get("total_operator_penalty_cents") or 0) != expected:
                raise ApiError("ERR_PENALTY_ALLOCATION_NOT_CONSERVED")
    elif status == "ALLOCATED":
        changed = parse_dt(allocation.get("status_changed_at"))
        if changed is None or now() < changed + timedelta(days=CONTEST_WINDOW_DAYS):
            raise ApiError("ERR_ALREADY_TERMINAL")
    else:
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")
    set_status(allocation, "SETTLED")
    return allocation
