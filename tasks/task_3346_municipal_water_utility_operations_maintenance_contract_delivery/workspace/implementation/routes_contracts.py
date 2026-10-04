"""Municipality and Contract endpoints — PRD 3.1, 3.4 (review), 3.8, 3.9."""
import re
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, body, create, dec, endpoint, field,
                  get, iso, now, now_iso, ordered, paginate, parse_dt,
                  parse_dt_opt as parse_dt_optional, rows, set_status, str_field)

LIVE_CONTRACT_STATUSES = ("OPERATING", "UNDER_REVIEW", "RENEWED")


def contract_or_404(contract_id):
    return get("contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")


def _version_guard(contract, data):
    """PRD 2.8: version-checked contract writes."""
    if "expected_contract_version" not in data or data.get("expected_contract_version") is None:
        return
    try:
        expected = int(data["expected_contract_version"])
    except (TypeError, ValueError):
        raise ApiError("ERR_STALE_VERSION")
    if expected != int(contract["version"]):
        raise ApiError("ERR_STALE_VERSION")


def _municipality_or_404(municipality_id):
    return get("municipalities", municipality_id, "ERR_MUNICIPALITY_NOT_FOUND")


# --------------------------------------------------------------------------
# municipalities
# --------------------------------------------------------------------------
@endpoint("/municipalities", ["POST"], ["PlatformAdmin"], status=201)
def register_municipality():
    data = body()
    name = str_field(data, "name")
    state_code = str_field(data, "state_code")
    if not re.fullmatch(r"[A-Z]{2}", state_code):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "state_code must be exactly two uppercase letters.")
    try:
        population = int(field(data, "population_served"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "population_served must be an integer.")
    if population < 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "population_served must be zero or greater.")
    owns = data.get("owns_treatment_works")
    municipality = create("municipalities",
                          name=name,
                          state_code=state_code,
                          population_served=population,
                          owns_treatment_works=bool(owns),
                          benchmark_index_baseline=0.0,
                          total_operator_penalty_cents=0)
    return municipality


@endpoint("/municipalities/<id>", ["GET"], ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_municipality(id):
    municipality = _municipality_or_404(id)
    from core import own
    own(municipality)
    return municipality


@endpoint("/municipalities/<id>/contracts", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_municipality_contracts(id):
    _municipality_or_404(id)
    status = arg("status")
    items = [c for c in DB["contracts"].values()
             if c["municipality_id"] == id and (status is None or c["status"] == status)]
    return paginate(ordered(items))


@endpoint("/municipalities/<id>/contracts", ["POST"], ["MunicipalityAdmin"], status=201)
def award_contract(id):
    municipality = _municipality_or_404(id)
    from core import own
    own(municipality)
    data = body()
    title = str_field(data, "title")
    start = parse_dt(field(data, "contract_start_date"))
    end = parse_dt(field(data, "contract_end_date"))
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_WINDOW")
    award_date = parse_dt_optional(data.get("award_date")) or start
    try:
        annual_fee = int(field(data, "annual_fee_cents"))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_DATE_WINDOW", "annual_fee_cents must be an integer.")
    if annual_fee < 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "annual_fee_cents must be at least 1.")
    pct = dec(field(data, "operator_penalty_share_pct"))
    if pct < 0 or pct > 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "operator_penalty_share_pct must be between 0.0 and 1.0.")
    contract = create("contracts",
                      municipality_id=municipality["id"],
                      title=title,
                      award_date=parse_dt(award_date).isoformat().replace("+00:00", "Z"),
                      contract_start_date=start.isoformat().replace("+00:00", "Z"),
                      contract_end_date=end.isoformat().replace("+00:00", "Z"),
                      annual_fee_cents=annual_fee,
                      operator_penalty_share_pct=float(pct),
                      staffing_floor_fte=0.0,
                      total_operator_penalty_cents=0,
                      status="AWARDED",
                      baseline_frozen=False,
                      baseline_asset_count=0,
                      renewal_round=0)
    if data.get("benchmark_index_baseline") is not None:
        apply(municipality, benchmark_index_baseline=float(dec(data["benchmark_index_baseline"])))
    return contract


