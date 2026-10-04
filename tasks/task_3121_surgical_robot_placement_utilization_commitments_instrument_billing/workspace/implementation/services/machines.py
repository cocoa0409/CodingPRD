"""State machines, cascades and derived-field reconciliation.

Transitions, their preconditions and their side effects come from
SCAFFOLD.yaml §1.2 (and the matching PRD §2 / §3 workflows). Cascades run hop
by hop, and each hop bumps the version of every row it mutates, as PRD §2.7
requires of any mutation including a derived reconciliation.
"""

from datetime import timedelta

from db import DB, base_record, to_iso, touch, parse_iso8601
from errors import ApiError
from services import calc


# ---------------------------------------------------------------------------
# Derived-field reconciliation
# ---------------------------------------------------------------------------

def refresh_posture(account):
    """Recompute account_posture (PRD §2.5 pinned order). No version bump."""
    if account is None:
        return None
    account["account_posture"] = calc.account_posture(account)
    return account


def refresh_commitment(agreement):
    """Recompute placement_agreement_commitment_state. No version bump.

    `compliance_status` is deliberately NOT touched here: SCAFFOLD §1.3 gives
    `shortfall_compliance_status` exactly two triggers — the month-close run and
    the shortfall waiver — so no other reconciliation may move it.
    """
    if agreement is None:
        return None
    agreement["shortfall_procedures"] = calc.shortfall_procedures(agreement)
    agreement["committed_cases"] = calc.committed_cases(agreement)
    agreement["cycle_end_utc"] = to_iso(calc.agreement_cycle_end(agreement))
    return agreement


def refresh_system(system):
    if system is None:
        return None
    system["instrument_lives_remaining"] = calc.instrument_lives_remaining(system)
    system["expansion_eligible"] = calc.expansion_eligible(system)
    return system


def refresh_account_and_systems(account):
    refresh_posture(account)
    for system in calc.systems_of_account((account or {}).get("id")):
        refresh_system(system)


def account_of(record):
    return DB.hospital_accounts.get((record or {}).get("hospital_account_id"))


def system_of(record):
    return DB.robot_systems.get((record or {}).get("robot_system_id"))


def systems_of_agreement(agreement):
    return [s for s in DB.robot_systems.values()
            if s.get("placement_agreement_id") == (agreement or {}).get("id")]


# ---------------------------------------------------------------------------
# UtilizationCycle lifecycle
# ---------------------------------------------------------------------------

def cycle_for_interval(system, agreement):
    """The cycle mirroring an agreement's current commitment interval.

    Reused when one already exists for that interval rather than duplicated
    (PRD §3.2, commissioning).
    """
    if system is None or agreement is None:
        return None
    start = parse_iso8601(agreement.get("cycle_start_utc"))
    if start is None:
        return None
    start_text = to_iso(start)
    for cycle in DB.utilization_cycles.values():
        if (cycle.get("robot_system_id") == system.get("id")
                and cycle.get("cycle_start_utc") == start_text):
            return cycle
    record = base_record({
        "robot_system_id": system.get("id"),
        "placement_agreement_id": agreement.get("id"),
        "cycle_start_utc": start_text,
        "reporting_period_index": 0,
    })
    DB.utilization_cycles[record["id"]] = record
    return record


def open_cycles_for_account(account):
    """Open a fresh cycle for every system of the account.

    None exist on the PROSPECT → READINESS path, so this is a no-op in
    practice, but PRD §2.5 requires it be performed regardless.
    """
    for system in calc.systems_of_account((account or {}).get("id")):
        agreement = DB.placement_agreements.get(system.get("placement_agreement_id"))
        if agreement is None:
            continue
        cycle = cycle_for_interval(system, agreement)
        if cycle is not None and system.get("current_utilization_cycle_id") is None:
            system["current_utilization_cycle_id"] = cycle["id"]
            touch(system)


# ---------------------------------------------------------------------------
# Shared cascades
# ---------------------------------------------------------------------------

def cancel_non_terminal_cases(systems):
    """Every SCHEDULED or COMPLETED case on these systems → CANCELLED."""
    for system in systems:
        for case in calc.cases_of_system(system.get("id")):
            if case.get("case_status") in ("SCHEDULED", "COMPLETED"):
                case["case_status"] = "CANCELLED"
                touch(case)


