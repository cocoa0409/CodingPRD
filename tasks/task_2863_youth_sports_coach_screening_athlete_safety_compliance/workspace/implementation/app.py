"""SafeSport youth-sports compliance platform - Flask application factory.

Storage is in-memory only and starts completely empty on every boot; no entity
is ever seeded. Mounted entirely under the /safesport prefix.
"""

import os

from flask import Blueprint, Flask
from werkzeug.exceptions import HTTPException

import auth
import clock
import derive
import envelope
import routes_audits
import routes_cases
import routes_clubs
import routes_coach
import routes_measures
import routes_members
import routes_rooms
import routes_screening
import routes_training
import validate
from errors import ApiError

API_PREFIX = "/safesport"

meta_bp = Blueprint("meta", __name__)


@meta_bp.post("/_clock/set_current_utc")
@auth.endpoint("NgbAdmin")
def set_clock():
    data = validate.body(auth.payload(), {"to_iso8601": validate.instant()})
    clock.set_now(data["to_iso8601"])
    derive.sync()
    return envelope.ok({"current_utc": clock.iso(clock.now())})


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (routes_clubs, routes_members, routes_screening, routes_training,
                   routes_coach, routes_cases, routes_measures, routes_audits,
                   routes_rooms):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)
    app.register_blueprint(meta_bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return envelope.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return envelope.error("ERR_NOT_FOUND", "the requested path does not exist", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return envelope.error("ERR_METHOD_NOT_ALLOWED",
                              "the method is not allowed for this path", 405)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return envelope.error("ERR_VALIDATION", "the request could not be parsed", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return envelope.error(exc.error_id, exc.message, exc.http_status)
        if isinstance(exc, HTTPException):
            if exc.code == 404:
                return envelope.error("ERR_NOT_FOUND", "the requested path does not exist", 404)
            if exc.code == 405:
                return envelope.error("ERR_METHOD_NOT_ALLOWED",
                                      "the method is not allowed for this path", 405)
            return envelope.error("ERR_VALIDATION", "the request could not be processed", 422)
        return envelope.error("ERR_INTERNAL", "unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
