import os

from flask import Flask, jsonify

import engine
import clock
from util import parse_iso, fmt_iso
from errors import ApiError, err_invalid_request
from middleware import require_roles, body_json, require_fields
from response import success_object, error_body

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_registrars
import routes_schedules
import routes_domains
import routes_nameservers
import routes_transfers
import routes_misc

app.register_blueprint(routes_registrars.bp, url_prefix="/registry")
app.register_blueprint(routes_schedules.bp, url_prefix="/registry")
app.register_blueprint(routes_domains.bp, url_prefix="/registry")
app.register_blueprint(routes_nameservers.bp, url_prefix="/registry")
app.register_blueprint(routes_transfers.bp, url_prefix="/registry")
app.register_blueprint(routes_misc.bp, url_prefix="/registry")


@app.post("/registry/_clock/set_current_utc")
def set_clock():
    require_roles("RegistryAdmin")
    data = body_json()
    require_fields(data, ["to_iso8601"])
    try:
        target = parse_iso(data["to_iso8601"])
    except Exception:
        raise err_invalid_request("to_iso8601 must be an ISO-8601 datetime")
    current = engine.advance_clock(target)
    return success_object({"current_utc": fmt_iso(current)})


@app.errorhandler(ApiError)
def handle_api_error(err):
    body, status = error_body(err)
    return jsonify(body), status


@app.errorhandler(404)
def handle_404(e):
    body, status = error_body(ApiError("ERR_NOT_FOUND", "Resource not found", 404))
    return jsonify(body), status


@app.errorhandler(405)
def handle_405(e):
    body, status = error_body(ApiError("ERR_NOT_FOUND", "Resource not found", 404))
    return jsonify(body), status


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        body, status = error_body(e)
        return jsonify(body), status
    body, status = error_body(ApiError("ERR_INVALID_REQUEST", str(e), 400))
    return jsonify(body), status


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
