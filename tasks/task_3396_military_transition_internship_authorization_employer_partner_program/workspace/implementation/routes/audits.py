from flask import Blueprint

import constants
import db
import services
from errors import fail
from middleware import auth_context, require_role, body, locked, req_str
from response import success
from util import serialize

bp = Blueprint("audits", __name__)


def _validate_findings(data):
    raw = data.get("findings")
    if raw is None:
        return []
    if not isinstance(raw, list):
        fail("ERR_VALIDATION", "findings must be an array")
    normalized = []
    for f in raw:
        if not isinstance(f, dict):
            fail("ERR_VALIDATION", "each finding must be an object")
        code = f.get("finding_code")
        if not isinstance(code, str) or code not in constants.FINDING_CODES:
            fail("ERR_VALIDATION", "finding_code must be one of %s" % ", ".join(sorted(constants.FINDING_CODES)))
        severity = f.get("severity")
        if not isinstance(severity, str) or severity not in constants.SEVERITIES:
            fail("ERR_VALIDATION", "severity must be one of MINOR, MAJOR, CRITICAL")
        note = f.get("note")
        if note is not None and not isinstance(note, str):
            fail("ERR_VALIDATION", "note must be a string")
        normalized.append({"finding_code": code, "severity": severity, "note": note})
    return normalized


@bp.route("/compliance-audits", methods=["POST"])
@locked
def create_audit():
    uid, role = auth_context()
    data = body()
    employer_id = req_str(data, "employer_id")
    require_role(role, ["ProgramOffice"])
    employer = db.store.employers.get(employer_id)
    if employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer %s does not exist" % employer_id)
    ent = db.base_entity()
    ent.update(
        {
            "employer_id": employer_id,
            "status": "OPEN",
            "opened_at": db.now(),
            "findings": [],
            "compliance_score": None,
            "closed_at": None,
        }
    )
    db.store.audits[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/compliance-audits/<aid>/close", methods=["POST"])
@locked
def close_audit(aid):
    uid, role = auth_context()
    data = body()
    findings = _validate_findings(data)
    require_role(role, ["ProgramOffice"])
    audit = db.store.audits.get(aid)
    if audit is None:
        fail("ERR_AUDIT_NOT_FOUND", "ComplianceAudit %s does not exist" % aid)
    if audit["status"] != "OPEN":
        fail("ERR_AUDIT_ALREADY_CLOSED", "Audit is not OPEN")
    score = services.compute_compliance_score(findings)
    employer = db.store.employers.get(audit["employer_id"])
    audit["findings"] = findings
    audit["compliance_score"] = score
    audit["closed_at"] = db.now()
    if score >= constants.SANCTION_SCORE_THRESHOLD:
        audit["status"] = "CLOSED_CLEARED"
        if employer is not None:
            employer["pending_violations"] = 0
            employer["last_cleared_audit_at"] = db.now()
            employer["last_compliance_score"] = score
            services.touch(employer)
    else:
        audit["status"] = "CLOSED_SANCTIONED"
        if employer is not None:
            employer["last_compliance_score"] = score
            if employer["authorization_status"] != "REVOKED":
                employer["authorization_status"] = "REVOKED"
                services.cascade_employer_revoked(employer)
            services.touch(employer)
    services.touch(audit)
    return success(serialize(audit))