def terminate_active_contracts(systems):
    for system in systems:
        for contract in calc.contracts_of_system(system.get("id")):
            if contract.get("contract_status") == "ACTIVE":
                contract["contract_status"] = "TERMINATED"
                touch(contract)


def resolve_open_incidents(systems):
    """Every OPEN or ACKNOWLEDGED incident → RESOLVED."""
    for system in systems:
        for incident in calc.incidents_of_system(system.get("id")):
            if incident.get("request_status") in ("OPEN", "ACKNOWLEDGED"):
                incident["request_status"] = "RESOLVED"
                incident["resolved_at_utc"] = to_iso(DB.clock)
                touch(incident)


def cancel_dispatches(systems):
    """Every PROGRAMMED or ACTIVATED loaner dispatch → CANCELLED."""
    for system in systems:
        for dispatch in calc.dispatches_of_system(system.get("id")):
            if dispatch.get("reservation_status") in ("PROGRAMMED", "ACTIVATED"):
                dispatch["reservation_status"] = "CANCELLED"
                touch(dispatch)


def reclaim_dispatches(systems, reason="CONTRACT_EXPIRED"):
    """The CONTRACT_EXPIRED reclaim wave leaves dispatches RECLAIMED."""
    for system in systems:
        for dispatch in calc.dispatches_of_system(system.get("id")):
            if dispatch.get("reservation_status") in ("PROGRAMMED", "ACTIVATED"):
                dispatch["reservation_status"] = "RECLAIMED"
                dispatch["reclaim_reason"] = reason
                touch(dispatch)


def decommission_systems(systems):
    for system in systems:
        system["service_status"] = "DECOMMISSIONED"
        touch(system)


# ---------------------------------------------------------------------------
# HospitalAccount state machine
# ---------------------------------------------------------------------------

def account_prospect_to_readiness(account):
    if account.get("account_status") != "PROSPECT":
        raise ApiError("ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE")
    if not calc.reviews_of_account(account.get("id")):
        raise ApiError("ERR_READINESS_REVIEW_REQUIRED")
    if not calc.training_records_of_account(account.get("id")):
        raise ApiError("ERR_TRAINING_PATH_UNINITIALIZED")
    account["account_status"] = "READINESS"
    refresh_posture(account)
    open_cycles_for_account(account)
    touch(account)
    return account


def advance_readiness_to_contracted(account):
    """READINESS → CONTRACTED, evaluated after a placement agreement is
    drafted for the account.

    The transition only fires from `READINESS`; an account that already moved on
    (`CONTRACTED`, `ACTIVE`, `DORMANT`, `CLOSED`) simply keeps its status, because
    `placement_cap` caps how many concurrently non-terminal agreements an account
    may hold, so several drafts against one account are expected. A draft against
    an account still in `PROSPECT` never activated is the `ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE`
    case PRD §2.5 pins.
    """
    status = account.get("account_status")
    if status in ("CONTRACTED", "ACTIVE", "DORMANT", "CLOSED"):
        return account
    if status != "READINESS":
        raise ApiError("ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE")
    if not calc.agreements_of_account(account.get("id")):
        raise ApiError("ERR_NO_PLACEMENT_AGREEMENT")
    account["account_status"] = "CONTRACTED"
    refresh_posture(account)
    return account


def account_to_active(account):
    """CONTRACTED → ACTIVE (automatic once an agreement reaches ACTIVE).

    Requires exactly zero non-terminal readiness reviews and at least one
    ACTIVE agreement; stamps the newly active agreement's cycle start.
    """
    if account is None:
        return None
    if account.get("account_status") not in ("CONTRACTED", "READINESS"):
        return account
    reviews = calc.reviews_of_account(account.get("id"))
    if any(r.get("readiness_status") in ("PENDING_REVIEW", "CONDITIONAL", "REJECTED")
           for r in reviews):
        return account
    if not any(a.get("agreement_status") == "ACTIVE"
               for a in calc.agreements_of_account(account.get("id"))):
        return account
    account["account_status"] = "ACTIVE"
    for agreement in calc.agreements_of_account(account.get("id")):
        if agreement.get("agreement_status") == "ACTIVE":
            if not agreement.get("cycle_start_utc"):
                agreement["cycle_start_utc"] = to_iso(DB.clock)
                agreement["cycle_end_utc"] = to_iso(calc.agreement_cycle_end(agreement))
                touch(agreement)
            refresh_commitment(agreement)
    refresh_posture(account)
    return account


