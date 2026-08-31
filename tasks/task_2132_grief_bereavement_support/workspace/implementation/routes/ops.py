"""The logical clock and the operational sweep (§2.4, §2.10)."""

from datetime import timedelta

from flask import Blueprint

from core.auth import authenticate
from core.envelope import ok
from core.shape import body, req_str, bad
from core.store import parse_ts, public, store
from services import cascade, derive

bp = Blueprint("ops", __name__)

ACK_WINDOW_DAYS = 21


@bp.route("/bereavement/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["ProgramDirector"])
    data = body()
    raw = req_str(data, "to_iso8601")
    parsed = parse_ts(raw)
    if parsed is None:
        bad("to_iso8601 must be an ISO 8601 instant.")
    store.set_clock(parsed)
    return ok({"current_utc": store.now_iso()})


@bp.route("/bereavement/_ops/cadence-run", methods=["POST"])
def cadence_run():
    authenticate(["ProgramDirector"])
    body()
    counters = {
        "enrollments_expired": 0,
        "invitations_expired": 0,
        "companions_lapsed": 0,
        "matches_ended": 0,
        "outreaches_due": 0,
        "outreaches_no_response": 0,
    }
    now = store.now()
    today = store.today()

    # step 1 — held enrollments past their hold deadline
    for enr in store.all("Enrollment"):
        if enr["status"] != "HELD":
            continue
        held_until = parse_ts(enr["held_until"])
        if held_until is not None and now > held_until:
            enr["status"] = "EXPIRED"
            store.touch(enr)
            cohort = store.get("Cohort", enr["cohort_id"])
            if cohort is not None:
                derive.recompute_seats(cohort)
                store.touch(cohort)
            counters["enrollments_expired"] += 1

    # step 2 — sent invitations past their RSVP deadline
    for inv in store.all("Invitation"):
        if inv["status"] != "SENT":
            continue
        if today.isoformat() > inv["rsvp_deadline"]:
            inv["status"] = "EXPIRED"
            store.touch(inv)
            counters["invitations_expired"] += 1

    # step 3 — certified volunteers whose certification expired
    for volunteer in store.all("VolunteerCompanion"):
        if volunteer["status"] != "CERTIFIED":
            continue
        expires = volunteer.get("certification_expires_on")
        if expires is not None and today.isoformat() > expires:
            counters["matches_ended"] += cascade.lapse_volunteer(volunteer)
            counters["companions_lapsed"] += 1

    # step 4 — scheduled touchpoints whose due date has arrived
    for row in store.all("AnniversaryOutreach"):
        if row["status"] != "SCHEDULED":
            continue
        participant = store.get("Participant", row["participant_id"])
        if participant is None or participant["outreach_status"] != "SCHEDULED":
            continue
        if today.isoformat() >= row["due_on"]:
            row["status"] = "DUE"
            store.touch(row)
            counters["outreaches_due"] += 1

    # step 5 — sent touchpoints that have gone unanswered long enough
    for row in store.all("AnniversaryOutreach"):
        if row["status"] != "SENT":
            continue
        participant = store.get("Participant", row["participant_id"])
        if participant is not None and participant["outreach_status"] == "ON_HOLD":
            continue
        sent_at = parse_ts(row["sent_at"])
        if sent_at is None:
            continue
        if now >= sent_at + timedelta(days=ACK_WINDOW_DAYS):
            row["status"] = "NO_RESPONSE"
            store.touch(row)
            counters["outreaches_no_response"] += 1
            if participant is not None and participant["outreach_status"] == "SCHEDULED":
                participant["outreach_status"] = "LAPSED"
                store.touch(participant)

    return ok(counters)
