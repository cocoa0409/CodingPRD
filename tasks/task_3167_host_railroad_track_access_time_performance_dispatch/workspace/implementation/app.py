"""Host Railroad Dispatch API entry point.

Single Flask process; in-memory only; nothing seeded. The logical clock starts
at 2026-09-01T00:00:00Z and advances only via /rail/_clock/set_current_utc.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
from routes.agreements import bp as agreements_bp
from routes.disruptions import bp as disruptions_bp
from routes.funding import bp as funding_bp
from routes.incidents import bp as incidents_bp
from routes.network import bp as network_bp
from routes.projects import bp as projects_bp
from routes.runs import bp as runs_bp
from routes.settlements import bp as settlements_bp
from routes.timetables import bp as timetables_bp
from routes.windows import bp as windows_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(network_bp)
    app.register_blueprint(agreements_bp)
    app.register_blueprint(timetables_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(windows_bp)
    app.register_blueprint(disruptions_bp)
    app.register_blueprint(funding_bp)
    app.register_blueprint(settlements_bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            return respond_error(
                "ERR_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if status == 405:
            return respond_error(
                "ERR_INVALID_STATE",
                "The HTTP method is not allowed on this path.",
                405,
            )
        return respond_error("ERR_VALIDATION", exc.description or "HTTP error.", status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return respond_error("ERR_VALIDATION", str(exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
