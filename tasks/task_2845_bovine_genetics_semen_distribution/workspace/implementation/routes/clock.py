"""The logical clock and its epoch sweep (PRD 2.5)."""

from flask import Blueprint

import auth
import cascades
import config
import envelope
import store
import validate
from errors import fail
from validate import F

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    values = validate.parse([F("current_utc", "datetime", required=True)])
    auth.require_role(config.ROLE_PROGRAM_DIRECTOR)
    target = values["current_utc"]
    if target <= store.clock():
        fail("ERR_CLOCK_REWIND", "The logical clock is strictly monotonic.")
    return envelope.ok(cascades.epoch_sweep(target))
