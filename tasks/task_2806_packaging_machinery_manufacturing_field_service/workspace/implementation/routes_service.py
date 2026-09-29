"""Service contracts and maintenance visits (PRD 3.8)."""
from flask import Blueprint

import auth
import calc
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("service", __name__)

CONTRACT_READERS = ("ServiceManager", "PlatformAdmin", "CustomerContact")
CONTRACT_STATUSES = ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
VISIT_STATUSES = ("SCHEDULED", "BILLABLE_HOLD", "COMPLETED", "CANCELLED")
VISIT_TYPES = ("PM", "REMOTE_DIAGNOSTIC", "CORRECTIVE")
FINDINGS_CODES = ("NONE", "OK", "WEAR_FOUND", "FAULT_FOUND")
TIERS = ("BRONZE", "SILVER", "GOLD")


def _cancel_visits(contract):
    """Both exits from ACTIVE close down the visit calendar (PRD 3.8)."""
    for visit in domain.children("pm_visits", "service_contract_id",
                                 contract["id"]):
        if visit["status"] in domain.LIVE_VISIT_STATUSES:
            visit["status"] = "CANCELLED"
            store.touch(visit)


# --------------------------------------------------------------------------
# service contracts
# --------------------------------------------------------------------------
@bp.post("/service-contracts")
def create_service_contract():
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    installed_machine_id = validation.req_str(payload, "installed_machine_id",
                                              1, None)
    tier = validation.req_enum(payload, "tier", TIERS)
    start_date = validation.req_date(payload, "start_date")
    end_date = validation.req_date(payload, "end_date")
    if store.parse_date(end_date) <= store.parse_date(start_date):
        raise validation.invalid("end_date must be strictly after start_date.")
    pm_visits_included = validation.req_int(payload, "pm_visits_included", 0)
    goodwill_initial = validation.req_int(payload,
                                          "goodwill_budget_initial_cents", 0)
    domain.must_get("installed_machines", installed_machine_id)
    row = store.insert("service_contracts", {
        "installed_machine_id": installed_machine_id,
        "tier": tier,
        "start_date": start_date,
        "end_date": end_date,
        "pm_visits_included": pm_visits_included,
        "pm_visits_used": 0,
        "goodwill_budget_initial_cents": goodwill_initial,
        "goodwill_budget_cents": 0,
        "coverage_posture": "OPEN",
        "status": "DRAFT",
    })
    return envelope.created(row)


@bp.get("/service-contracts")
def list_service_contracts():
    auth.authorize(CONTRACT_READERS)
    limit, offset = validation.pagination()
    filters = {
        "installed_machine_id": validation.query_str("installed_machine_id"),
        "status": validation.query_enum("status", CONTRACT_STATUSES),
    }
    items = [row for row in store.rows("service_contracts")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/service-contracts/<service_contract_id>")
def read_service_contract(service_contract_id):
    auth.authorize(CONTRACT_READERS)
    return envelope.ok(domain.must_get("service_contracts", service_contract_id))


@bp.post("/service-contracts/<service_contract_id>/activate")
def activate_service_contract(service_contract_id):
    auth.authorize(("ServiceManager",))
    contract = domain.must_get("service_contracts", service_contract_id)
    machine = store.get("installed_machines", contract["installed_machine_id"])
    if machine is None or machine["status"] != "ACCEPTED":
        raise ApiError("ERR_MACHINE_NOT_ACCEPTED",
                       "The covered machine has not been accepted.")
    if contract["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "Only a DRAFT contract may be activated.")
    today = store.today()
    if not (store.parse_date(contract["start_date"]) <= today
            <= store.parse_date(contract["end_date"])):
        raise ApiError("ERR_CONTRACT_WINDOW_INVALID",
                       "The logical clock date is outside the contract term.")
    contract["goodwill_budget_cents"] = int(
        contract["goodwill_budget_initial_cents"])
    contract["coverage_posture"] = calc.coverage_posture(
        contract["goodwill_budget_cents"])
    contract["status"] = "ACTIVE"
    store.touch(contract)
    return envelope.ok(contract)


@bp.post("/service-contracts/<service_contract_id>/expire")
def expire_service_contract(service_contract_id):
    auth.authorize(("ServiceManager",))
    contract = domain.must_get("service_contracts", service_contract_id)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "Only an ACTIVE contract may be expired.")
    if store.today() <= store.parse_date(contract["end_date"]):
        raise ApiError("ERR_CONTRACT_NOT_EXPIRABLE",
                       "The contract term has not passed yet.")
    contract["status"] = "EXPIRED"
    _cancel_visits(contract)
    domain.recompute_contract_pm_used(contract, bump=False)
    store.touch(contract)
    return envelope.ok(contract)


@bp.post("/service-contracts/<service_contract_id>/terminate")
def terminate_service_contract(service_contract_id):
    auth.authorize(("ServiceManager",))
    contract = domain.must_get("service_contracts", service_contract_id)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_CONTRACT_STATE",
                       "Only an ACTIVE contract may be terminated.")
    for claim in store.rows("warranty_claims"):
        if (claim["service_contract_id"] == contract["id"]
                and claim["status"] in domain.OPEN_CLAIM_STATUSES):
            raise ApiError("ERR_CLAIM_STILL_OPEN",
                           "An unresolved warranty claim blocks termination.")
    contract["status"] = "TERMINATED"
    _cancel_visits(contract)
    domain.recompute_contract_pm_used(contract, bump=False)
    store.touch(contract)
    return envelope.ok(contract)


