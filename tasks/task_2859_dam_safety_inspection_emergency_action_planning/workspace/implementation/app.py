"""Dam Safety Inspection and Emergency Action Planning service.

Storage is in-memory only: every byte of state lives in the `store.db` object and
is therefore discarded when this process exits. Nothing is seeded at startup --
every owner, engineer, reach, dam, assessment, inspection, deficiency, order,
plan, exercise, permit, event, reading, drawdown and ledger entry must be created
through the declared API endpoints.
"""

import os

from flask import Flask

from common import ApiError, error_body
import routes_assessment
import routes_eap
import routes_emergency
import routes_inspection
import routes_permit
import routes_program
import routes_registry


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_assessment.bp)
    app.register_blueprint(routes_inspection.bp)
    app.register_blueprint(routes_eap.bp)
    app.register_blueprint(routes_permit.bp)
    app.register_blueprint(routes_emergency.bp)
    app.register_blueprint(routes_program.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        payload, _status = error_body(exc.error_id, exc.message)
        return payload, exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        payload, _status = error_body("ERR_INVALID_REQUEST", "no such resource path")
        return payload, 404

    @app.errorhandler(405)
    def handle_405(exc):
        payload, _status = error_body("ERR_INVALID_REQUEST", "method not allowed on this path")
        return payload, 405

    @app.errorhandler(400)
    def handle_400(exc):
        payload, _status = error_body("ERR_INVALID_REQUEST", "malformed request")
        return payload, 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("unhandled error")
        payload, _status = error_body(
            "ERR_INVALID_REQUEST", "unhandled server error: %s" % exc)
        return payload, 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
