"""Entity resolution: every collection has its own 404 code (PRD 2.5)."""
from db import db
from errors import ApiError

_MAP = (
    ("programs", "ERR_PROGRAM_NOT_FOUND"),
    ("competencies", "ERR_COMPETENCY_NOT_FOUND"),
    ("blueprints", "ERR_BLUEPRINT_NOT_FOUND"),
    ("students", "ERR_STUDENT_NOT_FOUND"),
    ("terms", "ERR_TERM_NOT_FOUND"),
    ("mentors", "ERR_MENTOR_NOT_FOUND"),
    ("assignments", "ERR_ASSIGNMENT_NOT_FOUND"),
    ("evaluators", "ERR_EVALUATOR_NOT_FOUND"),
    ("attempts", "ERR_ATTEMPT_NOT_FOUND"),
    ("scores", "ERR_SCORE_NOT_FOUND"),
    ("cases", "ERR_CASE_NOT_FOUND"),
    ("sap_reviews", "ERR_SAP_REVIEW_NOT_FOUND"),
    ("disbursements", "ERR_DISBURSEMENT_NOT_FOUND"),
    ("transcripts", "ERR_TRANSCRIPT_NOT_FOUND"),
)

CODES = dict(_MAP)


def find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, collection).get(row_id)


def must(collection, row_id):
    row = find(collection, row_id)
    if row is None:
        raise ApiError(CODES[collection],
                       "No %s exists with the supplied identifier."
                       % collection.rstrip("s").replace("_", " "))
    return row


def program(pid):
    return must("programs", pid)


def competency(cid):
    return must("competencies", cid)


def blueprint(bid):
    return must("blueprints", bid)


def student(sid):
    return must("students", sid)


def term(tid):
    return must("terms", tid)


def mentor(mid):
    return must("mentors", mid)


def assignment(aid):
    return must("assignments", aid)


def evaluator(eid):
    return must("evaluators", eid)


def attempt(aid):
    return must("attempts", aid)


def score(sid):
    return must("scores", sid)


def case(cid):
    return must("cases", cid)


def sap_review(rid):
    return must("sap_reviews", rid)


def disbursement(did):
    return must("disbursements", did)


def transcript(tid):
    return must("transcripts", tid)


# ---- collection scans --------------------------------------------------

def competencies_of(program_id):
    return [c for c in db.competencies.values()
            if c["program_id"] == program_id]


def blueprints_of(competency_id):
    return [b for b in db.blueprints.values()
            if b["competency_id"] == competency_id]


def terms_of(student_id):
    return [t for t in db.terms.values() if t["student_id"] == student_id]


def assignments_of(student_id):
    return [a for a in db.assignments.values()
            if a["student_id"] == student_id]


def assignments_for_mentor(mentor_id):
    return [a for a in db.assignments.values()
            if a["mentor_id"] == mentor_id]


def attempts_of(student_id):
    return [a for a in db.attempts.values() if a["student_id"] == student_id]


def attempts_on_term(term_id):
    return [a for a in db.attempts.values() if a["term_id"] == term_id]


def scores_of(attempt_id):
    return [s for s in db.scores.values() if s["attempt_id"] == attempt_id]


def cases_of_attempt(attempt_id):
    return [c for c in db.cases.values() if c["attempt_id"] == attempt_id]


def cases_of_student(student_id):
    return [c for c in db.cases.values() if c["student_id"] == student_id]


def disbursements_of_student(student_id):
    return [d for d in db.disbursements.values()
            if d["student_id"] == student_id]


def disbursements_of_term(term_id):
    return [d for d in db.disbursements.values() if d["term_id"] == term_id]


def transcripts_of(student_id):
    return [t for t in db.transcripts.values()
            if t["student_id"] == student_id]


def sap_reviews_of(student_id):
    return [r for r in db.sap_reviews.values()
            if r["student_id"] == student_id]


def program_of_student(student_row):
    return db.programs.get(student_row["program_id"])


def program_of_competency(competency_row):
    return db.programs.get(competency_row["program_id"])


def program_of_attempt(attempt_row):
    student_row = db.students.get(attempt_row["student_id"])
    if student_row is None:
        return None
    return db.programs.get(student_row["program_id"])
