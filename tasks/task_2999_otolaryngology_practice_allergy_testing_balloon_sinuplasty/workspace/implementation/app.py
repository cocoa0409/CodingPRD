"""Otolaryngology practice API — allergy testing, immunotherapy, balloon sinuplasty.

Storage is in-memory only and nothing is seeded: every row is built through the
declared endpoints. A restart wipes all state.
"""
import os
import sys
import traceback

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import envelope
import r_allergy
import r_assets
import r_audiology
import r_immuno
import r_registry
import r_schedule
import r_sinuplasty
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(r_registry.bp)
    app.register_blueprint(r_allergy.bp)
    app.register_blueprint(r_immuno.bp)
    app.register_blueprint(r_sinuplasty.bp)
    app.register_blueprint(r_audiology.bp)
    app.register_blueprint(r_assets.bp)
    app.register_blueprint(r_schedule.bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        body = envelope.error_body(
            "ERR_INVALID_REQUEST",
            err.description or "The request could not be routed as declared.",
        )
        return jsonify(body), err.code

    @app.errorhandler(Exception)
    def _unexpected(err):
        traceback.print_exc(file=sys.stderr)
        body = envelope.error_body("ERR_INVALID_REQUEST", str(err))
        return jsonify(body), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=True)