def account_to_dormant(account):
    if account is None or account.get("account_status") != "ACTIVE":
        return False
    account["account_status"] = "DORMANT"
    account["dormant_since_utc"] = to_iso(DB.clock)
    refresh_posture(account)
    touch(account)
    return True


def account_reactivate(account):
    if account.get("account_status") != "DORMANT":
        raise ApiError("ERR_ACCOUNT_NOT_IN_ELIGIBLE_STATE")
    account["account_status"] = "ACTIVE"
    account["dormant_since_utc"] = None
    refresh_posture(account)
    touch(account)
    return account


def account_close(account):
    if account.get("account_status") not in ("ACTIVE", "DORMANT"):
        raise ApiError("ERR_ACCOUNT_NOT_CLOSABLE")
    for agreement in calc.agreements_of_account(account.get("id")):
        if agreement.get("agreement_status") in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_ACTIVE_AGREEMENT_EXISTS")
    systems = calc.systems_of_account(account.get("id"))
    account["account_status"] = "CLOSED"
    cancel_non_terminal_cases(systems)
    terminate_active_contracts(systems)
    refresh_posture(account)
    refresh_account_and_systems(account)
    touch(account)
    return account


# ---------------------------------------------------------------------------
# RobotSystem state machine
# ---------------------------------------------------------------------------

def system_install(system, account, agreement, review):
    if system.get("service_status") != "NOT_INSTALLED":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    if review is None or review.get("readiness_status") != "PASSED":
        raise ApiError("ERR_SYSTEM_SITE_NOT_READY")
    if calc.account_posture(account) != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_POSTURE_GATE")
    start = parse_iso8601((agreement or {}).get("cycle_start_utc"))
    if start is None:
        raise ApiError("ERR_COMMITMENT_CYCLE_NOT_STARTED")
    end = calc.agreement_cycle_end(agreement)
    now = DB.clock
    if end is None or now >= end or now < start:
        raise ApiError("ERR_COMMITMENT_CYCLE_NOT_STARTED")
    system["service_status"] = "INSTALLED"
    system["installed_at_utc"] = to_iso(DB.clock)
    system["site_readiness_review_id"] = review.get("id")
    touch(system)
    refresh_posture(account)
    return system


def system_commission(system, account, agreement):
    if system.get("service_status") != "INSTALLED":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    if not any(t.get("training_status") == "CREDENTIALED"
               for t in calc.training_records_of_account(account.get("id"))):
        raise ApiError("ERR_NO_CREDENTIALED_SURGEON")
    if calc.active_contract(system.get("id")) is None:
        raise ApiError("ERR_SERVICE_CONTRACT_REQUIRED")
    system["service_status"] = "IN_SERVICE"
    cycle = cycle_for_interval(system, agreement)
    if cycle is None:
        cycle = base_record({
            "robot_system_id": system.get("id"),
            "placement_agreement_id": (agreement or {}).get("id"),
            "cycle_start_utc": to_iso(DB.clock),
            "reporting_period_index": 0,
        })
        DB.utilization_cycles[cycle["id"]] = cycle
    system["current_utilization_cycle_id"] = cycle["id"]
    cycle["utilization_band"] = calc.utilization_band(cycle)
    touch(cycle)
    refresh_system(system)
    touch(system)
    refresh_posture(account)
    return system


def system_open_service_action(system, account):
    if system.get("service_status") != "IN_SERVICE":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    system["service_status"] = "SERVICE_ACTION_REQUIRED"
    touch(system)
    # HOP 1 — the posture recomputes to EXPANSION_BLOCKED.
    refresh_posture(account)
    # HOP 2 — every ACTIVE agreement on this system with NON_COMPLIANT
    # compliance is suspended.
    for agreement in DB.placement_agreements.values():
        if agreement.get("agreement_status") != "ACTIVE":
            continue
        if agreement.get("compliance_status") != "NON_COMPLIANT":
            continue
        if any(s.get("id") == system.get("id")
               for s in systems_of_agreement(agreement)):
            agreement["agreement_status"] = "SUSPENDED"
            touch(agreement)
    # HOP 2b — the CONTRACT_EXPIRED reclaim wave over this system.
    reclaim_dispatches([system], reason="CONTRACT_EXPIRED")
    refresh_system(system)
    refresh_posture(account)
    return system


