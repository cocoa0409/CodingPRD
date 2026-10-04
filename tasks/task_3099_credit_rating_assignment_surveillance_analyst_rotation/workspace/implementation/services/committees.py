"""Rating committees: convening, sessions, votes and decision rounds.

SCAFFOLD state_machines -> RatingCommittee / CommitteeVote,
PRD sections 3.4 and 3.5.
"""

from db import base_row, db, now, parse_ts, touch
from domain import INDEPENDENCE_DAYS
from errors import fail
from services import calculations, common


def create(rating_request_id, committee_date, required_voting_members):
    row = base_row()
    row.update(
        {
            "rating_request_id": rating_request_id,
            "committee_date": parse_ts(committee_date),
            "required_voting_members": int(required_voting_members or 0),
            "votes_cast": 0,
            "quorum_met": False,
            "dissent_count": 0,
            "committee_status": "CONVENED",
            "session_opened_at": None,
        }
    )
    db.rating_committees[row["id"]] = row
    return row


def session_overlap(committee):
    """Does this committee's sitting interval collide with another open one?"""
    start = committee["committee_date"]
    if start is None:
        return False
    for other in db.rating_committees.values():
        if other["id"] == committee["id"]:
            continue
        if other["committee_status"] not in ("CONVENED", "IN_SESSION"):
            continue
        other_start = other["committee_date"]
        if other_start is None:
            continue
        if start == other_start:
            return True
    return False


def open_session(committee):
    # PRD §3.5: both `decide` and `redecide` report a committee that is not
    # decidable — including one that is DISSOLVED — as ERR_COMMITTEE_NOT_IN_SESSION.
    if committee["committee_status"] not in ("CONVENED", "IN_SESSION"):
        fail("ERR_COMMITTEE_NOT_IN_SESSION")
    if committee["committee_date"] is None or not committee["committee_date"] <= now():
        fail("ERR_COMMITTEE_NOT_DUE")
    if session_overlap(committee):
        fail("ERR_COMMITTEE_SCHEDULE_OVERLAP")
    committee["committee_status"] = "IN_SESSION"
    committee["session_opened_at"] = committee["committee_date"]
    return touch(committee)


def votes_for(committee_id):
    rows = [
        v for v in db.committee_votes.values() if v["rating_committee_id"] == committee_id
    ]
    rows.sort(key=lambda v: (v["voted_at"], v["created_at"], v["id"]))
    return rows


def cast_vote(committee, analyst_id, vote_value, assigned_grade, dissent_rationale):
    if committee["committee_status"] != "IN_SESSION":
        fail("ERR_INVALID_STATE", "Votes may only be cast while the committee is IN_SESSION.")

    analyst = db.analysts.get(analyst_id)
    if analyst is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if analyst["analyst_tier"] != "COMMITTEE_ELIGIBLE":
        fail("ERR_VOTE_NOT_ELIGIBLE_MEMBER")
    for existing in votes_for(committee["id"]):
        if existing["analyst_id"] == analyst_id:
            fail("ERR_VOTE_NOT_ELIGIBLE_MEMBER")

    row = base_row(common=False)
    row.update(
        {
            "rating_committee_id": committee["id"],
            "analyst_id": analyst_id,
            "vote_value": vote_value,
            "assigned_grade": assigned_grade,
            "dissent_rationale": dissent_rationale,
            "is_dissent": False,
            "voted_at": now(),
        }
    )
    db.committee_votes[row["id"]] = row

    committee["votes_cast"] = int(committee["votes_cast"]) + 1
    committee["quorum_met"] = committee["votes_cast"] >= int(committee["required_voting_members"])
    touch(committee)
    return row


def _abstentions_outstanding(committee_id):
    return any(
        v["vote_value"] == "ABSTAIN" for v in votes_for(committee_id)
    )


def _stale_independence(committee_id):
    """Any appearing voter whose declaration is older than 180 days?"""
    for vote in votes_for(committee_id):
        analyst = db.analysts.get(vote["analyst_id"])
        if analyst is None:
            continue
        declared = analyst.get("independence_declared_at")
        if declared is None:
            return True
        elapsed = (now() - declared).total_seconds() / 86400.0
        if elapsed > INDEPENDENCE_DAYS:
            return True
    return False


def _check_decidable(committee, request):
    if committee["committee_status"] not in ("CONVENED", "IN_SESSION"):
        fail("ERR_COMMITTEE_NOT_IN_SESSION")
    if request is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if request["request_status"] not in ("TEAM_CONFIRMED", "APPEALED"):
        fail("ERR_REQUEST_NOT_TEAM_CONFIRMED")
    if not committee["quorum_met"]:
        fail("ERR_COMMITTEE_QUORUM_NOT_MET")
    if _abstentions_outstanding(committee["id"]):
        fail("ERR_COMMITTEE_ABSTENTION_NOT_PERMITTED")
    if _stale_independence(committee["id"]):
        fail("ERR_INDEPENDENCE_DECLARATION_STALE")


def mark_dissent(committee_id, decided_grade):
    """Mark, then score, the votes that differ from the decided majority."""
    majority = [
        (v, v.get("assigned_grade"))
        for v in votes_for(committee_id)
        if v["vote_value"] != "ABSTAIN"
    ]
    total = 0
    for vote, grade in majority:
        if grade is not None and decided_grade is not None and grade != decided_grade:
            vote["is_dissent"] = True
            total += 1
    count, score = calculations.dissent_tally(committee_id, decided_grade, False)
    return count, score


def spell_out_dissent(decision, committee_id):
    """Restate a draft decision's dissent tally over its committee's votes."""
    count, score = calculations.dissent_tally(committee_id, decision["assigned_grade"], False)
    decision["dissent_count"] = count
    decision["dissent_score"] = score
    return count, score


