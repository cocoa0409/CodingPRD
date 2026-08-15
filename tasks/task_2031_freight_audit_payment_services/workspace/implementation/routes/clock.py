"""Logical clock endpoints."""

import db
from middleware import authenticate, require_roles
from response import success_object
from validate import get_body, check_shape


def register(app):

    @app.route("/fap/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        uid, role = authenticate()
        require_roles(role, {"FapAdmin"})
        body = get_body(allow_empty=False)
        check_shape(body, {
            "to_iso8601": {"kind": "string", "required": True},
        })
        current = db.set_clock(body["to_iso8601"])
        return success_object({"current_utc": current})
