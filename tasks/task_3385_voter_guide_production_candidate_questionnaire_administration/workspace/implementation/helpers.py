"""Entity resolution (PRD 2.8 left-to-right path checks) and graph walk
helpers shared by route modules."""
from errors import not_found
from store import store


def base_entity():
    """Common fields (PRD 2.5): id, created_at, updated_at, version."""
    now = store.clock
    return {
        "id": store.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }


def touch(entity):
    """A mutation refreshes updated_at and increments version by exactly 1."""
    entity["updated_at"] = store.clock
    entity["version"] += 1


def get_cycle(cid):
    e = store.cycles.get(cid)
    if e is None:
        raise not_found("ElectionCycle not found")
    return e


def get_jurisdiction(jid):
    e = store.jurisdictions.get(jid)
    if e is None:
        raise not_found("Jurisdiction not found")
    return e


def get_contest(cid):
    e = store.contests.get(cid)
    if e is None:
        raise not_found("Contest not found")
    return e


def get_filing(fid):
    e = store.filings.get(fid)
    if e is None:
        raise not_found("CandidateFiling not found")
    return e


def get_questionnaire(qid):
    e = store.questionnaires.get(qid)
    if e is None:
        raise not_found("Questionnaire not found")
    return e


def get_response(rid):
    e = store.responses.get(rid)
    if e is None:
        raise not_found("CandidateResponse not found")
    return e


def get_measure(mid):
    e = store.measures.get(mid)
    if e is None:
        raise not_found("BallotMeasure not found")
    return e


def get_edition(eid):
    e = store.editions.get(eid)
    if e is None:
        raise not_found("GuideEdition not found")
    return e


def get_forum(fid):
    e = store.forums.get(fid)
    if e is None:
        raise not_found("Forum not found")
    return e


def get_question(qid):
    e = store.questions.get(qid)
    if e is None:
        raise not_found("ForumQuestion not found")
    return e


def get_volunteer(vid):
    e = store.volunteers.get(vid)
    if e is None:
        raise not_found("Volunteer not found")
    return e


def get_incident(iid):
    e = store.incidents.get(iid)
    if e is None:
        raise not_found("PolicyIncident not found")
    return e


# --- relationship walks ---------------------------------------------------
def jurisdictions_of_cycle(cycle_id):
    return [j for j in store.jurisdictions.values() if j["cycle_id"] == cycle_id]


def contests_of_jurisdiction(jurisdiction_id):
    return [c for c in store.contests.values() if c["jurisdiction_id"] == jurisdiction_id]


def contests_of_cycle(cycle_id):
    out = []
    for j in jurisdictions_of_cycle(cycle_id):
        out.extend(contests_of_jurisdiction(j["id"]))
    return out


def jurisdiction_of_contest(contest):
    return store.jurisdictions.get(contest["jurisdiction_id"])


def cycle_of_contest(contest):
    j = jurisdiction_of_contest(contest)
    return store.cycles.get(j["cycle_id"]) if j else None


def filings_of_contest(contest_id):
    return [f for f in store.filings.values() if f["contest_id"] == contest_id]


def questionnaire_of_contest(contest_id):
    for q in store.questionnaires.values():
        if q["contest_id"] == contest_id:
            return q
    return None


def measure_of_contest(contest_id):
    for m in store.measures.values():
        if m["contest_id"] == contest_id:
            return m
    return None


def shells_of_questionnaire(questionnaire_id):
    return [r for r in store.responses.values() if r["questionnaire_id"] == questionnaire_id]


def shell_of(questionnaire_id, filing_id):
    for r in store.responses.values():
        if r["questionnaire_id"] == questionnaire_id and r["filing_id"] == filing_id:
            return r
    return None


def shell_of_filing(filing_id):
    for r in store.responses.values():
        if r["filing_id"] == filing_id:
            return r
    return None


def arguments_of_measure(measure_id):
    return [a for a in store.arguments.values() if a["measure_id"] == measure_id]


def reviews_of_measure(measure_id):
    return [r for r in store.reviews.values() if r["measure_id"] == measure_id]


def editions_of_cycle(cycle_id):
    return [e for e in store.editions.values() if e["cycle_id"] == cycle_id]


def forums_of_contest(contest_id):
    return [f for f in store.forums.values() if f["contest_id"] == contest_id]


def questions_of_forum(forum_id):
    return [q for q in store.questions.values() if q["forum_id"] == forum_id]


def incidents_of_volunteer(volunteer_id):
    return [i for i in store.incidents.values() if i["volunteer_id"] == volunteer_id]


def sorted_rows(rows):
    """Default list ordering: created_at ascending (PRD 2.3); insertion
    sequence breaks ties when one logical instant stamps many rows."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def page_of(rows, limit, offset):
    rows = sorted_rows(rows)
    total = len(rows)
    return rows[offset:offset + limit], total