def build_decision(committee, request, entity, assigned_grade, outlook, watch_status, rationale):
    from db import base_row as _base_row

    methodology_code = None
    methodology_id = entity.get("methodology_id") if entity else None
    if methodology_id is not None:
        methodology = db.methodologies.get(methodology_id)
        if methodology is not None:
            methodology_code = methodology["methodology_code"]

    row = _base_row()
    row.update(
        {
            "rating_request_id": request["id"],
            "assigned_grade": assigned_grade,
            "prior_grade": entity.get("current_grade") if entity else None,
            "outlook": outlook,
            "watch_status": watch_status,
            "rationale": rationale,
            "dissent_count": 0,
            "dissent_score": 0,
            "decision_status": "DRAFT",
            "published_at": None,
            "appeal_window_end_at": None,
            "is_unsolicited": bool(
                entity and entity.get("solicitation_status") == "UNSOLICITED"
            ),
            "methodology_code": methodology_code,
        }
    )
    db.rating_decisions[row["id"]] = row
    return row


def _check_rationale(rationale):
    if len(rationale or "") < 200:
        fail("ERR_RATIONALE_TOO_SHORT")


def decide(committee, assigned_grade, outlook, watch_status, rationale):
    request = db.rating_requests.get(committee["rating_request_id"])
    _check_decidable(committee, request)
    _check_rationale(rationale)
    entity = db.rated_entities.get(request["rated_entity_id"])

    dissent_count, dissent_score = mark_dissent(committee["id"], assigned_grade)

    decision = build_decision(
        committee, request, entity, assigned_grade, outlook, watch_status, rationale
    )
    decision["dissent_count"] = dissent_count
    decision["dissent_score"] = dissent_score

    committee["committee_status"] = "DECIDED"
    committee["dissent_count"] = dissent_count
    touch(committee)

    request["request_status"] = "COMMITTEE_DECIDED"
    touch(request)
    return decision


def decidable_for_request(request, committee=None):
    """Resolve the committee that owns a request's current decision round."""
    if committee is not None:
        return committee
    return common.primary_committee_for_request(request["id"])


def redecide(committee, assigned_grade, outlook, watch_status, rationale):
    request = db.rating_requests.get(committee["rating_request_id"])
    if committee["committee_status"] not in ("DECIDED", "IN_SESSION"):
        fail("ERR_COMMITTEE_NOT_IN_SESSION")
    if request is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if request["request_status"] not in ("TEAM_CONFIRMED", "APPEALED"):
        fail("ERR_REQUEST_NOT_TEAM_CONFIRMED")
    if not committee["quorum_met"]:
        fail("ERR_COMMITTEE_QUORUM_NOT_MET")
    if _abstentions_outstanding(committee["id"]):
        fail("ERR_COMMITTEE_ABSTENTION_NOT_PERMITTED")
    if _stale_independence(committee["id"]):
        fail("ERR_INDEPENDENCE_DECLARATION_STALE")
    _check_rationale(rationale)

    entity = db.rated_entities.get(request["rated_entity_id"])
    previous = common.any_decision_for_request(request["id"])

    dissent_count, dissent_score = mark_dissent(committee["id"], assigned_grade)

    decision = build_decision(
        committee, request, entity, assigned_grade, outlook, watch_status, rationale
    )
    decision["dissent_count"] = dissent_count
    decision["dissent_score"] = dissent_score

    if previous is not None and previous["id"] != decision["id"]:
        if previous["decision_status"] != "PUBLISHED":
            previous["decision_status"] = "WITHDRAWN"
            touch(previous)

    committee["committee_status"] = "DECIDED"
    committee["dissent_count"] = dissent_count
    touch(committee)

    request["request_status"] = "COMMITTEE_DECIDED"
    touch(request)
    return decision


def reopen(committee):
    # PRD §3.6: "a committee may be reopened only while its request is
    # APPEALED, and a reopen attempted otherwise is rejected with
    # ERR_COMMITTEE_NOT_REOPENABLE".  An accepted appeal already returns the
    # committee to IN_SESSION, so a reopen against a request in APPEALED is
    # accepted whether the committee is still DECIDED or already reopened.
    request = db.rating_requests.get(committee["rating_request_id"])
    if request is None or request["request_status"] != "APPEALED":
        fail("ERR_COMMITTEE_NOT_REOPENABLE")
    if committee["committee_status"] not in ("DECIDED", "IN_SESSION"):
        fail("ERR_COMMITTEE_NOT_REOPENABLE")
    committee["committee_status"] = "IN_SESSION"
    return touch(committee)


def quorum_fail(committee):
    """CONVENED -> QUORUM_FAILED; the parent request returns to SCREENING."""
    if committee["votes_cast"] >= int(committee["required_voting_members"]):
        return None
    committee["committee_status"] = "QUORUM_FAILED"
    touch(committee)
    request = db.rating_requests.get(committee["rating_request_id"])
    if request is not None and request["request_status"] in (
        "SUBMITTED",
        "SCREENING",
        "TEAM_CONFIRMED",
    ):
        request["request_status"] = "SCREENING"
        touch(request)
    return committee


def sweep(row):
    """Automatic CONVENED -> QUORUM_FAILED once committee_date has passed
    with the quorum still unmet.  Idempotent, so a read may safely call it."""
    if row["committee_status"] != "CONVENED":
        return row
    due = row.get("committee_date")
    if due is None or due > now():
        return row
    if int(row["votes_cast"]) < int(row["required_voting_members"]):
        quorum_fail(row)
    return row


def sweep_all(rows):
    for row in rows:
        sweep(row)
    return rows