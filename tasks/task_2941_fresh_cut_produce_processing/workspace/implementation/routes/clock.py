"""The plant logical clock (PRD 2.4). Test-driving capability, PlantAdmin only."""

from flask import Blueprint

from envelope import object_response, read_body, require
from util import CLOCK

bp = Blueprint("clock", __name__)

SET_CLOCK = (("current_utc", "datetime", True),)


@bp.post("/_clock/set_current_utc")
@require("PlantAdmin")
def set_current_utc():
    body = read_body(SET_CLOCK)
    instant = body["current_utc"]
    CLOCK.set(instant.dt)
    return object_response({"current_utc": instant.raw})
