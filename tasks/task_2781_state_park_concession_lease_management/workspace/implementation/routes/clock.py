"""The logical clock — PRD 2.4. The only source of 'now' in the system."""
from auth import guard
from envelope import ok
from router import route
from shape import body, req_instant
from store import db


@route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    guard("ProgramAdministrator")
    data = body()
    raw, parsed = req_instant(data, "current_utc")
    # Repositioning mutates no entity: no status moves, no version advances.
    db.clock = parsed
    return ok({"current_utc": raw})
