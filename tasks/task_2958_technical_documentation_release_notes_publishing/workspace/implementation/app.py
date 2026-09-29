"""Docs Release Publishing API - Flask entry point.

State lives only in process memory (see core.Store) and starts completely
empty on every boot: no entity is ever seeded, preloaded or hardcoded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, error_response
import routes_change
import routes_core
import routes_docset
import routes_loc
import routes_plan
import routes_signoff
import routes_term
import routes_topic

app = Flask(__name__)
app.url_map.strict_slashes = False
try:
    app.json.sort_keys = False
except Exception:
    app.config["JSON_SORT_KEYS"] = False

for module in (routes_core, routes_plan, routes_topic, routes_signoff,
               routes_docset, routes_change, routes_loc, routes_term):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(HTTPException)
def handle_http_error(error):
    status = error.code or 500
    if status == 404:
        return error_response("ERR_INVALID_REQUEST", "No such route.", 404)
    if status == 405:
        return error_response("ERR_INVALID_REQUEST",
                              "That method is not allowed on this route.", 405)
    return error_response("ERR_INVALID_REQUEST",
                          error.description or "Request could not be processed.", status)


@app.errorhandler(Exception)
def handle_unexpected(error):
    return error_response("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
