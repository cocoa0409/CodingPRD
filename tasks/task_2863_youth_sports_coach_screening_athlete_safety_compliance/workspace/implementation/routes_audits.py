"""Club compliance audits, findings, decisions and sanctions (PRD section 3.9)."""

from decimal import Decimal

from flask import Blueprint, g, request

import auth
import calc
import clock
import derive
import envelope
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("audits", __name__)

AUDIT_STATUSES = ("SAMPLED", "FINDINGS_ISSUED", "CLOSED_COMPLIANT", "CLOSED_SANCTIONED")
SCORE_VARIANTS = ("SELF_ATTESTED", "REGISTRY_VERIFIED")
FINDING_CODES = ("SCREENING_LAPSED", "TRAINING_LAPSED", "UNSCREENED_CONTACT",
                 "LODGING_POLICY_BREACH", "ELECTRONIC_COMM_BREACH", "FAILURE_TO_REPORT",
                 "RECORDS_INCOMPLETE")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
FINDING_STATUSES = ("OPEN", "REMEDIATED", "WAIVED")
DECISIONS = ("REMEDIATION_SUBMITTED", "REMEDIATION_REJECTED", "WAIVED")


# --------------------------------------------------------------------- reads --
@bp.get("/club-audits")
@auth.endpoint("NgbAdmin", "ComplianceAuditor", "SafeSportOfficer")
def list_audits():
    args = request.args
    validate.query_enum(args, "status", AUDIT_STATUSES)
    validate.query_enum(args, "score_variant", SCORE_VARIANTS)
    rows = [a for a in store.CLUB_AUDITS.values()
            if pagelib.match(a, args, "club_id")
            and pagelib.match(a, args, "status")
            and pagelib.match(a, args, "score_variant")]
    return pagelib.page(store.ordered(rows), serialize.club_audit, args)


@bp.get("/club-audits/<club_audit_id>")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def read_audit(club_audit_id):
    row = auth.club_audit(club_audit_id)
    auth.scope(row["club_id"])
    return envelope.ok(serialize.club_audit(row))


@bp.get("/audit-findings")
@auth.endpoint("NgbAdmin", "ComplianceAuditor", "ClubAdministrator")
def list_findings():
    args = request.args
    validate.query_enum(args, "status", FINDING_STATUSES)
    validate.query_enum(args, "severity", SEVERITIES)
    rows = [f for f in store.AUDIT_FINDINGS.values()
            if pagelib.match(f, args, "audit_id")
            and pagelib.match(f, args, "member_id")
            and pagelib.match(f, args, "status")
            and pagelib.match(f, args, "severity")]
    return pagelib.page(store.ordered(rows), serialize.audit_finding, args)


@bp.get("/audit-findings/<audit_finding_id>")
@auth.endpoint("NgbAdmin", "ComplianceAuditor", "ClubAdministrator")
def read_finding(audit_finding_id):
    row = auth.audit_finding(audit_finding_id)
    auth.scope_finding(row)
    return envelope.ok(serialize.audit_finding(row))


# -------------------------------------------------------------------- writes --
AUDIT_SPEC = {
    "club_id": validate.string(min_len=1),
    "audit_period_start": validate.instant(),
    "audit_period_end": validate.instant(),
    "score_variant": validate.enum(SCORE_VARIANTS),
    "sampled_member_ids": validate.array(validate.string(min_len=1), min_items=0, max_items=50,
                                         unique=True),
}


@bp.post("/club-audits")
@auth.endpoint("ComplianceAuditor")
def open_audit():
    data = validate.body(auth.payload(), AUDIT_SPEC)
    if data["audit_period_end"] <= data["audit_period_start"]:
        validate.bad("audit_period_end must be strictly after audit_period_start")
    club = auth.club(data["club_id"])
    sampled = []
    for member_id in data["sampled_member_ids"]:
        sampled.append(auth.member(member_id))
    for member in sampled:
        if member["club_id"] != club["id"]:
            fail("ERR_CLUB_SCOPE_VIOLATION",
                 "member %s is not chartered by the audited club" % member["id"])
    row = store.new_row(
        club_id=club["id"],
        audit_period_start=data["audit_period_start"],
        audit_period_end=data["audit_period_end"],
        score_variant=data["score_variant"],
        sampled_member_ids=list(data["sampled_member_ids"]),
        sampled_member_count=len(data["sampled_member_ids"]),
        compliant_member_count=None,
        denominator_count=None,
        compliance_score=None,
        finding_total_count=0,
        open_finding_count=0,
        remediated_finding_count=0,
        waived_finding_count=0,
        sanction_fine_cents=None,
        status="SAMPLED",
        finalized_at=None,
        closed_at=None,
        resolution=None,
    )
    store.CLUB_AUDITS[row["id"]] = row
    return envelope.created(serialize.club_audit(row))


