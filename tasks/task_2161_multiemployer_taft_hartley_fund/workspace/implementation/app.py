"""Multiemployer (Taft-Hartley) Benefit Fund Administration API."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import api_audit
import api_core
import api_governance
import api_reads
import api_reports
import api_withdrawal
from envelope import error_body
from errors import ApiError
from store import db


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(api_reads.bp)
    app.register_blueprint(api_core.bp)
    app.register_blueprint(api_reports.bp)
    app.register_blueprint(api_audit.bp)
    app.register_blueprint(api_withdrawal.bp)
    app.register_blueprint(api_governance.bp)

    @app.before_request
    def _lock():
        db.lock.acquire()

    @app.teardown_request
    def _unlock(exc=None):
        try:
            db.lock.release()
        except RuntimeError:
            pass

    @app.errorhandler(ApiError)
    def _api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 404:
            return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 404
        if err.code == 405:
            return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed.")), 405
        if err.code == 400:
            return jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request.")), 400
        return jsonify(error_body("ERR_INVALID_REQUEST", err.description or "Request failed")), err.code

    @app.errorhandler(Exception)
    def _unexpected(err):
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INVALID_REQUEST", "Internal error: %s" % err)), 500

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
