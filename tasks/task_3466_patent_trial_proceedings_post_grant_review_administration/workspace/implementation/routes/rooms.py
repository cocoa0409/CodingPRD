"""POST /ptab/hearing-rooms — register a hearing room (PRD 3.1)."""

from flask import Blueprint

from db import store, strip_internal
from errors import raise_err, ERR_VALIDATION
from helpers import (
    require_roles, get_body, req_string, req_int, success_object,
)

bp = Blueprint("rooms", __name__)


@bp.post("/ptab/hearing-rooms")
def create_room():
    require_roles("PlatformAdmin")
    body = get_body()
    name = req_string(body, "name")
    capacity = req_int(body, "capacity", minimum=1)

    room = store.new_common()
    room.update({
        "name": name,
        "capacity": capacity,
    })
    for existing in store.rooms.values():
        if existing["name"] == name:
            raise_err(ERR_VALIDATION,
                      "name must be unique across the board facility")
    store.rooms[room["id"]] = room
    return success_object(strip_internal(room), status=201)
