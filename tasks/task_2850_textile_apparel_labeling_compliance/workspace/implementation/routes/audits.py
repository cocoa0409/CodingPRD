"""Compliance audits, mislabeled-inventory findings and the audit rollup (PRD 3.9)."""
from flask import Blueprint, request

import calc
import services
from auth import require_roles
from envelope import created, listing, ok
from errors import fail
from serializers import audit_json, finding_json
from store import create_row, db, ordered, touch
from util import parse_second_instant
from validate import (body, find_audit, find_brand, find_finding, find_label_spec,
                      find_style, present, req_enum, req_int, req_string)

bp = Blueprint("audits", __name__)

SCOPES = ("STYLE_DOSSIER", "MARKET_LABELING", "IMPORT_MARKING")
FINDING_CODES = ("FIBER_CONTENT_MISSTATED", "ORIGIN_MISSTATED", "CARE_UNSUBSTANTIATED",
                 "IDENTITY_MISSING", "PLACEMENT_NON_PERMANENT", "HANGTAG_INCONSISTENT")
LIVE_FINDING_STATES = ("OPEN", "REMEDIATED")
READ_ROLES = ("ComplianceAdmin", "BrandAdmin", "Auditor")


def _party_of(audit):
    return services.brand_of_record_row(audit["brand_id"])


@bp.post("/labeling/compliance-audits")
def open_audit():
    require_roles("Auditor", "ComplianceAdmin")
    payload = body()
    if present(payload, "brand_id"):                                 # ladder 5
        find_brand(payload["brand_id"])
    brand_id = req_string(payload, "brand_id")                        # ladder 6
    scope = req_enum(payload, "scope", SCOPES)
    window_from = parse_second_instant(payload.get("audit_window_from"))
    window_to = parse_second_instant(payload.get("audit_window_to"))
    if not (window_to > window_from):                                # ladder 20
        fail("ERR_INVALID_EFFECTIVE_WINDOW",
             "audit_window_to must be strictly after audit_window_from.")
    row = create_row(db.compliance_audits, {
        "brand_id": brand_id,
        "scope": scope,
        "audit_window_from": window_from,
        "audit_window_to": window_to,
        "state": "OPEN",
        # All three counters are derived from the child findings and are never
        # supplied by the caller (PRD 3.9).
        "open_finding_count": 0,
        "critical_finding_count": 0,
        "units_in_scope": 0,
        "closed_at": None,
    })
    return created(audit_json(row))


@bp.post("/labeling/compliance-audits/<aid>/findings")
def raise_finding(aid):
    require_roles("Auditor", "ComplianceAdmin")
    audit = find_audit(aid)                                          # ladder 3
    payload = body()
    if present(payload, "style_id"):                                 # ladder 5
        find_style(payload["style_id"])
    style_id = req_string(payload, "style_id")                        # ladder 6
    finding_code = req_enum(payload, "finding_code", FINDING_CODES)
    units_affected = req_int(payload, "units_affected", minimum=1)
    if audit["state"] == "CLOSED":                                   # ladder 9
        fail("ERR_AUDIT_STATE_INVALID", "A closed audit cannot take a finding.")
    for other in calc.findings_of(audit["id"]):                      # ladder 26
        if (other["style_id"] == style_id and other["finding_code"] == finding_code
                and other["state"] in LIVE_FINDING_STATES):
            fail("ERR_DUPLICATE_OPEN_FINDING",
                 "That style already carries a live finding of that code in this audit.")
    finding = create_row(db.audit_findings, {
        "audit_id": audit["id"],
        "style_id": style_id,
        "corrective_label_spec_id": None,
        "finding_code": finding_code,
        # Severity is derived, never supplied (PRD 3.9).
        "severity": calc.finding_severity(finding_code, units_affected),
        "units_affected": units_affected,
        "units_relabeled": 0,
        "units_destroyed": 0,
        "units_released": 0,
        "state": "OPEN",
        "disposition_recorded_at": None,
        "verified_at": None,
        "reopen_reason": None,
    })
    if audit["state"] == "OPEN":
        audit["state"] = "IN_REVIEW"
    calc.audit_rollup(audit)
    touch(audit)
    return created(finding_json(finding))


