"""The logical clock endpoint (PRD SS2.4)."""
from flask import Blueprint

from constants import ROLE_PLATFORM_ADMIN
from db import db, fmt_instant, rows
from derive import by_created, refresh_title
from middleware import endpoint
from response import ok
from validation import json_body, req_instant

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint([ROLE_PLATFORM_ADMIN])
def set_current_utc():
    body = json_body()
    current_utc = req_instant(body, "current_utc")

    db.clock = current_utc
    # the certification-window arithmetic is a function of the clock, so every
    # title's release-gate posture is recomputed when the clock moves
    for title in by_created(rows("titles")):
        refresh_title(title)

    return ok({"current_utc": fmt_instant(current_utc)})
