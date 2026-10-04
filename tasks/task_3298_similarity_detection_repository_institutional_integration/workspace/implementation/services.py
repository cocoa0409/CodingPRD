"""Business logic: cascades, calculations, state machine helpers."""
import uuid
from decimal import Decimal, ROUND_HALF_UP

from store import DB, now_logical, fmt_iso, parse_iso

REGIONS = {"EU", "US", "APAC"}
PROVIDERS = {"CANVAS", "BLACKBOARD", "MOODLE", "CUSTOM_API"}
PARTICIPATION = {"GLOBAL_SHARED", "INSTITUTION_ONLY", "OPT_OUT"}
CONSENT_ENFORCEMENT = {"STRICT", "LENIENT"}
REPO_OPTIONS = {"STORE_AND_COMPARE", "COMPARE_ONLY"}
REPORT_VISIBILITY = {"HIDDEN", "RELEASED"}
SOURCE_TYPES = {"INTERNET", "PUBLICATION", "STUDENT_REPOSITORY"}
MANUAL_SOURCE_TYPES = {"INTERNET", "PUBLICATION"}
MATCH_CATEGORIES = {"DIRECT_QUOTE", "PARAPHRASE", "BIBLIOGRAPHY_ENTRY", "BOILERPLATE"}
INTERPRETATIONS = {"NOT_MISCONDUCT", "POSSIBLE_MISCONDUCT", "NEEDS_REVIEW"}
APPLIES_TO = {"SUBMISSIONS", "REPORTS", "BOTH"}
CONSENT_ACTIONS = {"GRANT", "WITHDRAW"}

CATEGORY_MULT = {
    "DIRECT_QUOTE": Decimal("1.0"),
    "PARAPHRASE": Decimal("0.8"),
    "BIBLIOGRAPHY_ENTRY": Decimal("1.0"),
    "BOILERPLATE": Decimal("0.5"),
}

BAND_MARGIN = {"HIGH": 500, "MEDIUM": 1500, "LOW": 2500}

GRACE_DAYS = 7


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    now = fmt_iso(now_logical())
    entity["id"] = new_id()
    entity["created_at"] = now
    return entity


def stamp_common(entity):
    """Entities with common_fields get updated_at + version."""
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1


