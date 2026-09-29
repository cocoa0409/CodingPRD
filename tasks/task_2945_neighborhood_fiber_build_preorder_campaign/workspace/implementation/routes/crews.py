"""Install crews (PRD 3.8)."""

from flask import Blueprint

import auth
import calc
import envelope
import listing
import serialize
import shape
from store import insert, must_find, new_row, ordered, rows

bp = Blueprint("crews", __name__)

READ_ROLES = ("ProgramManager", "InstallCoordinator")


@bp.post("/install-crews")
def create_crew():
    auth.gate(("InstallCoordinator",))
    data = shape.body()
    row = new_row(
        {
            "name": shape.req_str(data, "name", 1, 80),
            "crew_type": shape.req_enum(data, "crew_type", calc.CREW_TYPES),
            "travel_buffer_minutes": shape.opt_int(data, "travel_buffer_minutes", 0, 240, 30),
            "daily_capacity_minutes": shape.opt_int(data, "daily_capacity_minutes", 60, 1440, 480),
        }
    )
    insert("install_crews", row)
    return envelope.created(serialize.install_crew(row))


@bp.get("/install-crews/<crew_id>")
def read_crew(crew_id):
    auth.gate(READ_ROLES)
    row = must_find("install_crews", crew_id)
    return envelope.ok(serialize.install_crew(row))


@bp.get("/install-crews")
def list_crews():
    auth.gate(READ_ROLES)
    items = listing.apply_filters(
        ordered(rows("install_crews")),
        (listing.enum("crew_type", "crew_type", calc.CREW_TYPES),),
    )
    return envelope.list_response(items, serialize.install_crew)