# --------------------------------------------------------------------------
# maintenance visits
# --------------------------------------------------------------------------
@bp.post("/pm-visits")
def create_pm_visit():
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    service_contract_id = validation.req_str(payload, "service_contract_id",
                                             1, None)
    field_engineer_id = validation.opt_str(payload, "field_engineer_id", 1, None)
    visit_type = validation.req_enum(payload, "visit_type", VISIT_TYPES)
    start_ts = validation.req_instant(payload, "start_ts")
    end_ts = validation.req_instant(payload, "end_ts")
    if end_ts <= start_ts:
        raise validation.invalid("end_ts must be strictly after start_ts.")
    contract = domain.must_get("service_contracts", service_contract_id)
    engineer = None
    if field_engineer_id is not None:
        engineer = domain.must_get("field_engineers", field_engineer_id)
    machine = store.get("installed_machines", contract["installed_machine_id"])
    # rung 22
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE",
                       "The service contract is not ACTIVE.")
    # rung 25
    if engineer is not None and engineer["status"] != "AVAILABLE":
        raise ApiError("ERR_ENGINEER_ON_LEAVE",
                       "The nominated engineer is ON_LEAVE.")
    # rung 35
    if engineer is not None:
        model = domain.machine_model(machine) if machine is not None else None
        family = model["machine_family"] if model is not None else None
        if family not in list(engineer["certifications"] or []):
            raise ApiError("ERR_ENGINEER_NOT_CERTIFIED",
                           "The engineer is not certified on family %s."
                           % family)
    # rung 36
    if visit_type == "REMOTE_DIAGNOSTIC":
        if machine is None or not machine["remote_diagnostics_enabled"]:
            raise ApiError("ERR_REMOTE_DIAGNOSTICS_DISABLED",
                           "Remote diagnostics is disabled on this machine.")
    # rung 42
    term_start = store.day_start(contract["start_date"])
    term_end = store.day_end(contract["end_date"])
    if not (term_start <= start_ts <= term_end
            and term_start <= end_ts <= term_end):
        raise ApiError("ERR_VISIT_OUTSIDE_CONTRACT_TERM",
                       "The visit window falls outside the contract term.")
    # rung 48
    if engineer is not None:
        for incumbent in store.rows("pm_visits"):
            if (incumbent["field_engineer_id"] == engineer["id"]
                    and incumbent["status"] in domain.LIVE_VISIT_STATUSES
                    and domain.visits_collide(
                        start_ts, end_ts,
                        validation.parse_instant(incumbent["start_ts"],
                                                 "start_ts"),
                        validation.parse_instant(incumbent["end_ts"],
                                                 "end_ts"))):
                raise ApiError("ERR_ENGINEER_DOUBLE_BOOKED",
                               "The engineer already occupies that window.")
    # rung 53
    if visit_type in ("PM", "CORRECTIVE") and engineer is None:
        raise ApiError("ERR_ENGINEER_REQUIRED",
                       "On-site work requires a field_engineer_id.")
    # rung 56
    if engineer is not None:
        customer = (store.get("customers", machine["customer_id"])
                    if machine is not None else None)
        region = customer["region_code"] if customer is not None else None
        if engineer["region_code"] != region:
            raise ApiError("ERR_ENGINEER_REGION_MISMATCH",
                           "The engineer is not assigned to region %s."
                           % region)
    # rung 60
    if contract["coverage_posture"] == "BUDGET_EXHAUSTED":
        raise ApiError("ERR_COVERAGE_EXHAUSTED",
                       "The contract's goodwill pot is fully consumed.")
    # rung 61
    if (contract["coverage_posture"] == "RESTRICTED"
            and visit_type == "CORRECTIVE"):
        raise ApiError("ERR_POSTURE_RESTRICTED",
                       "A RESTRICTED contract refuses CORRECTIVE bookings.")
    row = store.insert("pm_visits", {
        "service_contract_id": service_contract_id,
        "field_engineer_id": field_engineer_id,
        "visit_type": visit_type,
        "start_ts": store.iso_ms(start_ts),
        "end_ts": store.iso_ms(end_ts),
        "status": "SCHEDULED",
        "billable": False,
        "findings_code": "NONE",
    })
    row["billable"] = domain.compute_billable(contract, visit_type, row["id"])
    domain.recompute_contract_pm_used(contract)
    return envelope.created(row)


