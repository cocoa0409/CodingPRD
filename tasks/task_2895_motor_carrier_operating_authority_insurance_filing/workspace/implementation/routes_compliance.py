"""Revocation cure, safety-audit results and the periodic compliance sweep (PRD 3.7, 3.8)."""

from flask import Blueprint

import calc
import clock
import domain
import envelope
import helpers
import store
from errors import ApiError
from validation import Body, authenticate

bp = Blueprint("compliance", __name__)


@bp.post("/revocation-proceedings/<proceeding_id>/cure")
def cure_proceeding(proceeding_id):
    authenticate(("ComplianceOfficer",))
    proceeding = helpers.need_ref(store.PROCEEDINGS, proceeding_id)

    body = Body()
    policy_number = body.req_str("replacement_policy_number", min_len=1, max_len=64)

    if proceeding["status"] != "NOTICE_ISSUED":
        raise ApiError("ERR_PROCEEDING_NOT_OPEN")

    now = clock.now()
    if now > proceeding["cure_deadline_at"]:
        raise ApiError("ERR_PROCEEDING_NOT_OPEN",
                       "The cure deadline for this proceeding has passed.")

    authority = store.AUTHORITIES.get(proceeding["authority_id"])
    replacement = None
    if authority is not None:
        for filing in domain.active_filings(authority["id"]):
            if filing["policy_number"] != policy_number:
                continue
            if not domain.filing_is_current(filing):
                continue
            replacement = filing
            break
    if replacement is None:
        raise ApiError("ERR_INSURANCE_BELOW_MINIMUM",
                       "No active replacement policy covering the current logical time is on file.")
    minimum = domain.required_minimum_for_type(authority, replacement["filing_type"])
    if replacement["coverage_limit_cents"] < minimum:
        raise ApiError("ERR_INSURANCE_BELOW_MINIMUM")

    proceeding["status"] = "CURED"
    proceeding["cured_at"] = now
    proceeding["replacement_policy_number"] = policy_number
    domain.touch(proceeding)

    if authority["insurance_status"] != "FILED":
        authority["insurance_status"] = "FILED"
        domain.touch(authority)
    domain.try_restore(authority)
    return helpers.one(proceeding)


@bp.post("/safety-audits/<audit_id>/record-result")
def record_audit_result(audit_id):
    authenticate(("ComplianceOfficer",))
    audit = helpers.need_ref(store.AUDITS, audit_id)

    body = Body()
    oos = body.req_number("audited_oos_rate_pct", lo=0, hi=100, max_dp=2)
    driver_violations = body.req_int("audited_driver_violation_count", min_v=0)
    vehicle_defects = body.req_int("audited_vehicle_defect_count", min_v=0)
    acute = body.req_int("acute_violation_count", min_v=0)

    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_AUDIT_INVALID_STATE")

    now = clock.now()
    if now < audit["audit_window_opens_at"] or now > audit["audit_deadline_at"]:
        raise ApiError("ERR_AUDIT_INVALID_STATE",
                       "The current logical time is outside this audit's window.")

    score = calc.audited_risk_score(oos, driver_violations, vehicle_defects, acute)
    outcome = calc.safety_audit_outcome(score, acute)

    audit["result_recorded_at"] = now
    audit["audited_oos_rate_pct"] = oos
    audit["audited_driver_violation_count"] = driver_violations
    audit["audited_vehicle_defect_count"] = vehicle_defects
    audit["acute_violation_count"] = acute
    audit["audit_score"] = score
    audit["status"] = outcome
    domain.touch(audit)

    carrier = store.CARRIERS.get(audit["carrier_id"])
    if carrier is not None:
        carrier["audited_oos_rate_pct"] = oos
        carrier["compliance_risk_score"] = score
        carrier["compliance_risk_variant"] = "AUDITED"
        if outcome == "PASSED":
            carrier["entrant_status"] = "PERMANENT"
        domain.touch(carrier)

        pending = [a for a in store.authorities_of_carrier(carrier["id"])
                   if a["new_entrant_audit_status"] == "PENDING"]
        for authority in pending:
            authority["new_entrant_audit_status"] = outcome
            domain.touch(authority)
        if outcome == "FAILED":
            for authority in pending:
                if authority["authority_status"] != "ACTIVE":
                    continue
                domain.open_proceeding(authority, "SAFETY_AUDIT_FAILURE")
                domain.suspend(authority, "SAFETY_AUDIT_FAILURE")
    return helpers.one(audit)


@bp.post("/compliance-sweeps")
def compliance_sweep():
    authenticate(("ComplianceOfficer", "RegistryAdmin"))
    now = clock.now()
    audits_missed = 0
    carriers_flagged = 0
    authorities_revoked = 0
    contracts_terminated = 0

    # step one: audit windows that expired
    for audit in store.all_of(store.AUDITS):
        if audit["status"] != "SCHEDULED" or not audit["audit_deadline_at"] < now:
            continue
        audit["status"] = "MISSED"
        domain.touch(audit)
        audits_missed += 1
        pending = [a for a in store.authorities_of_carrier(audit["carrier_id"])
                   if a["new_entrant_audit_status"] == "PENDING"]
        for authority in pending:
            authority["new_entrant_audit_status"] = "MISSED"
            domain.touch(authority)
        for authority in pending:
            if authority["authority_status"] != "ACTIVE":
                continue
            domain.open_proceeding(authority, "AUDIT_WINDOW_MISSED")
            domain.suspend(authority, "AUDIT_WINDOW_MISSED")

    # step two: registration delinquency
    for carrier in store.all_of(store.CARRIERS):
        if carrier["biennial_delinquent"]:
            continue
        if not carrier["biennial_update_due_at"] < now:
            continue
        carrier["biennial_delinquent"] = True
        domain.touch(carrier)
        carriers_flagged += 1

    # step three: expired cure deadlines
    for proceeding in store.all_of(store.PROCEEDINGS):
        if proceeding["status"] != "NOTICE_ISSUED":
            continue
        if not proceeding["notice_issued_at"] < now:
            continue
        if not proceeding["cure_deadline_at"] < now:
            continue
        proceeding["status"] = "REVOKED"
        proceeding["revoked_at"] = now
        domain.touch(proceeding)
        authorities_revoked += 1
        authority = store.AUTHORITIES.get(proceeding["authority_id"])
        if authority is not None and authority["authority_status"] not in ("REVOKED", "RESCINDED"):
            contracts_terminated += domain.terminate(authority)

    return envelope.obj({
        "swept_at": clock.fmt(now),
        "audits_missed_count": audits_missed,
        "carriers_flagged_delinquent_count": carriers_flagged,
        "authorities_revoked_count": authorities_revoked,
        "contracts_terminated_count": contracts_terminated,
    })
