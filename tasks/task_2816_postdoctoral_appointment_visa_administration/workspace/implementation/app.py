"""Flask entry point: blueprint registration, error handling and the launcher.

The in-memory store starts completely empty on every boot; nothing is seeded here.
"""
import os

from flask import Flask, g

import routes_appointments
import routes_documents
import routes_registry
import routes_reviews
import routes_security
import routes_visa
from envelope import error_response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes_registry.bp)
app.register_blueprint(routes_appointments.bp)
app.register_blueprint(routes_visa.bp)
app.register_blueprint(routes_documents.bp)
app.register_blueprint(routes_security.bp)
app.register_blueprint(routes_reviews.bp)


@app.before_request
def reset_touch_ledger():
    """One version bump per record per request (PRD 2.4)."""
    g.touched_records = set()


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def handle_not_found(error):
    return error_response("ERR_NOT_FOUND", "No such route.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(error):
    return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route.", 405)


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return handle_api_error(error)
    app.logger.exception("unhandled error")
    return error_response("ERR_INTERNAL", "Unexpected server error: %s" % error, 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
