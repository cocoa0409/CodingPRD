"""Entry point: Flask app, error handlers, route registration."""
from __future__ import annotations

import os

from flask import Flask

from db import db
from errors import ApiError, err_invalid_request
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_clock
    import routes_registrations
    import routes_engagements
    import routes_self_reports
    import routes_violations
    import routes_mitigation
    import routes_selflog
    import routes_cip
    import routes_penalties
    import routes_appeals

    app.register_blueprint(routes_clock.bp, url_prefix="/compliance")
    app.register_blueprint(routes_registrations.bp, url_prefix="/compliance")
    app.register_blueprint(routes_engagements.bp, url_prefix="/compliance")
    app.register_blueprint(routes_self_reports.bp, url_prefix="/compliance")
    app.register_blueprint(routes_violations.bp, url_prefix="/compliance")
    app.register_blueprint(routes_mitigation.bp, url_prefix="/compliance")
    app.register_blueprint(routes_selflog.bp, url_prefix="/compliance")
    app.register_blueprint(routes_cip.bp, url_prefix="/compliance")
    app.register_blueprint(routes_penalties.bp, url_prefix="/compliance")
    app.register_blueprint(routes_appeals.bp, url_prefix="/compliance")

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Referenced id does not exist", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Referenced id does not exist", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