def system_restore_service(system, account):
    if system.get("service_status") != "SERVICE_ACTION_REQUIRED":
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    for incident in calc.incidents_of_system(system.get("id")):
        if incident.get("request_status") != "RESOLVED":
            raise ApiError("ERR_SERVICE_ACTION_UNRESOLVED")
    contract = calc.active_contract(system.get("id"))
    if contract is None:
        raise ApiError("ERR_SERVICE_CONTRACT_REQUIRED")
    system["service_status"] = "IN_SERVICE"
    touch(system)
    refresh_system(system)
    refresh_posture(account)
    return system


def system_decommission(system, account):
    if system.get("service_status") not in ("IN_SERVICE", "INSTALLED"):
        raise ApiError("ERR_SYSTEM_STATUS_INVALID")
    for case in calc.cases_of_system(system.get("id")):
        if case.get("case_status") in ("SCHEDULED", "COMPLETED"):
            raise ApiError("ERR_SYSTEM_HAS_OPEN_CASES")
    system["service_status"] = "DECOMMISSIONED"
    touch(system)
    terminate_active_contracts([system])
    refresh_system(system)
    refresh_posture(account)
    return system


# ---------------------------------------------------------------------------
# PlacementAgreement state machine
# ---------------------------------------------------------------------------

def agreement_submit(agreement, account, review, config):
    if agreement.get("agreement_status") != "DRAFT":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    if review is None or review.get("readiness_status") != "PASSED":
        raise ApiError("ERR_READINESS_REVIEW_NOT_PASSED")
    if calc.account_posture(account) != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_POSTURE_GATE")
    arrangement = agreement.get("arrangement_type")
    if arrangement == "PURCHASE" and not int(agreement.get("placement_fee_cents") or 0):
        raise ApiError("ERR_AGREEMENT_TERMS_INCOMPLETE")
    if arrangement == "LEASE" and not int(agreement.get("lease_monthly_amount_cents") or 0):
        raise ApiError("ERR_AGREEMENT_TERMS_INCOMPLETE")
    if arrangement == "USAGE_BASED" and not int(agreement.get("usage_rate_basis_points") or 0):
        raise ApiError("ERR_AGREEMENT_TERMS_INCOMPLETE")
    cap = int(account.get("placement_cap") or 0)
    if cap >= 1:
        non_terminal = sum(1 for a in calc.agreements_of_account(account.get("id"))
                           if a.get("agreement_status") != "TERMINATED")
        if non_terminal > cap:
            raise ApiError("ERR_PLACEMENT_CAP_EXCEEDED")
    agreement["placement_fee_cents"] = calc.placement_fee(account, review, config)
    agreement["agreement_status"] = "PENDING_ACCEPTANCE"
    agreement["acceptance_expires_utc"] = to_iso(
        DB.clock + timedelta(days=calc.ACCEPTANCE_WINDOW_DAYS))
    touch(agreement)
    refresh_posture(account)
    return agreement