@bp.get("/pm-visits")
def list_pm_visits():
    auth.authorize(CONTRACT_READERS)
    limit, offset = validation.pagination()
    filters = {
        "service_contract_id": validation.query_str("service_contract_id"),
        "field_engineer_id": validation.query_str("field_engineer_id"),
        "status": validation.query_enum("status", VISIT_STATUSES),
    }
    items = [row for row in store.rows("pm_visits")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/pm-visits/<pm_visit_id>")
def read_pm_visit(pm_visit_id):
    auth.authorize(CONTRACT_READERS)
    return envelope.ok(domain.must_get("pm_visits", pm_visit_id))


@bp.post("/pm-visits/<pm_visit_id>/complete")
def complete_pm_visit(pm_visit_id):
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    findings_code = validation.req_enum(payload, "findings_code",
                                        FINDINGS_CODES)
    visit = domain.must_get("pm_visits", pm_visit_id)
    if visit["status"] not in domain.LIVE_VISIT_STATUSES:
        raise ApiError("ERR_INVALID_VISIT_STATE",
                       "Only a SCHEDULED or BILLABLE_HOLD visit may be "
                       "completed.")
    if store.now() < validation.parse_instant(visit["end_ts"], "end_ts"):
        raise ApiError("ERR_VISIT_NOT_ELAPSED",
                       "The visit window has not elapsed yet.")
    visit["status"] = "COMPLETED"
    visit["findings_code"] = findings_code
    store.touch(visit)
    domain.recompute_contract_pm_used(
        store.get("service_contracts", visit["service_contract_id"]))
    return envelope.ok(visit)


@bp.post("/pm-visits/<pm_visit_id>/cancel")
def cancel_pm_visit(pm_visit_id):
    auth.authorize(("ServiceManager",))
    visit = domain.must_get("pm_visits", pm_visit_id)
    if visit["status"] not in domain.LIVE_VISIT_STATUSES:
        raise ApiError("ERR_INVALID_VISIT_STATE",
                       "Only a SCHEDULED or BILLABLE_HOLD visit may be "
                       "cancelled.")
    visit["status"] = "CANCELLED"
    store.touch(visit)
    domain.recompute_contract_pm_used(
        store.get("service_contracts", visit["service_contract_id"]))
    return envelope.ok(visit)
