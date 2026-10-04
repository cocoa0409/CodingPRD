"""Staffing commitments and employee transition endpoints — PRD 3.3."""
from datetime import timedelta

import calc
import services
from core import (ApiError, DB, apply, arg, body, create, dec, endpoint, field,
                  g, get, now, ordered, own, paginate, parse_dt, set_status,
                  str_field)


def commitment_or_404(commitment_id):
    return get("staffing", commitment_id, "ERR_STAFFING_NOT_FOUND")


def employee_or_404(employee_id):
    return get("employees", employee_id, "ERR_EMPLOYEE_NOT_FOUND")


def commitment_under(contract_id, commitment_id):
    commitment = commitment_or_404(commitment_id)
    if commitment["contract_id"] != contract_id:
        raise ApiError("ERR_STAFFING_NOT_FOUND")
    return commitment


def employee_under(contract_id, employee_id):
    employee = employee_or_404(employee_id)
    if employee["contract_id"] != contract_id:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    return employee


def _floor_guard_commitments(contract, excluding=None):
    """PRD 3.3: staffing may not drop below the floor while an emergency is open."""
    if not services.open_emergency_events(contract["id"]):
        return
    total = dec(0)
    for commitment in services.commitments_of(contract["id"]):
        if commitment is excluding:
            continue
        if commitment["status"] in ("BINDING", "REMEDIATING", "SATISFIED"):
            total += dec(commitment.get("committed_fte") or 0)
    if total < dec(contract.get("staffing_floor_fte") or 0):
        raise ApiError("ERR_EMERGENCY_STAFFING_FLOOR")


def _floor_guard_filled(contract, excluding_employee=None):
    if not services.open_emergency_events(contract["id"]):
        return
    total = dec(0)
    for commitment in services.commitments_of(contract["id"]):
        if commitment["status"] not in ("BINDING", "REMEDIATING", "SATISFIED"):
            continue
        for employee in services.employees_of(contract["id"], role_code=commitment["role_code"]):
            if employee is excluding_employee or employee["status"] not in services.FILLED_STATUSES:
                continue
            total += dec(employee.get("transfer_offer_fte") or 0)
    if total < dec(contract.get("staffing_floor_fte") or 0):
        raise ApiError("ERR_EMERGENCY_STAFFING_FLOOR")


# --------------------------------------------------------------------------
# staffing commitments
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/staffing-commitments", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_commitments(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    return paginate(ordered(services.commitments_of(contract["id"], status)))


@endpoint("/contracts/<id>/staffing-commitments", ["POST"], ["OperatorAdmin"], status=201)
def create_commitment(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    role_code = str_field(data, "role_code")
    committed = dec(field(data, "committed_fte"))
    if committed < 0:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "committed_fte must be zero or greater.")
    for existing in services.commitments_of(contract["id"]):
        if existing["role_code"] == role_code:
            raise ApiError("ERR_INVALID_DATE_WINDOW", "role_code must be unique within the contract.")
    return create("staffing",
                  contract_id=contract["id"],
                  role_code=role_code,
                  committed_fte=float(committed),
                  filled_fte=0.0,
                  vacancy_fte=0.0,
                  status="DRAFT")


