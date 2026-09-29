"""PRD 2.11: the logical clock and the deferred reauthorization sweep."""

from flask import Blueprint

from auth import ALL_ROLES, endpoint
from response import ok
from store import bump, db, fmt_ts, sort_rows
from validation import read_body, v_instant

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES)
def set_current_utc():
    body = read_body()
    current_utc = v_instant(body, "current_utc")
    # Mutates no entity; echoes back the value now in force.
    db.clock = current_utc
    return ok({"current_utc": fmt_ts(db.clock)})


@bp.post("/_ops/run-reauthorization-calendar")
@endpoint(["RegistryAdmin"])
def run_reauthorization_calendar():
    read_body(required=False)
    now = db.now()
    authorizations_expired = 0
    episodes_lapsed = 0
    enrollments_reauth_pending = 0

    # The coverage window is inclusive at both ends, so expiry needs the clock
    # to have passed valid_through outright.
    for authorization in sort_rows(list(db.authorizations.values())):
        if authorization["status"] != "APPROVED":
            continue
        valid_through = authorization["valid_through"]
        if valid_through is None or now <= valid_through:
            continue
        authorization["status"] = "EXPIRED"
        bump(authorization)
        authorizations_expired += 1
        episode = db.episodes.get(authorization["episode_id"])
        if episode is not None and episode["funding_state"] == "AUTHORIZED":
            episode["funding_state"] = "LAPSED"
            bump(episode)
            episodes_lapsed += 1

    for enrollment in sort_rows(list(db.enrollments.values())):
        if enrollment["status"] != "ACTIVE":
            continue
        due = enrollment["reauth_due_at"]
        if due is None or now < due:
            continue
        enrollment["status"] = "REAUTH_PENDING"
        bump(enrollment)
        enrollments_reauth_pending += 1

    return ok(
        {
            "authorizations_expired": authorizations_expired,
            "episodes_lapsed": episodes_lapsed,
            "enrollments_reauth_pending": enrollments_reauth_pending,
        }
    )