FINDING_SPEC = {
    "finding_code": validate.enum(FINDING_CODES),
    "severity": validate.enum(SEVERITIES),
    "member_id": validate.string(required=False, min_len=1),
    "is_repeat": validate.boolean(required=False, default=False),
}


@bp.post("/club-audits/<club_audit_id>/findings")
@auth.endpoint("ComplianceAuditor")
def write_finding(club_audit_id):
    audit = auth.club_audit(club_audit_id)
    data = validate.body(auth.payload(), FINDING_SPEC)
    member = None
    if data["member_id"] is not None:
        member = auth.member(data["member_id"])
        if member["id"] not in audit["sampled_member_ids"]:
            fail("ERR_CLUB_SCOPE_VIOLATION",
                 "member %s is not part of this audit's sample" % member["id"])
    if audit["status"] != "SAMPLED":
        fail("ERR_AUDIT_INVALID_STATE", "findings may only be written while the audit is SAMPLED")
    row = store.new_row(
        audit_id=audit["id"],
        member_id=None if member is None else member["id"],
        finding_code=data["finding_code"],
        severity=data["severity"],
        is_repeat=data["is_repeat"],
        status="OPEN",
        fine_cents=None,
        evidence_note=None,
        decision_note=None,
    )
    store.AUDIT_FINDINGS[row["id"]] = row
    derive.recompute_audit(audit)
    derive.recompute_all()
    return envelope.created(serialize.audit_finding(row))


def _is_compliant(member):
    return (member["screening_status"] == "CLEARED"
            and member["training_status"] == "CURRENT"
            and member["membership_status"] == "ACTIVE"
            and not derive.has_measure(member["id"], ("ACTIVE", "PERMANENT")))


def _denominator(audit, club):
    if audit["score_variant"] == "SELF_ATTESTED":
        return club["roster_size_attested"]
    return len([a for a in store.coach_assignments_of_club(club["id"])
                if a["status"] in ("PENDING", "ACTIVE")])


@bp.post("/club-audits/<club_audit_id>/finalize")
@auth.endpoint("ComplianceAuditor")
def finalize_audit(club_audit_id):
    audit = auth.club_audit(club_audit_id)
    validate.body(auth.payload(), {})
    club = store.CLUBS[audit["club_id"]]
    if audit["status"] != "SAMPLED":
        fail("ERR_AUDIT_INVALID_STATE", "only a SAMPLED audit may be finalized")

    compliant = 0
    for member_id in audit["sampled_member_ids"]:
        member = store.MEMBERS.get(member_id)
        if member is not None and _is_compliant(member):
            compliant += 1
    denominator = _denominator(audit, club)
    score = calc.club_compliance_score(audit["sampled_member_count"], compliant, denominator)
    audit["compliant_member_count"] = compliant
    audit["denominator_count"] = denominator
    audit["compliance_score"] = score
    audit["status"] = "FINDINGS_ISSUED"
    audit["finalized_at"] = clock.now()
    store.bump(audit)
    club["compliance_score"] = score
    derive.recompute_audit(audit)
    derive.recompute_all()
    return envelope.ok(serialize.club_audit(audit))


DECISION_SPEC = {
    "decision": validate.enum(DECISIONS),
    "note": validate.string(min_len=1, max_len=4000),
}

