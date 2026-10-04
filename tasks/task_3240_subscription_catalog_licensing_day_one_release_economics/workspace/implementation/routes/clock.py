"""Logical clock control (PRD section 2.12)."""
from flask import Blueprint

from db import db
from errors import fail
from request_ctx import ctx, expect_query, run, want_instant
from response import ok_object
from services.store import advance_clock

bp = Blueprint("clock", __name__)


@bp.route("/catalog/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    c = ctx(["CatalogAdmin"], full=True)
    expect_query(c, ())
    run(c, _shape_clock)
    target = c.get("current_utc")
    # Let advance_clock own the assignment: it needs the *previous* instant to
    # detect a calendar-month rollover for the engagement rollover (PRD 3.6).
    advance_clock(target)
    return ok_object({})


def _shape_clock(c):
    want_instant(c, "current_utc", required=True)
