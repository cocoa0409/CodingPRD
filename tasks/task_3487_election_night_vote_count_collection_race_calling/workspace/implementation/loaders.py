"""Entity resolution (PRD §2.6: first unresolved segment determines the
not-found error) and posture gates (PRD §2.5 / validation priority 5)."""
from clock import now as clock_now
from errors import raise_err
from store import db, next_seq
from util import new_id


def _get(table, rid, error_id):
    rec = db[table].get(rid)
    if rec is None:
        raise_err(error_id, f"{error_id}: {rid}")
    return rec


def get_event(rid):
    return _get("events", rid, "ERR_EVENT_NOT_FOUND")


def get_contest(rid):
    return _get("contests", rid, "ERR_CONTEST_NOT_FOUND")


def get_county(rid):
    return _get("counties", rid, "ERR_COUNTY_NOT_FOUND")


def get_stringer(rid):
    return _get("stringers", rid, "ERR_STRINGER_NOT_FOUND")


def get_assignment(rid):
    return _get("assignments", rid, "ERR_ASSIGNMENT_NOT_FOUND")


def get_report(rid):
    return _get("reports", rid, "ERR_REPORT_NOT_FOUND")


def get_call(rid):
    return _get("calls", rid, "ERR_CALL_NOT_FOUND")


def get_recount(rid):
    return _get("recounts", rid, "ERR_RECOUNT_NOT_FOUND")


def get_coverage(rid):
    return _get("coverages", rid, "ERR_DECISION_NOT_FOUND")


def get_customer(rid):
    return _get("customers", rid, "ERR_CUSTOMER_NOT_FOUND")


def event_of_contest(contest):
    return db["events"][contest["event_id"]]


def event_of_report(report):
    return db["events"][db["contests"][report["contest_id"]]["event_id"]]


def event_of_call(call):
    return db["events"][db["contests"][call["contest_id"]]["event_id"]]


def event_of_recount(case):
    return db["events"][db["contests"][case["contest_id"]]["event_id"]]


def require_posture(event, *allowed):
    """Validation priority 5: the endpoint's posture gate."""
    if event["posture"] not in allowed:
        raise_err(
            "ERR_POSTURE_FORBIDS",
            f"Event posture {event['posture']} does not admit this operation",
        )


def base_record():
    """Common fields: server-minted id, logical-clock created_at, and the
    internal insertion sequence used for created_at tie-breaks."""
    ts = clock_now()
    return {"id": new_id(), "created_at": ts, "_seq": next_seq()}


def versioned_record():
    rec = base_record()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version on a mutation (PRD §2.4)."""
    rec["updated_at"] = clock_now()
    rec["version"] += 1