REQUIRED_FINDING_STATE = {
    "REMEDIATION_SUBMITTED": "OPEN",
    "REMEDIATION_REJECTED": "REMEDIATED",
    "WAIVED": "OPEN",
}
ALLOWED_BY_ROLE = {
    "ClubAdministrator": ("REMEDIATION_SUBMITTED",),
    "ComplianceAuditor": ("REMEDIATION_REJECTED", "WAIVED"),
}


@bp.post("/audit-findings/<audit_finding_id>/decision")
@auth.endpoint("ClubAdministrator", "ComplianceAuditor")
def decide_finding(audit_finding_id):
    finding = auth.audit_finding(audit_finding_id)
    auth.scope_finding(finding)
    data = validate.body(auth.payload(), DECISION_SPEC)
    audit = store.CLUB_AUDITS[finding["audit_id"]]
    decision = data["decision"]
    if finding["status"] != REQUIRED_FINDING_STATE[decision]:
        fail("ERR_FINDING_INVALID_STATE",
             "decision %s is not available from status %s" % (decision, finding["status"]))
    if audit["status"] != "FINDINGS_ISSUED":
        fail("ERR_AUDIT_INVALID_STATE", "the audit is not in status FINDINGS_ISSUED")
    if decision not in ALLOWED_BY_ROLE.get(g.role, ()):
        fail("ERR_DECISION_ROLE_MISMATCH", "role %s may not record decision %s" % (g.role, decision))

    if decision == "REMEDIATION_SUBMITTED":
        finding["status"] = "REMEDIATED"
        finding["evidence_note"] = data["note"]
    elif decision == "REMEDIATION_REJECTED":
        finding["status"] = "OPEN"
        finding["decision_note"] = data["note"]
    else:
        finding["status"] = "WAIVED"
        finding["decision_note"] = data["note"]
    store.bump(finding)
    derive.recompute_audit(audit)
    derive.recompute_all()
    return envelope.ok(serialize.audit_finding(finding))


@bp.post("/club-audits/<club_audit_id>/close")
@auth.endpoint("ComplianceAuditor")
def close_audit(club_audit_id):
    audit = auth.club_audit(club_audit_id)
    data = validate.body(auth.payload(),
                         {"resolution": validate.enum(("CLOSE_COMPLIANT", "SANCTION"))})
    club = store.CLUBS[audit["club_id"]]
    if audit["status"] != "FINDINGS_ISSUED":
        fail("ERR_AUDIT_INVALID_STATE", "only a finalized audit may be closed")
    score = audit["compliance_score"]
    passing = (score is not None and Decimal(str(score)) >= calc.COMPLIANCE_PASS_SCORE)
    if data["resolution"] == "CLOSE_COMPLIANT":
        if not passing or audit["open_finding_count"] != 0:
            fail("ERR_AUDIT_INVALID_STATE",
                 "a clean closure requires a passing score and no open finding")
    else:
        if passing and audit["open_finding_count"] == 0:
            fail("ERR_AUDIT_INVALID_STATE",
                 "a sanction requires a failing score or at least one open finding")

    audit["resolution"] = data["resolution"]
    audit["closed_at"] = clock.now()
    if data["resolution"] == "CLOSE_COMPLIANT":
        audit["status"] = "CLOSED_COMPLIANT"
        audit["sanction_fine_cents"] = 0
        store.bump(audit)
        club["sanction_status"] = "NONE"
    else:
        factor = calc.shortfall_factor(audit["compliance_score"])
        total = 0
        for finding in store.ordered(store.findings_of_audit(audit["id"])):
            if finding["status"] != "OPEN":
                continue
            fine = calc.finding_fine_cents(finding["severity"], finding["is_repeat"], factor)
            finding["fine_cents"] = fine
            store.bump(finding)
            total += fine
        audit["status"] = "CLOSED_SANCTIONED"
        audit["sanction_fine_cents"] = total
        store.bump(audit)
        club["sanction_status"] = "SUSPENDED"
        for placement in store.coach_assignments_of_club(club["id"]):
            if placement["status"] in ("PENDING", "ACTIVE"):
                placement["status"] = "TERMINATED"
                placement["suspended_reason"] = "CLUB_SANCTION"
                store.bump(placement)
    derive.recompute_audit(audit)
    derive.recompute_all()
    return envelope.ok(serialize.club_audit(audit))
