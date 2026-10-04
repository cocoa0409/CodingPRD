"""Procedure cases: booking, occupancy, the instrument bill and bulk work."""

from flask import Blueprint

from db import DB, base_record, as_int, as_bool, as_str, check_version, to_iso, touch
from errors import ApiError
from middleware import authenticate
from response import success
from routes import common
from serializers import procedure_case as ser_case
from services import calc, machines

bp = Blueprint("cases", __name__)

PROCEDURE_FAMILIES = ("UROLOGY", "GYNECOLOGY", "GENERAL_SURGERY", "THORACIC", "COLORECTAL")


def _owned_system(ctx, system_id):
    """Resolve the system and enforce the entity-backed ownership rule."""
    system = common.get_system(system_id)
    if ctx.role == "AccountOwner" and system.get("hospital_account_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    return system


def _operator_of(case_or_record_id, account):
    """The training record named by a case must belong to the same account."""
    record = common.get_record(case_or_record_id)
    if record.get("hospital_account_id") != account.get("id"):
        raise ApiError("ERR_REFERENTIAL_INTEGRITY_VIOLATION")
    return record


def _assert_credentialed(record, account):
    """Every procedure-case mutation is guarded by the credential-validity step
    of the training-path evaluation (PRD §2.1 / §3.4)."""
    if not calc.credential_valid(record):
        raise ApiError("ERR_SURGEON_NOT_CREDENTIALED")


@bp.post("/api/robot-systems/<system_id>/procedure-cases")
def schedule_case(system_id):
    ctx = authenticate(["AccountOwner"])
    system = _owned_system(ctx, system_id)
    account = common.get_account(system.get("hospital_account_id"))
    data = common.body()
    record_id = common.require_str(data, "training_record_id")
    family = common.require_str(data, "procedure_family").upper()
    if family not in PROCEDURE_FAMILIES:
        raise ApiError("ERR_INVALID_REQUEST")
    started = common.require_dt(data, "case_started_at")
    duration = common.require_int(data, "duration_minutes")
    attempted = as_int(data.get("instrument_load"), 0)
    if attempted < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    is_emergency = as_bool(data.get("is_emergency"))

    # Cross-entity state gate: a system that has been taken out of service refuses
    # an elective booking, while an emergency add-on is still accepted. The case
    # then bills zero because a service-action-required system is never billable.
    if system.get("service_status") == "SERVICE_ACTION_REQUIRED" and not is_emergency:
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")

    # Priority 18 — the referenced operator must exist and belong to the account.
    record = _operator_of(record_id, account)

    # Priority 19 — occupancy is exclusive on a system.
    siblings = calc.cases_of_system(system.get("id"))
    if calc.schedule_conflict(started, duration, siblings):
        raise ApiError("ERR_CASE_SCHEDULE_CONFLICT")

    # Priority 20 — the load is clamped rather than refused outright.
    remaining = calc.instrument_lives_remaining(system)
    approved = calc.clamp_load(attempted, remaining)
    if attempted > 0 and approved == 0:
        raise ApiError("ERR_INSTRUMENT_LIVES_EXHAUSTED")

    # Priority 41 — the operator must be credential-valid.
    _assert_credentialed(record, account)

    agreement = DB.placement_agreements.get(system.get("placement_agreement_id"))
    case = base_record({
        "robot_system_id": system.get("id"),
        "hospital_account_id": account.get("id"),
        "placement_agreement_id": system.get("placement_agreement_id"),
        "training_record_id": record.get("id"),
        "procedure_family": family,
        "case_started_at": to_iso(started),
        "duration_minutes": duration,
        "instrument_load": attempted,
        "is_emergency": is_emergency,
        "approved_instrument_load": approved,
        "instrument_billing_cents": 0,
        "commitment_cycle_index": 0,
        "case_status": "SCHEDULED",
    })
    # The commitment interval the case was booked into, stamped now.
    if agreement is not None:
        start = calc.parse_iso(agreement.get("cycle_start_utc"))
        end = calc.agreement_cycle_end(agreement)
        if start is not None and end is not None and start <= DB.clock < end:
            case["commitment_cycle_index"] = int(agreement.get("_cycle_index") or 0)
    # Quote variant — reads the attempted load, before the clamp.
    case["instrument_billing_cents"] = calc.instrument_billing(case, load=attempted, mode="quote")
    case["anticipated_instrument_lives_remaining"] = max(0, remaining - approved)
    DB.procedure_cases[case["id"]] = case
    machines.refresh_system(system)
    machines.refresh_posture(account)
    return success(ser_case(case)), 201


@bp.get("/api/procedure-cases")
def list_cases():
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer",
                  "AccountOwner"])
    records = list(DB.procedure_cases.values())
    system_id = common.arg("robot_system_id")
    if system_id:
        records = [r for r in records if r.get("robot_system_id") == system_id]
    account_id = common.arg("hospital_account_id")
    if account_id:
        records = [r for r in records if r.get("hospital_account_id") == account_id]
    status = common.arg("case_status")
    if status:
        records = [r for r in records if r.get("case_status") == status]
    agreement_id = common.arg("placement_agreement_id")
    if agreement_id:
        records = [r for r in records if r.get("placement_agreement_id") == agreement_id]
    record_id = common.arg("training_record_id")
    if record_id:
        records = [r for r in records if r.get("training_record_id") == record_id]
    from_dt = common.arg_dt("case_started_from")
    if from_dt is not None:
        records = [r for r in records
                   if (calc.parse_iso(r.get("case_started_at")) or from_dt) >= from_dt]
    to_dt = common.arg_dt("case_started_to")
    if to_dt is not None:
        records = [r for r in records
                   if (calc.parse_iso(r.get("case_started_at")) or to_dt) <= to_dt]
    return common.paged(records, "procedure_cases")


