"""Existence resolution — ladder rules 3 (path) and 4 (request body).

Path parameters are validated left to right; body foreign keys are resolved in
the order the fields appear in the endpoint's input list (PRD 2.5).  Each
identifier carries its own dedicated not-found error.
"""
import db
import errors


def _get(collection, key, error_id):
    if not isinstance(key, str):
        errors.fail(error_id, "Resource %r was not found." % key)
    row = collection.get(key)
    if row is None:
        errors.fail(error_id, "Resource %s was not found." % key)
    return row


# ---- path parameters (rule 3) ----------------------------------------------
def election(election_id):
    return _get(db.store.elections, election_id, errors.ERR_ELECTION_NOT_FOUND)


def office(office_id):
    return _get(db.store.offices, office_id, errors.ERR_OFFICE_NOT_FOUND)


def student(student_id):
    return _get(db.store.students, student_id, errors.ERR_STUDENT_NOT_FOUND)


def candidacy(candidacy_id):
    return _get(db.store.candidacies, candidacy_id, errors.ERR_CANDIDACY_NOT_FOUND)


def signature(signature_id):
    return _get(db.store.petition_signatures, signature_id, errors.ERR_SIGNATURE_NOT_FOUND)


def expense(expense_id):
    return _get(db.store.campaign_expenses, expense_id, errors.ERR_EXPENSE_NOT_FOUND)


def case(case_id):
    return _get(db.store.compliance_cases, case_id, errors.ERR_CASE_NOT_FOUND)


def referendum(referendum_id):
    return _get(db.store.referenda, referendum_id, errors.ERR_REFERENDUM_NOT_FOUND)


def ballot(ballot_id):
    return _get(db.store.ballots, ballot_id, errors.ERR_BALLOT_NOT_FOUND)


def ballot_line(line_id):
    return _get(db.store.ballot_lines, line_id, errors.ERR_BALLOT_LINE_NOT_FOUND)


def vote(vote_id):
    return _get(db.store.votes, vote_id, errors.ERR_VOTE_NOT_FOUND)


def appeal(appeal_id):
    return _get(db.store.appeals, appeal_id, errors.ERR_APPEAL_NOT_FOUND)


# ---- body foreign keys (rule 4) --------------------------------------------
def body_fk(body, field, collection, error_id):
    """Resolve a body foreign key.

    A value that is absent, null or not a string is left to the schema check of
    rule 5; a string that resolves to nothing raises the dedicated 404 now.
    """
    if field not in body:
        return None
    value = body[field]
    if value is None or not isinstance(value, str):
        return None
    row = collection.get(value)
    if row is None:
        errors.fail(error_id, "Resource %s was not found." % value)
    return row


def fk_election(body, field="election_id"):
    return body_fk(body, field, db.store.elections, errors.ERR_ELECTION_NOT_FOUND)


def fk_office(body, field="office_id"):
    return body_fk(body, field, db.store.offices, errors.ERR_OFFICE_NOT_FOUND)


def fk_student(body, field="student_id"):
    return body_fk(body, field, db.store.students, errors.ERR_STUDENT_NOT_FOUND)


def fk_candidacy(body, field="candidacy_id"):
    return body_fk(body, field, db.store.candidacies, errors.ERR_CANDIDACY_NOT_FOUND)


def fk_case(body, field="compliance_case_id"):
    return body_fk(body, field, db.store.compliance_cases, errors.ERR_CASE_NOT_FOUND)


def fk_referendum(body, field="referendum_id"):
    return body_fk(body, field, db.store.referenda, errors.ERR_REFERENDUM_NOT_FOUND)


def fk_ballot(body, field="ballot_id"):
    return body_fk(body, field, db.store.ballots, errors.ERR_BALLOT_NOT_FOUND)


# ---- collection helpers ----------------------------------------------------
def offices_of(election_id):
    return db.by_seq([o for o in db.store.offices.values()
                      if o["election_id"] == election_id])


def candidacies_of(election_id):
    return db.by_seq([c for c in db.store.candidacies.values()
                      if c["election_id"] == election_id])


def candidacies_of_office(office_id):
    return db.by_seq([c for c in db.store.candidacies.values()
                      if c["office_id"] == office_id])


def signatures_of(candidacy_id):
    return db.by_seq([s for s in db.store.petition_signatures.values()
                      if s["candidacy_id"] == candidacy_id])


def expenses_of(candidacy_id):
    return db.by_seq([e for e in db.store.campaign_expenses.values()
                      if e["candidacy_id"] == candidacy_id])


def cases_of(candidacy_id):
    return db.by_seq([c for c in db.store.compliance_cases.values()
                      if c["candidacy_id"] == candidacy_id])


def lines_of_ballot(ballot_id):
    return db.by_seq([l for l in db.store.ballot_lines.values()
                      if l["ballot_id"] == ballot_id])


def lines_of_candidacy(candidacy_id):
    return db.by_seq([l for l in db.store.ballot_lines.values()
                      if l["candidacy_id"] == candidacy_id])


def ballots_of(election_id):
    return db.by_seq([b for b in db.store.ballots.values()
                      if b["election_id"] == election_id])


def referenda_of(election_id):
    return db.by_seq([r for r in db.store.referenda.values()
                      if r["election_id"] == election_id])


def votes_of(election_id):
    return db.by_seq([v for v in db.store.votes.values()
                      if v["election_id"] == election_id])
