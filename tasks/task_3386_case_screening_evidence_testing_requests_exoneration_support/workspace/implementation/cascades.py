"""Cascade helpers (PRD 2.6).

Chain A: records response DESTROYED reveal -> EvidenceItem location ->
Case.destroyed_evidence_count + evidence_posture -> EVIDENCE_PRESERVATION
PolicyInitiative pattern counts.
Chain B: database-comparison HIT -> Case.exculpatory_evidence_flag ->
evidence_posture (EXCULPATORY precedence) -> DATABASE_ACCESS pattern counts.
Plus the records-denial (RECORDS_TRANSPARENCY) and claim-denial
(COMPENSATION_REFORM) pattern re-derivations.

Touch discipline: an entity's version is bumped and updated_at refreshed only
when one of its stored fields actually changes value; the destruction cascade
always changes the case (destroyed_evidence_count += 1) so it always bumps.
"""

import db
from calculations import derive_evidence_posture, policy_pattern_count
from db import touch


def case_jurisdiction_id(case):
    ir = db.intake_requests.get(case["intake_request_id"])
    return ir["jurisdiction_id"] if ir else None


def refresh_case_posture(case):
    """Re-derive evidence_posture; returns True when it changed."""
    new = derive_evidence_posture(case)
    if new != case["evidence_posture"]:
        case["evidence_posture"] = new
        return True
    return False


def refresh_case_posture_touch(case):
    if refresh_case_posture(case):
        touch(case)


def rederive_policy_counts(topic, jurisdiction_id):
    """Re-derive pattern_case_count for every initiative of the given topic in
    the given jurisdiction; bump version only when the count changes."""
    if jurisdiction_id is None:
        return
    for pi in db.policy_initiatives.values():
        if pi["jurisdiction_id"] == jurisdiction_id and pi["topic"] == topic:
            new = policy_pattern_count(topic, jurisdiction_id)
            if new != pi["pattern_case_count"]:
                pi["pattern_case_count"] = new
                touch(pi)


def apply_destruction_cascade(item):
    """The item has just entered REPORTED_DESTROYED via a records response."""
    case = db.cases[item["case_id"]]
    case["destroyed_evidence_count"] += 1
    refresh_case_posture(case)
    touch(case)
    rederive_policy_counts("EVIDENCE_PRESERVATION", case_jurisdiction_id(case))


def apply_hit_cascade(analysis):
    """A database comparison returned HIT on this analysis."""
    item = db.evidence_items[analysis["evidence_item_id"]]
    case = db.cases[item["case_id"]]
    changed = False
    if not case["exculpatory_evidence_flag"]:
        case["exculpatory_evidence_flag"] = True
        changed = True
    if refresh_case_posture(case):
        changed = True
    if changed:
        touch(case)
    rederive_policy_counts("DATABASE_ACCESS", case_jurisdiction_id(case))


def apply_records_denial_cascade(records_request):
    case = db.cases.get(records_request["case_id"])
    if case is not None:
        rederive_policy_counts("RECORDS_TRANSPARENCY", case_jurisdiction_id(case))


def apply_claim_denial_cascade(claim):
    case = db.cases.get(claim["case_id"])
    if case is not None:
        rederive_policy_counts("COMPENSATION_REFORM", case_jurisdiction_id(case))


def apply_exoneration_cascade(case, stamp):
    """LegalPetition RECORD_DECISION GRANTED with vacates_conviction=true."""
    case["status"] = "EXONERATED"
    case["exoneration_date"] = stamp
    case["release_readiness"] = "PLANNING"
    case["contact_interval_days"] = 14
    touch(case)
