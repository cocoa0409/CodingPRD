"""Response serializers.

Each serializer emits the entity's own stored fields plus its computed fields.
Computed values are derived on read so they stay consistent no matter which
workflow last touched the row. Field names come from SCAFFOLD.yaml §1.1 —
nothing is renamed or invented.
"""

from db import DB, to_iso
from services import calc


def _copy(rec, drop=()):
    out = {}
    for key, value in rec.items():
        if key in drop or key.startswith("_"):
            continue
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# Hospital account
# ---------------------------------------------------------------------------

def account(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["account_posture"] = calc.account_posture(rec)
    out["service_line_tier"] = calc.service_line_tier_label(rec)
    # PRD §2.9 makes the account the owner of "the account's penalty balance",
    # "clamped to the range from 0 to 15", so the resource exposes it.
    out["penalty_balance_points"] = calc.penalty_balance(rec)
    return out


# ---------------------------------------------------------------------------
# Site readiness
# ---------------------------------------------------------------------------

def readiness_review(rec):
    if rec is None:
        return None
    out = _copy(rec)
    # The clearance count is a live reconciliation; the construction uplift was
    # quoted once, at creation, and is returned as stored (PRD §3.1.1).
    out["conditional_clearance_count"] = calc.conditional_clearance_count(rec)
    return out


def system_configuration(rec):
    if rec is None:
        return None
    return _copy(rec)


# ---------------------------------------------------------------------------
# Agreements and systems
# ---------------------------------------------------------------------------

def agreement(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["committed_cases"] = calc.committed_cases(rec)
    out["cycle_end_utc"] = to_iso(calc.agreement_cycle_end(rec))
    if rec.get("compliance_status") is None:
        out["compliance_status"] = calc.compliance_status(rec)
    return out


def robot_system(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["instrument_lives_remaining"] = calc.instrument_lives_remaining(rec)
    out["expansion_eligible"] = calc.expansion_eligible(rec)
    config = DB.system_configurations.get(rec.get("system_configuration_id"))
    index = int(rec.get("installed_software_release_index") or 0)
    out["entitled_feature_codes"] = calc.entitled_feature_codes(config, index)
    out["accessory_set_status"] = calc.accessory_set_status(rec)
    return out


# ---------------------------------------------------------------------------
# Cases and cycles
# ---------------------------------------------------------------------------

def procedure_case(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["instrument_billing_cents"] = calc.reported_instrument_billing(rec)
    return out


def utilization_cycle(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["cycle_end_utc"] = to_iso(calc.cycle_end(rec))
    out["scheduled_case_count"] = calc.scheduled_case_count(rec)
    out["completed_case_count"] = calc.completed_case_count(rec)
    out["utilization_band"] = calc.utilization_band(rec)
    out["same_hour_conflict_count"] = calc.same_hour_conflict_count(rec)
    return out


# ---------------------------------------------------------------------------
# Training and credentialing
# ---------------------------------------------------------------------------

def training_record(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["simulation_ready"] = calc.simulation_ready(rec)
    out["proctoring_ready"] = calc.proctoring_ready(rec)
    out["proctoring_satisfied"] = calc.proctoring_satisfied(rec)
    out["credentialing_ready"] = calc.credentialing_ready(rec)
    out["credential_valid"] = calc.credential_valid(rec)
    # The proctor cases logged against this record, and the one still awaiting
    # a compliance decision: `POST /api/proctor-cases/{proctorCaseId}/approve`
    # is addressed by the child's own id, so the parent exposes it.
    proctors = sorted(calc.proctor_cases_of_record(rec.get("id")),
                      key=lambda p: (p.get("created_at") or "", p.get("_seq") or 0))
    out["proctor_case_ids"] = [p.get("id") for p in proctors]
    pending = None
    for proctor in proctors:
        if proctor.get("proctor_status") == "PROCTOR_LOGGED":
            pending = proctor.get("id")
            break
    out["pending_proctor_case_id"] = pending
    # The declared approval path addresses its child by `{proctorCaseId}`, so the
    # identifier of the case awaiting the compliance decision is part of the
    # response surface: without it the endpoint cannot be reached.
    out["proctor_case_id"] = pending
    return out


def credentialing_evidence(rec):
    if rec is None:
        return None
    return _copy(rec)


def proctor_case(rec):
    if rec is None:
        return None
    return _copy(rec)


# ---------------------------------------------------------------------------
# Coverage, incidents, loaners and software
# ---------------------------------------------------------------------------

def service_contract(rec):
    if rec is None:
        return None
    out = _copy(rec)
    index = calc.service_tier_index(rec)
    out["service_tier_index"] = index if index >= 0 else None
    out["response_time_commitment_hours"] = calc.contract_response_hours(rec)
    out["contract_end_utc"] = to_iso(calc.contract_end(rec))
    return out


def incident(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["response_due_at_utc"] = calc.incident_response_due(rec)
    out["is_response_breached"] = calc.incident_breached(rec)
    out["resolution_penalty_points"] = calc.incident_resolution_penalty(rec)
    return out


def loaner_dispatch(rec):
    if rec is None:
        return None
    return _copy(rec)


def software_release(rec):
    if rec is None:
        return None
    return _copy(rec)


def software_deployment(rec):
    if rec is None:
        return None
    out = _copy(rec)
    system = DB.robot_systems.get(rec.get("robot_system_id"))
    config = None
    if system:
        config = DB.system_configurations.get(system.get("system_configuration_id"))
    index = int((system or {}).get("installed_software_release_index") or 0)
    out["entitlement_snapshot"] = calc.entitled_feature_codes(config, index)
    return out


# ---------------------------------------------------------------------------
# Expansion and IDN pool
# ---------------------------------------------------------------------------

def expansion_review(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["eligible_system_utilization"] = calc.eligible_system_utilization(rec)
    account = DB.hospital_accounts.get(rec.get("hospital_account_id"))
    out["expansion_status"] = calc.expansion_status(account)
    out["requires_prior_reporting_period"] = calc.requires_prior_reporting_period(rec)
    return out


def consumption_ledger(rec):
    if rec is None:
        return None
    out = _copy(rec)
    out["remaining_credit_units"] = calc.remaining_credit_units(rec)
    return out


def transfer_transaction(rec):
    if rec is None:
        return None
    return _copy(rec)


SERIALIZERS = {
    "hospital_accounts": account,
    "site_readiness_reviews": readiness_review,
    "system_configurations": system_configuration,
    "placement_agreements": agreement,
    "robot_systems": robot_system,
    "surgeon_training_records": training_record,
    "credentialing_evidence": credentialing_evidence,
    "utilization_cycles": utilization_cycle,
    "procedure_cases": procedure_case,
    "loaner_dispatches": loaner_dispatch,
    "service_contracts": service_contract,
    "incidents": incident,
    "software_releases": software_release,
    "software_deployments": software_deployment,
    "expansion_reviews": expansion_review,
    "consumption_ledgers": consumption_ledger,
    "transfer_transactions": transfer_transaction,
    "proctor_cases": proctor_case,
}


def serialize(collection, rec):
    func = SERIALIZERS.get(collection)
    return func(rec) if func else _copy(rec)


def serialize_all(collection, records):
    return [serialize(collection, r) for r in records]