def agreement_accept(agreement, account, review, config):
    if agreement.get("agreement_status") != "PENDING_ACCEPTANCE":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    expires = parse_iso8601(agreement.get("acceptance_expires_utc"))
    if expires is not None and DB.clock >= expires:
        raise ApiError("ERR_ACCEPTANCE_WINDOW_EXPIRED")
    if calc.account_posture(account) != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_POSTURE_GATE")

    agreement["agreement_status"] = "ACTIVE"
    now = DB.clock
    agreement["activated_at_utc"] = to_iso(now)
    agreement["cycle_start_utc"] = to_iso(now)
    agreement["cycle_end_utc"] = to_iso(calc.agreement_cycle_end(agreement))

    # Synthesize the RobotSystem.
    serial = "SROB-%s" % agreement["id"].replace("-", "").upper()[:12]
    if any(s.get("serial_number") == serial for s in DB.robot_systems.values()):
        raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER")
    system = base_record({
        "hospital_account_id": account.get("id"),
        "system_configuration_id": agreement.get("system_configuration_id"),
        "placement_agreement_id": agreement.get("id"),
        "site_readiness_review_id": agreement.get("site_readiness_review_id"),
        "serial_number": serial,
        "service_status": "NOT_INSTALLED",
        "installed_software_release_index": 0,
        "current_utilization_cycle_id": None,
        "installed_at_utc": None,
    })
    DB.robot_systems[system["id"]] = system
    refresh_system(system)
    agreement["synthesized_system_id"] = system["id"]
    agreement["synthesized_system_version"] = 1

    # Synthesize the ServiceContract.
    contract = base_record({
        "robot_system_id": system["id"],
        "coverage_tier": "COMPREHENSIVE",
        "contract_start_utc": to_iso(now),
        "contract_months": 1,
        "contract_status": "ACTIVE",
    })
    DB.service_contracts[contract["id"]] = contract
    agreement["synthesized_service_contract_id"] = contract["id"]

    refresh_commitment(agreement)
    touch(agreement)
    refresh_posture(account)
    # CONTRACTED → ACTIVE happens automatically once the agreement is ACTIVE,
    # and the volume-discount ladder is re-evaluated AFTER that change: the
    # account now counts 1 toward idn_scale, so the net fee re-prices strictly
    # lower than the list fee written at submit (PRD §3.1.2).
    account_to_active(account)
    agreement["net_placement_fee_cents"] = calc.placement_fee(account, review, config)
    # PRD §3.1.3: "The agreement's version and the account's version both increment."
    touch(account)
    return agreement


def agreement_suspend(agreement, account):
    if agreement.get("agreement_status") != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    if agreement.get("compliance_status") != "NON_COMPLIANT":
        raise ApiError("ERR_AGREEMENT_NOT_SUSPENDABLE")
    agreement["agreement_status"] = "SUSPENDED"
    systems = systems_of_agreement(agreement)
    for system in systems:
        system["service_status"] = "SERVICE_ACTION_REQUIRED"
        touch(system)
    reclaim_dispatches(systems, reason="CONTRACT_EXPIRED")
    touch(agreement)
    refresh_account_and_systems(account)
    return agreement


def agreement_reinstate(agreement, account):
    if agreement.get("agreement_status") != "SUSPENDED":
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    systems = systems_of_agreement(agreement)
    for system in systems:
        for contract in calc.contracts_of_system(system.get("id")):
            if contract.get("contract_status") != "ACTIVE":
                continue
            end = calc.contract_end(contract)
            if end is None or not DB.clock < end:
                raise ApiError("ERR_CONTRACT_TEMPORALLY_INVALID")
    agreement["agreement_status"] = "ACTIVE"
    for system in systems:
        if system.get("service_status") == "SERVICE_ACTION_REQUIRED":
            system["service_status"] = "IN_SERVICE"
            touch(system)
    refresh_commitment(agreement)
    touch(agreement)
    refresh_account_and_systems(account)
    return agreement


def agreement_reject(agreement, account):
    status = agreement.get("agreement_status")
    if status not in ("DRAFT", "PENDING_ACCEPTANCE", "ACTIVE"):
        raise ApiError("ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE")
    agreement["agreement_status"] = "DRAFT"
    if status == "PENDING_ACCEPTANCE":
        agreement["acceptance_expires_utc"] = None
    if status == "ACTIVE":
        agreement["cycle_start_utc"] = None
        agreement["activated_at_utc"] = None
        agreement["cycle_end_utc"] = None
    touch(agreement)
    refresh_posture(account)
    return agreement


def agreement_terminate(agreement, account):
    if agreement.get("agreement_status") not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_AGREEMENT_NOT_TERMINABLE")
    agreement["agreement_status"] = "TERMINATED"
    systems = systems_of_agreement(agreement)
    cancel_non_terminal_cases(systems)      # hop 0
    decommission_systems(systems)           # HOP 1
    terminate_active_contracts(systems)     # HOP 2 (caused by hop 1)
    resolve_open_incidents(systems)         # HOP 3 (caused by hop 2)
    cancel_dispatches(systems)
    touch(agreement)
    refresh_account_and_systems(account)
    return agreement


