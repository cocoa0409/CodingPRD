"""The logical UTC clock (PRD 2.1). Nothing in this service reads wall-clock time."""
from flask import Blueprint

import cascade
import serialize
import validate as v
from auth import REGULATORY_ADMIN, actor
from envelope import object_response
from store import db

bp = Blueprint("clock", __name__)
PREFIX = "/nitrogen-ops/_clock"


@bp.post(PREFIX + "/set_current_utc")
def set_current_utc():
    actor([REGULATORY_ADMIN])
    body = v.get_body()
    instant = v.s_dt(body, "to_iso8601")
    db.clock = instant
    # Sliding the 30-day window can move a plant's posture with no write to it.
    for plant in db.rows("plants"):
        cascade.rederive_posture(plant)
    return object_response(serialize.clock_json())