@endpoint("/staffing-commitments/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def read_commitment(id):
    commitment = commitment_or_404(id)
    own(commitment)
    return commitment


@endpoint("/contracts/<id>/staffing-commitments/<cid>/bind", ["POST"], ["OperatorAdmin"])
def bind_commitment(id, cid):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    commitment = commitment_under(contract["id"], cid)
    if commitment["status"] != "DRAFT":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if dec(commitment.get("committed_fte") or 0) < 0:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contract["status"] != "MOBILIZING":
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(commitment, "BINDING")
    services.refresh_commitment(commitment, demote=False)
    return commitment


@endpoint("/staffing-commitments/<id>/evaluate", ["POST"], ["OperatorAdmin"])
def evaluate_commitment(id):
    commitment = commitment_or_404(id)
    own(commitment)
    data = body()
    filled = dec(field(data, "filled_fte"))
    contract = DB["contracts"][commitment["contract_id"]]
    committed = dec(commitment.get("committed_fte") or 0)
    vacancy = committed - filled
    if vacancy < 0:
        vacancy = dec(0)
    apply(commitment, filled_fte=float(filled), vacancy_fte=float(vacancy))
    if commitment["status"] == "BINDING":
        if filled < committed:
            set_status(commitment, "SHORTFALL")
            services.refresh_commitment(commitment, demote=False)
    elif commitment["status"] == "REMEDIATING":
        if filled >= committed:
            set_status(commitment, "SATISFIED", vacancy_fte=0.0)
            for employee in services.employees_of(contract["id"], status="OFFERED",
                                                  role_code=commitment["role_code"]):
                set_status(employee, "WITHDRAWN")
        else:
            changed = parse_dt(commitment.get("status_changed_at"))
            if changed is not None and now() >= changed + timedelta(days=30):
                set_status(commitment, "SHORTFALL")
                services.refresh_commitment(commitment, demote=False)
                if contract["status"] == "OPERATING":
                    set_status(contract, "UNDER_REVIEW")
    return commitment


@endpoint("/staffing-commitments/<id>/remedy", ["POST"], ["OperatorAdmin"])
def remedy_commitment(id):
    commitment = commitment_or_404(id)
    own(commitment)
    data = body()
    str_field(data, "remedy_plan")
    if commitment["status"] != "SHORTFALL":
        raise ApiError("ERR_ALREADY_TERMINAL")
    offered = services.employees_of(commitment["contract_id"], status="OFFERED",
                                    role_code=commitment["role_code"])
    if not offered:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(commitment, "REMEDIATING")
    return commitment


@endpoint("/staffing-commitments/<id>/suspend", ["POST"], ["MunicipalityAdmin"])
def suspend_commitment(id):
    commitment = commitment_or_404(id)
    own(commitment)
    if commitment["status"] not in ("BINDING", "SATISFIED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][commitment["contract_id"]]
    if contract["status"] not in ("HANDING_BACK", "TERMINATED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    _floor_guard_commitments(contract, excluding=commitment)
    set_status(commitment, "SUSPENDED", filled_fte=0.0)
    return commitment


# --------------------------------------------------------------------------
# employees
# --------------------------------------------------------------------------
@endpoint("/contracts/<id>/employees", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_contract_employees(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    status = arg("status")
    role_code = arg("role_code")
    return paginate(ordered(services.employees_of(contract["id"], status, role_code)))


@endpoint("/contracts/<id>/employees", ["POST"], ["OperatorAdmin"], status=201)
def register_employee(id):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    data = body()
    role_code = str_field(data, "role_code")
    full_name = str_field(data, "full_name")
    hire = parse_dt(field(data, "municipal_hire_date"))
    offer_fte = dec(field(data, "transfer_offer_fte"))
    if offer_fte <= 0 or offer_fte > 1:
        raise ApiError("ERR_INVALID_DATE_WINDOW", "transfer_offer_fte must be greater than 0 and at most 1.0.")
    if services.matching_commitment(contract["id"], role_code) is None:
        raise ApiError("ERR_INVALID_DATE_WINDOW",
                       "role_code must match a staffing commitment on the same contract.")
    years, _, _ = calc.vesting(hire, parse_dt(contract["contract_start_date"]))
    return create("employees",
                  contract_id=contract["id"],
                  role_code=role_code,
                  full_name=full_name,
                  municipal_hire_date=hire.isoformat().replace("+00:00", "Z"),
                  municipal_years_of_service=years,
                  transfer_offer_fte=float(offer_fte),
                  benefit_tier="NONE",
                  pension_offset_cents=0,
                  status="MUNICIPAL")


@endpoint("/contracts/<id>/employees/<eid>/offer", ["POST"], ["OperatorAdmin"])
def offer_employee(id, eid):
    contract = get("contracts", id, "ERR_CONTRACT_NOT_FOUND")
    own(contract)
    employee = employee_under(contract["id"], eid)
    if employee["status"] != "MUNICIPAL":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if dec(employee.get("transfer_offer_fte") or 0) <= 0:
        raise ApiError("ERR_ALREADY_TERMINAL")
    commitment = services.matching_commitment(contract["id"], employee["role_code"])
    if commitment is None or commitment["status"] not in ("BINDING", "REMEDIATING"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if contract["status"] not in ("MOBILIZING", "OPERATING"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    years, tier, offset = calc.vesting(parse_dt(employee["municipal_hire_date"]),
                                       parse_dt(contract["contract_start_date"]))
    set_status(employee, "OFFERED",
               benefit_tier=tier,
               pension_offset_cents=offset,
               municipal_years_of_service=years)
    return employee


@endpoint("/employees", ["GET"], ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin"])
def list_employees():
    status = arg("status")
    role_code = arg("role_code")
    items = [e for e in DB["employees"].values()
             if (status is None or e["status"] == status)
             and (role_code is None or e["role_code"] == role_code)]
    return paginate(ordered(items))


@endpoint("/employees/<id>", ["GET"],
          ["PlatformAdmin", "MunicipalityAdmin", "OperatorAdmin", "Employee"])
def read_employee(id):
    employee = employee_or_404(id)
    if g.actor_role == "Employee" and id != g.actor_id:
        raise ApiError("ERR_SELF_SERVICE_OWNER_MISMATCH")
    own(employee)
    return employee


@endpoint("/employees/<id>/accept", ["POST"], ["Employee"], self_service=True)
def accept_offer(id):
    employee = employee_or_404(id)
    if employee["status"] != "OFFERED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    changed = parse_dt(employee.get("status_changed_at"))
    if changed is None or now() >= changed + timedelta(days=21):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(employee, "ACCEPTED")
    return employee


@endpoint("/employees/<id>/decline", ["POST"], ["Employee"], self_service=True)
def decline_offer(id):
    employee = employee_or_404(id)
    contract = DB["contracts"][employee["contract_id"]]
    if employee["status"] == "OFFERED":
        pass
    elif employee["status"] == "ACCEPTED":
        changed = parse_dt(employee.get("status_changed_at"))
        if changed is None or now() < changed + timedelta(days=7):
            raise ApiError("ERR_ALREADY_TERMINAL")
    else:
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(employee, "DECLINED")
    commitment = services.matching_commitment(contract["id"], employee["role_code"])
    if commitment is not None:
        services.refresh_commitment(commitment)
    return employee


@endpoint("/employees/<id>/transfer", ["POST"], ["OperatorAdmin"])
def transfer_employee(id):
    employee = employee_or_404(id)
    own(employee)
    if employee["status"] != "ACCEPTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][employee["contract_id"]]
    # The employee is in its correct from-state; what blocks the transfer is the
    # owning contract's state, so this is not the terminal-state guard of PRD §3.10.
    if not contract["baseline_frozen"]:
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    if now() < parse_dt(contract["contract_start_date"]):
        raise ApiError("ERR_CONTRACT_INVALID_STATE")
    set_status(employee, "TRANSFERRED")
    commitment = services.matching_commitment(contract["id"], employee["role_code"])
    if commitment is not None:
        filled = dec(commitment.get("filled_fte") or 0) + dec(employee.get("transfer_offer_fte") or 0)
        committed = dec(commitment.get("committed_fte") or 0)
        vacancy = committed - filled
        if vacancy < 0:
            vacancy = dec(0)
        apply(commitment, filled_fte=float(filled), vacancy_fte=float(vacancy))
        if filled >= committed and commitment["status"] == "SHORTFALL":
            set_status(commitment, "SATISFIED")
    return employee


@endpoint("/employees/<id>/begin-induction", ["POST"], ["OperatorAdmin"])
def begin_induction(id):
    employee = employee_or_404(id)
    own(employee)
    if employee["status"] != "TRANSFERRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][employee["contract_id"]]
    if now() >= parse_dt(contract["contract_start_date"]) + timedelta(days=30):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(employee, "INDUCTION")
    return employee


@endpoint("/employees/<id>/complete-induction", ["POST"], ["OperatorAdmin"])
def complete_induction(id):
    employee = employee_or_404(id)
    own(employee)
    if employee["status"] != "INDUCTION":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if int(employee.get("pension_offset_cents") or 0) < 0:
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][employee["contract_id"]]
    if contract["status"] == "OPERATING":
        for obligation in services.obligations_of(contract["id"]):
            if obligation["obligation_type"] == "EMPLOYEE_REINSTATE" \
                    and obligation["status"] in ("PENDING", "IN_PROGRESS", "OVERDUE",
                                                 "DISPUTED", "ESCALATED"):
                raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(employee, "ACTIVE")
    commitment = services.matching_commitment(contract["id"], employee["role_code"])
    if commitment is not None:
        services.refresh_commitment(commitment, demote=False)
    return employee


@endpoint("/employees/<id>/withdraw-offer", ["POST"], ["OperatorAdmin"])
def withdraw_offer(id):
    employee = employee_or_404(id)
    own(employee)
    if employee["status"] != "OFFERED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][employee["contract_id"]]
    if now() >= parse_dt(contract["contract_start_date"]):
        raise ApiError("ERR_ALREADY_TERMINAL")
    set_status(employee, "MUNICIPAL", benefit_tier="NONE", pension_offset_cents=0)
    return employee


@endpoint("/employees/<id>/separate", ["POST"], ["OperatorAdmin"])
def separate_employee(id):
    employee = employee_or_404(id)
    own(employee)
    data = body()
    str_field(data, "separation_reason")
    if employee["status"] != "ACTIVE":
        raise ApiError("ERR_ALREADY_TERMINAL")
    contract = DB["contracts"][employee["contract_id"]]
    _floor_guard_filled(contract, excluding_employee=employee)
    set_status(employee, "SEPARATED")
    commitment = services.matching_commitment(contract["id"], employee["role_code"])
    if commitment is not None:
        services.refresh_commitment(commitment)
    return employee