def agreement_acceptance_expire(agreement, account):
    """PENDING_ACCEPTANCE → DRAFT when the clock reaches the window expiry."""
    if agreement.get("agreement_status") != "PENDING_ACCEPTANCE":
        return False
    expires = parse_iso8601(agreement.get("acceptance_expires_utc"))
    if expires is None or DB.clock < expires:
        return False
    agreement["agreement_status"] = "DRAFT"
    agreement["acceptance_expires_utc"] = None
    touch(agreement)
    refresh_posture(account)
    return True


# ---------------------------------------------------------------------------
# ServiceContract state machine
# ---------------------------------------------------------------------------

def contract_terminate(contract, account):
    if contract.get("contract_status") != "ACTIVE":
        raise ApiError("ERR_SERVICE_CONTRACT_NOT_ACTIVE")
    contract["contract_status"] = "TERMINATED"
    touch(contract)
    system = system_of(contract)
    if system is not None:
        for incident in calc.incidents_of_system(system.get("id")):
            if incident.get("request_status") in ("OPEN", "ACKNOWLEDGED"):
                incident["request_status"] = "RESOLVED"
                incident["resolved_at_utc"] = to_iso(DB.clock)
                touch(incident)
    refresh_posture(account)
    return contract


def contract_expire(contract):
    """Month-close expiry plus the CONTRACT_EXPIRED reclaim wave."""
    if contract.get("contract_status") != "ACTIVE":
        return False
    end = calc.contract_end(contract)
    if end is None or DB.clock < end:
        return False
    contract["contract_status"] = "EXPIRED"
    touch(contract)
    system = system_of(contract)
    if system is not None:
        reclaim_dispatches([system], reason="CONTRACT_EXPIRED")
    return True


# ---------------------------------------------------------------------------
# SurgeonTrainingRecord state machine
# ---------------------------------------------------------------------------

def record_complete_simulation(record, modules):
    if record.get("training_status") not in ("NOT_STARTED", "SIMULATION_INCOMPLETE"):
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    if modules is not None:
        record["simulation_modules_completed"] = int(modules)
    if not calc.simulation_ready(record):
        raise ApiError("ERR_SIMULATION_MODULES_INCOMPLETE")
    record["training_status"] = "SIMULATION_COMPLETE"
    touch(record)
    return record


def record_begin_proctoring(record, required):
    if record.get("training_status") != "SIMULATION_COMPLETE":
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    if required is not None:
        record["required_proctored_cases"] = int(required)
    if int(record.get("required_proctored_cases") or 0) < 1:
        raise ApiError("ERR_PROCTORING_REQUIREMENT_MISSING")
    record["training_status"] = "PROCTORING"
    touch(record)
    return record


def record_trigger_reevaluation(record):
    if record.get("training_status") != "CREDENTIALED":
        raise ApiError("ERR_TRAINING_STATUS_INVALID")
    expires = parse_iso8601(record.get("credential_expires_utc"))
    revoked = any(e.get("evidence_status") == "REVOKED"
                  for e in calc.evidence_of_record(record.get("id")))
    if not revoked and (expires is None or DB.clock < expires):
        raise ApiError("ERR_RECERTIFICATION_NOT_DUE")
    record["training_status"] = "PROCTORING"
    record["proctored_cases_completed"] = 0
    record["credential_expires_utc"] = None
    record["evidence_required_after_utc"] = None
    touch(record)
    return record


def evidence_expiry_sweep():
    """VALID → EXPIRING_SOON (within 30 days) / EXPIRED (clock >= expiry)."""
    now = DB.clock
    for evidence in list(DB.credentialing_evidence.values()):
        status = evidence.get("evidence_status")
        if status not in ("VALID", "EXPIRING_SOON"):
            continue
        expires = parse_iso8601(evidence.get("expires_utc"))
        if expires is None:
            continue
        if now >= expires:
            evidence["evidence_status"] = "EXPIRED"
            touch(evidence)
        elif status == "VALID" and expires - now <= timedelta(days=calc.EXPIRING_SOON_DAYS):
            evidence["evidence_status"] = "EXPIRING_SOON"
            touch(evidence)