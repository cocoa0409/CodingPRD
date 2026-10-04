"""Flask entry point: blueprint registration and envelope-shaped error handlers."""

import os

from flask import Flask

from util import ApiError, error_response

app = Flask(__name__)
try:
    app.json.sort_keys = False
except Exception:
    pass

import routes_admin
import routes_campaigns
import routes_chapters
import routes_complaints
import routes_governance
import routes_households
import routes_providers
import routes_publications

for module in (
    routes_admin,
    routes_households,
    routes_providers,
    routes_complaints,
    routes_governance,
    routes_publications,
    routes_chapters,
    routes_campaigns,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error)


@app.errorhandler(404)
def handle_not_found(_error):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_error):
    return error_response(ApiError("ERR_NOT_FOUND", 405, "Method not allowed for this resource"))


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return error_response(error)
    return error_response(ApiError("ERR_INTERNAL", 500, "Internal server error"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