@endpoint("/municipalities/<id>/benchmark", ["GET"], ["PlatformAdmin", "MunicipalityAdmin"])
def read_benchmark(id):
    municipality = _municipality_or_404(id)
    from core import own
    own(municipality)
    index = calc.benchmark_index(municipality)
    comparator = calc.benchmark_comparator(municipality)
    return municipality, 200, {
        "municipality_id": municipality["id"],
        "benchmark_index_baseline": index,
        "comparator_basis_index": comparator,
        "comparator_index": comparator,
    }


# --------------------------------------------------------------------------
# contracts
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>", ["GET"], ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_contract(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    return contract


@endpoint("/contracts/<id>/mobilize", ["POST"], ["OperatorAdmin"])
def mobilize_contract(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    if contract["status"] != "AWARDED":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if contract["baseline_frozen"]:
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if not services.standards_of(contract["id"], "ACTIVE"):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if now() < parse_dt(contract["contract_start_date"]):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")

    for commitment in services.commitments_of(contract["id"], "DRAFT"):
        set_status(commitment, "BINDING")
        services.refresh_commitment(commitment, demote=False)
    floor = services.recompute_staffing_floor(contract)
    bound = services.commitments_of(contract["id"], "BINDING")
    committed_total = sum((dec(c.get("committed_fte") or 0) for c in bound), dec(0))
    if dec(floor) > committed_total and bound:
        bound.sort(key=lambda c: (dec(c.get("committed_fte") or 0), c["created_at"], c["_seq"]))
        lowest = bound[0]
        set_status(lowest, "SHORTFALL")
        services.refresh_commitment(lowest, demote=False)
    set_status(contract, "MOBILIZING")
    return contract


@endpoint("/contracts/<id>/commence-operating", ["POST"], ["OperatorAdmin"])
def commence_operating(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    if contract["status"] != "MOBILIZING":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if not contract["baseline_frozen"]:
        raise ApiError("ERR_ASSET_BASELINE_UNRESOLVED")
    for asset in services.assets_of(contract["id"]):
        if asset["status"] in ("BASELINE_ASSESSED", "BASELINE_DISPUTED"):
            if not services.baseline_accepted(asset["id"]):
                raise ApiError("ERR_ASSET_BASELINE_UNRESOLVED")
    if services.commitments_of(contract["id"], "SHORTFALL"):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    filled = sum((dec(c.get("filled_fte") or 0)
                  for c in services.commitments_of(contract["id"])
                  if c["status"] in ("BINDING", "REMEDIATING", "SATISFIED")), dec(0))
    if filled < dec(contract.get("staffing_floor_fte") or 0):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")

    for asset in services.assets_of(contract["id"]):
        if asset["status"] in ("BASELINE_ASSESSED", "BASELINE_DISPUTED"):
            for assessment in DB["assessments"].values():
                if assessment["asset_id"] == asset["id"] and assessment["status"] == "ACCEPTED":
                    apply(assessment, baseline_binding=True)
            set_status(asset, "IN_SERVICE")
    start = parse_dt(contract["contract_start_date"])
    for schedule in services.schedules_of(contract_id=contract["id"], status="DRAFT"):
        set_status(schedule, "ACTIVE")
        schedule["next_due_at"] = iso(start + timedelta(days=int(schedule["frequency_days"])))
    set_status(contract, "OPERATING")
    return contract


@endpoint("/contracts/<id>/freeze-baseline", ["POST"], ["MunicipalityAdmin"])
def freeze_baseline(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    for asset in services.assets_of(contract["id"]):
        if not services.baseline_accepted(asset["id"]):
            raise ApiError("ERR_ASSET_BASELINE_UNRESOLVED")
    count = 0
    for assessment in DB["assessments"].values():
        asset = DB["assets"].get(assessment["asset_id"])
        if asset and asset["contract_id"] == contract["id"] \
                and assessment.get("is_baseline") and assessment["status"] == "ACCEPTED":
            count += 1
    apply(contract, baseline_frozen=True, baseline_asset_count=count)
    return contract


@endpoint("/contracts/<id>/reviews", ["POST"], ["MunicipalityAdmin", "OperatorAdmin"])
def contract_review(id):
    contract = contract_or_404(id)
    from core import g, own
    own(contract)
    data = body()
    status = contract["status"]
    if status == "OPERATING":
        if g.actor_role != "MunicipalityAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        if now() < parse_dt(contract["contract_start_date"]):
            raise ApiError("ERR_CONTRACT_INVALID_STATE")
        _version_guard(contract, data)
        _open_review(contract)
    elif status == "UNDER_REVIEW":
        if g.actor_role != "OperatorAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        _version_guard(contract, data)
        if services.standards_of(contract["id"], "BREACHED"):
            raise ApiError("ERR_OPEN_BREACH_BLOCKS")
        set_status(contract, "OPERATING")
    else:
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    return contract


def _open_review(contract):
    candidates = []
    for standard in services.standards_of(contract["id"], "ACTIVE"):
        latest = services.latest_measurement(standard["id"])
        if latest is not None and latest.get("in_breach"):
            candidates.append((standard, latest))
    prospective = services.breach_penalty_total(contract["id"])
    prospective += sum(int(s.get("breach_penalty_cents") or 0) for s, _ in candidates)
    if prospective > int(contract["annual_fee_cents"]):
        raise ApiError("ERR_PENALTY_CAP_EXCEEDED")
    set_status(contract, "UNDER_REVIEW")
    for standard, latest in candidates:
        services.mark_breached(standard, latest.get("metric_type") or standard["metric_type"])
        if dec(contract.get("total_operator_penalty_cents") or 0) > dec(contract["annual_fee_cents"]):
            _auto_measurement(standard, latest)
    services.recompute_staffing_floor(contract)


def _auto_measurement(standard, previous):
    start = parse_dt(previous.get("period_end")) or now()
    end = parse_dt(previous.get("period_end")) or now()
    length = (end - (parse_dt(previous.get("period_start")) or start))
    if length.total_seconds() <= 0:
        length = timedelta(days=30)
    measured = 0.0
    create("measurements",
           performance_standard_id=standard["id"],
           period_start=iso(start),
           period_end=iso(start + length),
           measured_value=measured,
           in_breach=calc.in_breach_value(standard, measured),
           weighted_breach_score=0.0,
           status="RECORDED")


@endpoint("/contracts/<id>/renewals", ["POST"], ["OperatorAdmin", "MunicipalityAdmin"])
def contract_renewals(id):
    contract = contract_or_404(id)
    from core import g, own
    own(contract)
    status = contract["status"]
    if status == "UNDER_REVIEW":
        if g.actor_role != "OperatorAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        if now() < parse_dt(contract["contract_end_date"]) - timedelta(days=180):
            raise ApiError("ERR_CONTRACT_INVALID_STATE")
        if not contract["baseline_frozen"]:
            raise ApiError("ERR_CONTRACT_INVALID_STATE")
        set_status(contract, "RENEWAL_PENDING")
    elif status == "HANDING_BACK":
        if g.actor_role != "MunicipalityAdmin":
            raise ApiError("ERR_ROLE_FORBIDDEN")
        for obligation in services.obligations_of(contract["id"]):
            if obligation.get("is_critical") and obligation["status"] not in ("SATISFIED", "WAIVED"):
                raise ApiError("ERR_CRITICAL_OBLIGATIONS_OUTSTANDING")
        services.waiver_of_non_critical(contract)
        set_status(contract, "RENEWAL_PENDING")
    else:
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    return contract


@endpoint("/contracts/<id>/hand-back", ["POST"], ["MunicipalityAdmin"])
def begin_hand_back(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    data = body()
    status = contract["status"]
    if status not in ("RENEWAL_PENDING", "UNDER_REVIEW"):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if not contract["baseline_frozen"]:
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if services.proposals_of(contract["id"], "SUBMITTED"):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    _version_guard(contract, data)
    start = now()
    set_status(contract, "HANDING_BACK")
    contract["_handback_started_at"] = iso(start)
    due = start + timedelta(days=30)
    for asset in services.assets_of(contract["id"]):
        services.create_obligation(contract, "ASSET_HANDOVER", due, False, 0)
    if status == "RENEWAL_PENDING":
        for employee in services.employees_of(contract["id"]):
            if employee["status"] in ("TRANSFERRED", "INDUCTION", "ACTIVE"):
                services.create_obligation(contract, "EMPLOYEE_REINSTATE", due, False, 0)
    return contract


@endpoint("/contracts/<id>/complete-hand-back", ["POST"], ["MunicipalityAdmin"])
def complete_hand_back(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    if contract["status"] != "HANDING_BACK":
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    figures = calc.settlement(contract)
    if figures["net_payable_cents"] < 0:
        raise ApiError("ERR_NEGATIVE_SETTLEMENT")
    for obligation in services.obligations_of(contract["id"]):
        if obligation.get("is_critical") and obligation["status"] in (
                "PENDING", "IN_PROGRESS", "OVERDUE", "ESCALATED"):
            raise ApiError("ERR_CRITICAL_OBLIGATIONS_OUTSTANDING")
    if services.permit_action_unresolved(contract["id"]):
        raise ApiError("ERR_PERMIT_ACTION_UNRESOLVED")

    for asset in services.assets_of(contract["id"]):
        if asset["status"] == "IN_SERVICE":
            set_status(asset, "OUT_OF_SERVICE")
    for permit in services.permits_of(contract["id"]):
        if permit["status"] == "ACTIVE":
            set_status(permit, "EXPIRED")
    for schedule in services.schedules_of(contract_id=contract["id"]):
        if schedule["status"] in ("ACTIVE", "DUE", "OVERDUE"):
            set_status(schedule, "RETIRED")
    set_status(contract, "TRANSITIONED")
    return contract


@endpoint("/contracts/<id>/terminate", ["POST"], ["MunicipalityAdmin"])
def terminate_contract(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    str_field(body(), "termination_reason", required=False)
    status = contract["status"]
    if status == "OPERATING":
        employees = ("TRANSFERRED", "INDUCTION", "ACTIVE", "OFFERED", "ACCEPTED")
        schedules = True
    elif status == "UNDER_REVIEW":
        if not services.standards_of(contract["id"], "BREACHED"):
            raise ApiError("ERR_CONTRACT_INVALID_STATE")
        employees = ("TRANSFERRED", "INDUCTION", "ACTIVE")
        schedules = False
    else:
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if services.permit_action_unresolved(contract["id"]):
        raise ApiError("ERR_PERMIT_ACTION_UNRESOLVED")
    for employee in services.employees_of(contract["id"]):
        if employee["status"] in employees:
            set_status(employee, "SEPARATED")
    for permit in services.permits_of(contract["id"]):
        if permit["status"] == "ACTIVE":
            set_status(permit, "SUSPENDED")
    if schedules:
        for schedule in services.schedules_of(contract_id=contract["id"]):
            if schedule["status"] in ("ACTIVE", "DUE", "OVERDUE"):
                set_status(schedule, "SUSPENDED")
    set_status(contract, "TERMINATED")
    return contract


@endpoint("/contracts/<id>/settlement", ["GET"], ["MunicipalityAdmin", "PlatformAdmin"])
def read_settlement(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    return calc.settlement(contract)


@endpoint("/contracts/<id>/pm-schedules", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_contract_pm_schedules(id):
    contract = contract_or_404(id)
    from core import own
    own(contract)
    status = arg("status")
    asset_id = arg("asset_id")
    items = services.schedules_of(contract_id=contract["id"], asset_id=asset_id, status=status)
    return paginate(ordered(items))
