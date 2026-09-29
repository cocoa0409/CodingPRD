"""Private-Label Grocery Brand Development API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import iso, now, set_clock
from errors import ApiError
from middleware import ALL_ROLES, Field, authenticate, validate_body
from response import error_response, object_response
from routes.artwork import bp as artwork_bp
from routes.costs import bp as costs_bp
from routes.items import bp as items_bp
from routes.programs import bp as programs_bp
from routes.specs import bp as specs_bp
from routes.studies import bp as studies_bp
from routes.suppliers import bp as suppliers_bp


app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(programs_bp)
app.register_blueprint(suppliers_bp)
app.register_blueprint(items_bp)
app.register_blueprint(costs_bp)
app.register_blueprint(studies_bp)
app.register_blueprint(artwork_bp)
app.register_blueprint(specs_bp)


@app.post("/_clock/set_current_utc")
def set_current_utc():
    """The logical clock of PRD 2.5.  Inert with respect to every entity."""
    authenticate(ALL_ROLES)
    body = validate_body({"current_utc": Field("datetime", required=True)})
    set_clock(body["current_utc"])
    return object_response({"current_utc": iso(now())})


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.status)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 404:
        return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
    if exc.code == 405:
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "The method is not allowed for this path.", 405
        )
    if exc.code and exc.code < 500:
        return error_response("ERR_INVALID_REQUEST", exc.description or "Malformed request.", 422)
    return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - defensive
    return error_response("ERR_INTERNAL", "An unexpected error occurred.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
