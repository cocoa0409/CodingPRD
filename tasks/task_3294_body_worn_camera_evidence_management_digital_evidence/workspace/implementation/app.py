import os

from flask import Flask, jsonify

from errors import ApiError
from helpers import error_response, make_meta

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_misc
import routes_roster_fleet
import routes_evidence
import routes_cases_sharing
import routes_redaction_ledgers

app.register_blueprint(routes_misc.bp)
app.register_blueprint(routes_roster_fleet.bp)
app.register_blueprint(routes_evidence.bp)
app.register_blueprint(routes_cases_sharing.bp)
app.register_blueprint(routes_redaction_ledgers.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    from errors import err_not_found
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    from errors import err_not_found
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    app.logger.exception("unexpected error")
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
