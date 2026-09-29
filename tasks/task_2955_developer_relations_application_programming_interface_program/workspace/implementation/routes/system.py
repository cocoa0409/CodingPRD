"""The programme checkpoint and the logical-clock test-driving endpoints."""
from flask import Blueprint

from constants import ALL_ROLES, ROLE_PLATFORM_ADMIN
from db import format_instant, store
from errors import ApiError
from middleware import endpoint
from response import object_response
from services import checkpoint
from validation import body

bp = Blueprint("system", __name__)


@bp.post("/program-checkpoints")
@endpoint([ROLE_PLATFORM_ADMIN])
def run_program_checkpoint():
    body()
    return object_response(checkpoint.run_checkpoint())


@bp.post("/_clock/set_current_utc")
@endpoint([ROLE_PLATFORM_ADMIN])
def set_clock():
    payload = body()
    current = payload.instant("current_utc")

    previous = store.now()
    if current <= previous:
        raise ApiError(
            "ERR_CLOCK_REWIND",
            "The logical clock only moves forward; it currently reads %s."
            % format_instant(previous),
        )

    store.clock = current
    return object_response(
        {
            "current_utc": format_instant(current),
            "previous_utc": format_instant(previous),
        }
    )


@bp.get("/_clock/current")
@endpoint(ALL_ROLES, require_headers=False)
def read_clock():
    return object_response({"current_utc": format_instant(store.now())})