def bump(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = fmt_iso(now_logical())


def tokenize(content_text):
    return [w for w in content_text.split() if w.strip()]


def word_count_of(content_text):
    return len(tokenize(content_text))


# ---- Lazy transitions -------------------------------------------------------

def lazy_auto_close_assignment(a):
    if a["accepting_state"] == "OPEN":
        due = parse_iso(a["due_at"])
        if now_logical() >= due:
            a["accepting_state"] = "CLOSED"
            bump(a)


def lazy_expire_policy(p):
    if p["policy_state"] == "ACTIVE":
        end = parse_iso(p["retention_end"])
        if now_logical() >= end:
            p["policy_state"] = "EXPIRED"
            bump(p)


# ---- Cascades ---------------------------------------------------------------

def reports_of_submission(sub_id):
    return [r for r in DB["similarity_reports"].values() if r["submission_id"] == sub_id]


def report_of_submission(sub_id):
    reps = reports_of_submission(sub_id)
    return reps[0] if reps else None


def stale_report(report):
    """DRAFT|FINALIZED -> STALE, and RELEASED grade entries -> PROVISIONAL."""
    if report["report_state"] in ("DRAFT", "FINALIZED"):
        report["report_state"] = "STALE"
        bump(report)
        for ge in DB["grade_entries"].values():
            if ge["submission_id"] == report["submission_id"] and ge["grade_state"] == "RELEASED":
                ge["grade_state"] = "PROVISIONAL"
                bump(ge)


def stale_reports_touching_source(source_id):
    """Find all submissions with a fragment referencing this source; stale their reports."""
    affected_subs = {
        f["submission_id"]
        for f in DB["match_fragments"].values()
        if f["source_document_id"] == source_id
    }
    for sid in affected_subs:
        rep = report_of_submission(sid)
        if rep:
            stale_report(rep)


def retract_source_cascade(src):
    """source -> RETRACTED: exclude its fragments, stale dependent reports (+ grades)."""
    src["status"] = "RETRACTED"
    bump(src)
    for f in DB["match_fragments"].values():
        if f["source_document_id"] == src["id"]:
            f["excluded"] = True
    stale_reports_touching_source(src["id"])


def deposits_of_submission(sub_id):
    return [d for d in DB["repository_deposits"].values() if d["submission_id"] == sub_id]


def deposits_of_student(student_id):
    subs = [s["id"] for s in DB["submissions"].values() if s["student_id"] == student_id]
    out = []
    for sid in subs:
        out.extend(deposits_of_submission(sid))
    return out


def recompute_comparable(institution_id):
    inst = DB["institutions"].get(institution_id)
    if not inst:
        return
    count = sum(
        1
        for d in DB["repository_deposits"].values()
        if d["institution_id"] == institution_id
        and d["deposit_state"] == "STORED"
        and d["scope"] == "GLOBAL_SHARED"
    )
    inst["comparable_submission_count"] = count


def withdraw_deposit(dep, retract_source=True):
    """deposit -> WITHDRAWN; optionally retract its auto-created STUDENT_REPOSITORY source."""
    if dep["deposit_state"] == "WITHDRAWN":
        return
    dep["deposit_state"] = "WITHDRAWN"
    bump(dep)
    if retract_source:
        # find auto-created source for this deposit
        for src in DB["source_documents"].values():
            if src.get("auto_deposit_id") == dep["id"] and src["status"] == "ACTIVE":
                retract_source_cascade(src)
    recompute_comparable(dep["institution_id"])


def quarantine_deposit(dep, cause):
    """deposit STORED -> QUARANTINED. cause in {'consent','participation'}."""
    if dep["deposit_state"] != "STORED":
        return
    dep["deposit_state"] = "QUARANTINED"
    dep["quarantine_cause"] = cause
    bump(dep)
    recompute_comparable(dep["institution_id"])


def restore_deposit(dep):
    """QUARANTINED (participation cause only) -> STORED."""
    if dep["deposit_state"] != "QUARANTINED":
        return
    if dep.get("quarantine_cause") != "participation":
        return
    dep["deposit_state"] = "STORED"
    dep["quarantine_cause"] = None
    bump(dep)
    recompute_comparable(dep["institution_id"])


def consent_withdraw_cascade(student_id):
    for dep in deposits_of_student(student_id):
        quarantine_deposit(dep, cause="consent")


def institution_opt_out_cascade(institution):
    """participation -> OPT_OUT: quarantine all STORED deposits of this institution."""
    for dep in DB["repository_deposits"].values():
        if dep["institution_id"] == institution["id"]:
            quarantine_deposit(dep, cause="participation")
    recompute_comparable(institution["id"])


def institution_opt_in_cascade(institution):
    """participation restored: restore only participation-quarantined deposits."""
    for dep in DB["repository_deposits"].values():
        if dep["institution_id"] == institution["id"]:
            restore_deposit(dep)
    recompute_comparable(institution["id"])


def supersede_submission(prior):
    """prior -> SUPERSEDED; withdraw its STORED deposits (no source retraction on supersede)."""
    if prior["pipeline_state"] != "SUPERSEDED":
        prior["pipeline_state"] = "SUPERSEDED"
        bump(prior)
    for dep in deposits_of_submission(prior["id"]):
        if dep["deposit_state"] == "STORED":
            # supersession withdraws the stored deposit; per PRD §3.4 only the deposit flips.
            dep["deposit_state"] = "WITHDRAWN"
            bump(dep)
            recompute_comparable(dep["institution_id"])


def recompute_submission_count(assignment_id):
    a = DB["assignments"].get(assignment_id)
    if not a:
        return
    a["submission_count"] = sum(
        1
        for s in DB["submissions"].values()
        if s["assignment_id"] == assignment_id and s["pipeline_state"] != "SUPERSEDED"
    )


def institution_of_submission(sub):
    a = DB["assignments"].get(sub["assignment_id"])
    if not a:
        return None
    li = DB["lms_integrations"].get(a["lms_integration_id"])
    if not li:
        return None
    return DB["institutions"].get(li["institution_id"])


def assignment_of_submission(sub):
    return DB["assignments"].get(sub["assignment_id"])


def integration_of_assignment(a):
    return DB["lms_integrations"].get(a["lms_integration_id"])
