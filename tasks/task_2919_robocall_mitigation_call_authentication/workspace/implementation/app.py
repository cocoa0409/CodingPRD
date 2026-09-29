"""Robocall Mitigation & Call Authentication API (Flask).

All state lives in process memory (see store.py). Nothing is seeded at
startup and nothing is written to disk.
"""
import os
import traceback

from flask import Flask, jsonify

import envelope
import errors
import views_attest
import views_blocking
import views_cert
import views_clock
import views_customer
import views_enforce
import views_notice
import views_number
import views_plan
import views_provider
import views_report
import views_traceback
import views_traffic

BLUEPRINTS = (
    views_clock.bp,
    views_provider.bp,
    views_cert.bp,
    views_plan.bp,
    views_customer.bp,
    views_number.bp,
    views_attest.bp,
    views_traffic.bp,
    views_traceback.bp,
    views_notice.bp,
    views_blocking.bp,
    views_enforce.bp,
    views_report.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        body = envelope.error_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        body = envelope.error_body(errors.ERR_INVALID_REQUEST,
                                  "No such resource path")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_bad_method(exc):
        body = envelope.error_body(errors.ERR_INVALID_REQUEST,
                                  "Method not allowed for this path")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_bad_request(exc):
        body = envelope.error_body(errors.ERR_INVALID_REQUEST,
                                  "Malformed request")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, errors.ApiError):
            return handle_api_error(exc)
        traceback.print_exc()
        body = envelope.error_body("ERR_INTERNAL", str(exc))
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