@bp.get("/api/procedure-cases/<case_id>")
def get_case(case_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "ComplianceOfficer",
                  "AccountOwner"])
    return success(ser_case(common.get_case(case_id)))


@bp.get("/api/robot-systems/<system_id>/procedure-cases")
def list_system_cases(system_id):
    authenticate(["PlatformAdmin", "RegionalSalesDirector", "AccountOwner"])
    common.get_system(system_id)
    records = calc.cases_of_system(system_id)
    status = common.arg("case_status")
    if status:
        records = [r for r in records if r.get("case_status") == status]
    return common.paged(records, "procedure_cases")


@bp.post("/api/procedure-cases/<case_id>/reschedule")
def reschedule_case(case_id):
    """Move a case to a new start instant.

    A case may always be rescheduled against its own freed slot: the candidate
    occupancy replaces the case's own prior occupancy.
    """
    ctx = authenticate(["AccountOwner"])
    case = common.get_case(case_id)
    account = common.get_account(case.get("hospital_account_id"))
    if case.get("hospital_account_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    data = common.body()
    started = common.require_dt(data, "case_started_at")
    duration = data.get("duration_minutes")
    if duration is None:
        duration = case.get("duration_minutes")
    record = _operator_of(case.get("training_record_id"), account)
    _assert_credentialed(record, account)
    siblings = calc.cases_of_system(case.get("robot_system_id"))
    if calc.schedule_conflict(started, duration, siblings, ignore_case_id=case.get("id")):
        raise ApiError("ERR_CASE_SCHEDULE_CONFLICT")
    check_version(case, data, "expected_case_version")
    case["case_started_at"] = to_iso(started)
    case["duration_minutes"] = as_int(duration)
    touch(case)
    return success(ser_case(case))


@bp.post("/api/procedure-cases/<case_id>/mark-completed")
def mark_completed(case_id):
    """Record a case as delivered.

    This single call increments four versions: the case's, the parent
    agreement's, the utilization cycle's and the account's.
    """
    ctx = authenticate(["AccountOwner"])
    case = common.get_case(case_id)
    account = common.get_account(case.get("hospital_account_id"))
    if case.get("hospital_account_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    data = common.body()
    record = _operator_of(case.get("training_record_id"), account)
    _assert_credentialed(record, account)
    if case.get("case_status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_REQUEST")
    check_version(case, data, "expected_case_version")

    case["case_status"] = "COMPLETED"
    # Settle variant — recomputed from the approved, clamped load.
    case["instrument_billing_cents"] = calc.instrument_billing(case, mode="settle")
    touch(case)

    agreement = DB.placement_agreements.get(case.get("placement_agreement_id"))
    if agreement is not None:
        machines.refresh_commitment(agreement)
        touch(agreement)

    system = DB.robot_systems.get(case.get("robot_system_id"))
    if system is not None:
        cycle = calc.current_cycle(system)
        if cycle is not None:
            cycle["utilization_band"] = calc.utilization_band(cycle)
            touch(cycle)
        machines.refresh_system(system)

    # The observed service-line depth, the utilization posture and the
    # expansion status are all reconciled off this completion.
    account["service_line_tier"] = calc.service_line_tier_label(account)
    machines.refresh_posture(account)
    touch(account)
    for other in calc.systems_of_account(account.get("id")):
        machines.refresh_system(other)
    calc.expansion_status(account)
    return success(ser_case(case))


@bp.post("/api/procedure-cases/bulk-complete")
def bulk_complete():
    """Bulk-complete a set of scheduled cases.

    Ineligible cases are skipped rather than rolled back, so a partially valid
    batch still makes progress; naming a system outside the acting account's
    scope is refused for the whole batch.
    """
    ctx = authenticate(["AccountOwner"])
    data = common.body()
    case_ids = data.get("case_ids")
    if not isinstance(case_ids, list):
        raise ApiError("ERR_INVALID_REQUEST")
    # Priority 27 — every named system must belong to the acting account.
    for case_id in case_ids:
        case = DB.procedure_cases.get(as_str(case_id))
        if case is None:
            continue
        if case.get("hospital_account_id") != ctx.user_id:
            raise ApiError("ERR_BULK_SCOPE_VIOLATION")
    completed = 0
    skipped = []
    for case_id in case_ids:
        case = DB.procedure_cases.get(as_str(case_id))
        if case is None:
            skipped.append(as_str(case_id))
            continue
        account = DB.hospital_accounts.get(case.get("hospital_account_id"))
        record = DB.surgeon_training_records.get(case.get("training_record_id"))
        if (case.get("case_status") != "SCHEDULED"
                or record is None or not calc.credential_valid(record)):
            skipped.append(case.get("id"))
            continue
        case["case_status"] = "COMPLETED"
        case["instrument_billing_cents"] = calc.instrument_billing(case, mode="settle")
        touch(case)
        agreement = DB.placement_agreements.get(case.get("placement_agreement_id"))
        if agreement is not None:
            machines.refresh_commitment(agreement)
            touch(agreement)
        system = DB.robot_systems.get(case.get("robot_system_id"))
        if system is not None:
            cycle = calc.current_cycle(system)
            if cycle is not None:
                cycle["utilization_band"] = calc.utilization_band(cycle)
                touch(cycle)
            machines.refresh_system(system)
        if account is not None:
            account["service_line_tier"] = calc.service_line_tier_label(account)
            machines.refresh_posture(account)
            touch(account)
        completed += 1
    return success({"completed_count": completed, "skipped_case_ids": skipped})


@bp.post("/api/procedure-cases/<case_id>/cancel")
def cancel_case(case_id):
    """Cancel a case and release its instrument load back to the accumulator."""
    ctx = authenticate(["HospitalProcurementOfficer", "AccountOwner"])
    case = common.get_case(case_id)
    account = common.get_account(case.get("hospital_account_id"))
    if ctx.role == "AccountOwner" and case.get("hospital_account_id") != ctx.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")
    data = common.body()
    if ctx.role == "AccountOwner":
        record = _operator_of(case.get("training_record_id"), account)
        _assert_credentialed(record, account)
    if case.get("case_status") != "SCHEDULED":
        raise ApiError("ERR_INVALID_REQUEST")
    check_version(case, data, "expected_case_version")
    case["case_status"] = "CANCELLED"
    case["instrument_billing_cents"] = calc.instrument_billing(case, mode="settle")
    touch(case)
    system = DB.robot_systems.get(case.get("robot_system_id"))
    if system is not None:
        machines.refresh_system(system)
    return success(ser_case(case))