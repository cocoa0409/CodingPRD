"""Interscholastic Athletics Eligibility & Scheduling API."""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response, _meta
import r_school
import r_student
import r_credential
import r_season
import r_case
import r_contest
import r_transport
import r_injury
import r_clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for module in (r_school, r_student, r_credential, r_season, r_case,
                   r_contest, r_transport, r_injury, r_clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {
                "error_id": "ERR_INVALID_REQUEST" if err.code == 400 else "ERR_NOT_FOUND",
                "message": err.description or str(err),
            },
        }
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def _unhandled(err):
        body = {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
        }
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