@bp.post("/labeling/audit-findings/<fid>/disposition")
def record_disposition(fid):
    require_roles("LabelingSpecialist", "ComplianceAdmin")
    finding = find_finding(fid)                                      # ladder 3
    payload = body()
    spec = None                                                      # ladder 5
    if present(payload, "corrective_label_spec_id"):
        spec = find_label_spec(payload["corrective_label_spec_id"])
    relabeled = req_int(payload, "units_relabeled", minimum=0)        # ladder 6
    destroyed = req_int(payload, "units_destroyed", minimum=0)
    released = req_int(payload, "units_released", minimum=0)
    if finding["state"] != "OPEN":                                   # ladder 9
        fail("ERR_FINDING_STATE_INVALID", "Only an open finding may take a disposition.")
    if relabeled > 0:                                                # ladder 16
        if spec is None:
            fail("ERR_REFERENCE_NOT_ELIGIBLE",
                 "A positive relabeled count requires a corrective label reference.")
        if (spec["artifact_type"] != "PERMANENT_LABEL"
                or spec["style_id"] != finding["style_id"]
                or spec["state"] != "PUBLISHED"):
            fail("ERR_REFERENCE_NOT_ELIGIBLE",
                 "The corrective label must be a published permanent label of the same style.")
    elif spec is not None:
        fail("ERR_REFERENCE_NOT_ELIGIBLE",
             "A corrective label reference is only permitted with a positive relabeled count.")
    if relabeled + destroyed + released != finding["units_affected"]:  # ladder 30
        fail("ERR_DISPOSITION_INCOMPLETE",
             "The disposition buckets must sum to exactly units_affected.")
    finding["units_relabeled"] = relabeled
    finding["units_destroyed"] = destroyed
    finding["units_released"] = released
    finding["corrective_label_spec_id"] = spec["id"] if spec is not None else None
    finding["disposition_recorded_at"] = db.now()
    finding["state"] = "REMEDIATED"
    touch(finding)
    audit = db.compliance_audits.get(finding["audit_id"])
    if audit is not None:
        calc.audit_rollup(audit)
        touch(audit)
    return ok(finding_json(finding))


@bp.post("/labeling/audit-findings/<fid>/verify")
def verify_finding(fid):
    require_roles("Auditor")
    finding = find_finding(fid)                                      # ladder 3
    if finding["state"] != "REMEDIATED":                             # ladder 9
        fail("ERR_FINDING_STATE_INVALID", "Only a remediated finding may be verified.")
    # Hop 1: the finding closes.
    finding["verified_at"] = db.now()
    finding["state"] = "CLOSED"
    touch(finding)
    audit = db.compliance_audits.get(finding["audit_id"])
    if audit is not None:
        # Hop 2: the parent audit re-derives its counters.
        calc.audit_rollup(audit)
        touch(audit)
        # Hop 3: the party's posture is recomputed (it is derived on read).
        party = _party_of(audit)
        if party is not None:
            touch(party)
    return ok(finding_json(finding))


@bp.post("/labeling/audit-findings/<fid>/reopen")
def reopen_finding(fid):
    require_roles("Auditor", "ComplianceAdmin")
    finding = find_finding(fid)                                      # ladder 3
    payload = body()
    reason = req_string(payload, "reopen_reason", min_len=1)           # ladder 6
    audit = db.compliance_audits.get(finding["audit_id"])
    if finding["state"] != "CLOSED":                                 # ladder 9
        fail("ERR_FINDING_STATE_INVALID", "Only a closed finding may be reopened.")
    if audit is not None and audit["state"] == "CLOSED":
        fail("ERR_AUDIT_STATE_INVALID", "The parent audit is closed.")
    finding["state"] = "OPEN"
    finding["reopen_reason"] = reason
    finding["verified_at"] = None
    finding["disposition_recorded_at"] = None
    finding["corrective_label_spec_id"] = None
    # Units are conserved: resetting the buckets restores units_unresolved to
    # the full affected total and leaves units_in_scope untouched.
    finding["units_relabeled"] = 0
    finding["units_destroyed"] = 0
    finding["units_released"] = 0
    touch(finding)
    if audit is not None:
        calc.audit_rollup(audit)
        touch(audit)
        party = _party_of(audit)
        if party is not None:
            touch(party)
    return ok(finding_json(finding))


@bp.post("/labeling/compliance-audits/<aid>/close")
def close_audit(aid):
    require_roles("Auditor", "ComplianceAdmin")
    audit = find_audit(aid)                                          # ladder 3
    has_findings = len(calc.findings_of(audit["id"])) > 0
    allowed = (audit["state"] == "PENDING_CLOSURE"
               or (audit["state"] == "OPEN" and not has_findings))
    if not allowed:                                                  # ladder 9
        fail("ERR_AUDIT_STATE_INVALID",
             "The audit cannot be closed from its current state.")
    audit["closed_at"] = db.now()
    audit["state"] = "CLOSED"
    touch(audit)
    party = _party_of(audit)
    if party is not None:
        touch(party)
    return ok(audit_json(audit))


@bp.get("/labeling/compliance-audits/<aid>")
def read_audit(aid):
    require_roles(*READ_ROLES)
    return ok(audit_json(find_audit(aid)))


@bp.get("/labeling/compliance-audits")
def list_audits():
    require_roles(*READ_ROLES)
    rows = ordered(list(db.compliance_audits.values()))
    args = request.args
    for field in ("brand_id", "state", "scope"):
        if args.get(field) is not None:
            rows = [r for r in rows if r[field] == args.get(field)]
    return listing(rows, audit_json)


@bp.get("/labeling/audit-findings/<fid>")
def read_finding(fid):
    require_roles(*READ_ROLES)
    return ok(finding_json(find_finding(fid)))


@bp.get("/labeling/audit-findings")
def list_findings():
    require_roles(*READ_ROLES)
    rows = ordered(list(db.audit_findings.values()))
    args = request.args
    for field in ("audit_id", "style_id", "corrective_label_spec_id", "state",
                  "severity", "finding_code"):
        if args.get(field) is not None:
            rows = [r for r in rows if r[field] == args.get(field)]
    return listing(rows, finding_json)
