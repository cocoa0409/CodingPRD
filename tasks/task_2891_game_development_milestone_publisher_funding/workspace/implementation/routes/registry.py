"""Studios, publishers, publisher operators and the logical clock (PRD 3.1, 2.4)."""

from flask import Blueprint, request

from envelope import created, success
from guards import (
    ALL_ROLES,
    ROLE_PLATFORM_ADMIN,
    ROLE_PUBLISHER_FINANCE,
    ROLE_PUBLISHER_REVIEWER,
    begin,
    body,
    find_publisher,
    find_publisher_user,
    find_studio,
)
from listing import matches, paged
from serializers import publisher as ser_publisher
from serializers import publisher_user as ser_publisher_user
from serializers import studio as ser_studio
from store import db, lock, new_id, ordered, set_clock, stamp_new
from validation import Field, validate_email

bp = Blueprint("registry", __name__)

# PRD 3.1: "a legal_name of one to 120 characters that is not blank, a
# contact_email of one to 160 characters ... and optionally a country_code ...
# as exactly two uppercase letters".
PARTY_FIELDS = (
    Field("legal_name", "string", required=True, min_len=1, max_len=120, non_blank=True),
    Field("contact_email", "string", required=True, min_len=1, max_len=160, non_blank=True),
    Field("country_code", "string", pattern=r"^[A-Z]{2}$", min_len=2, max_len=2),
)

PUBLISHER_USER_FIELDS = (
    Field("publisher_id", "string", required=True),
    Field("display_name", "string", required=True, min_len=1, max_len=80, non_blank=True),
    Field("function", "enum", required=True, values=("REVIEW", "FINANCE", "DUAL")),
)

PUBLISHER_STAFF_ROLES = [ROLE_PLATFORM_ADMIN, ROLE_PUBLISHER_REVIEWER, ROLE_PUBLISHER_FINANCE]


def _party_row(data):
    validate_email(data["contact_email"])
    row = {
        "id": new_id(),
        "legal_name": data["legal_name"],
        "contact_email": data["contact_email"],
        "country_code": data["country_code"],
    }
    return stamp_new(row)


@bp.post("/studios")
def create_studio():
    begin([ROLE_PLATFORM_ADMIN], exempt_actor=True)
    _, data = body(PARTY_FIELDS)
    with lock:
        row = _party_row(data)
        db.studios[row["id"]] = row
        return created(ser_studio(row))


@bp.get("/studios/<sid>")
def read_studio(sid):
    begin(ALL_ROLES)
    with lock:
        return success(ser_studio(find_studio(sid)))


@bp.post("/publishers")
def create_publisher():
    begin([ROLE_PLATFORM_ADMIN], exempt_actor=True)
    _, data = body(PARTY_FIELDS)
    with lock:
        row = _party_row(data)
        db.publishers[row["id"]] = row
        return created(ser_publisher(row))


@bp.get("/publishers/<pid>")
def read_publisher(pid):
    begin(ALL_ROLES)
    with lock:
        return success(ser_publisher(find_publisher(pid)))


@bp.post("/publisher-users")
def create_publisher_user():
    begin([ROLE_PLATFORM_ADMIN], exempt_actor=True)
    _, data = body(PUBLISHER_USER_FIELDS)
    with lock:
        # Rule 19: publisher-user creation resolves publisher_id.
        find_publisher(data["publisher_id"])
        row = {
            "id": new_id(),
            "publisher_id": data["publisher_id"],
            "display_name": data["display_name"],
            "function": data["function"],
        }
        stamp_new(row)
        db.publisher_users[row["id"]] = row
        return created(ser_publisher_user(row))


@bp.get("/publisher-users/<uid>")
def read_publisher_user(uid):
    begin(PUBLISHER_STAFF_ROLES)
    with lock:
        return success(ser_publisher_user(find_publisher_user(uid)))


@bp.get("/publisher-users")
def list_publisher_users():
    begin(PUBLISHER_STAFF_ROLES)
    with lock:
        rows = [
            row for row in ordered(db.publisher_users.values())
            if matches(row, request.args, ("publisher_id", "function"))
        ]
        return paged(rows, request.args, ser_publisher_user)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    """PRD 2.4: "the call sets the clock and nothing else -- no entity is
    modified, no cascade runs, and the response carries no resource"."""
    begin([ROLE_PLATFORM_ADMIN], exempt_actor=True)
    _, data = body((Field("current_utc", "instant", required=True),))
    with lock:
        set_clock(data["current_utc"])
        return success({})
