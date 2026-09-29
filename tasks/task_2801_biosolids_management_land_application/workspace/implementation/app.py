"""Biosolids Land Application API — Flask entry point."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError

from routes_facility import bp as facility_bp
from routes_limits import bp as limits_bp
from routes_batch import bp as batch_bp
from routes_site import bp as site_bp
from routes_agreement import bp as agreement_bp
from routes_event import bp as event_bp
from routes_outlet import bp as outlet_bp
from routes_odor import bp as odor_bp
from routes_report import bp as report_bp
from routes_misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in (facility_bp, limits_bp, batch_bp, site_bp, agreement_bp,
                      event_bp, outlet_bp, odor_bp, report_bp, misc_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        return error_response("ERR_INVALID_REQUEST",
                              exc.description or "Request could not be processed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
