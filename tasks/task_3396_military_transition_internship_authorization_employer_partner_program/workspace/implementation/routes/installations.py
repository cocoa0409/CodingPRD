from flask import Blueprint

import db
from middleware import (
    auth_context,
    require_role,
    body,
    locked,
    req_str,
    req_int,
    req_bool,
    opt_list_str,
)
from response import success
from util import serialize

bp = Blueprint("installations", __name__)


@bp.route("/installations", methods=["POST"])
@locked
def create_installation():
    uid, role = auth_context()
    data = body()
    name = req_str(data, "name")
    command_code = req_str(data, "command_code")
    region_code = req_str(data, "region_code")
    max_days = req_int(data, "max_internship_duration_days", min_value=1)
    appeal_days = req_int(data, "appeal_window_days", min_value=1)
    requires_tap = req_bool(data, "requires_tap_complete")
    excluded = opt_list_str(data, "excluded_pay_grades")
    require_role(role, ["ProgramOffice"])
    ent = db.base_entity()
    ent.update(
        {
            "name": name,
            "command_code": command_code,
            "region_code": region_code,
            "max_internship_duration_days": max_days,
            "appeal_window_days": appeal_days,
            "requires_tap_complete": requires_tap,
            "excluded_pay_grades": excluded,
        }
    )
    db.store.installations[ent["id"]] = ent
    return success(serialize(ent), status=201)
