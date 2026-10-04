"""Battery Platform Ecosystem API — entry point.

Registers all route blueprints under the /battery-ecosystem prefix plus the
platform logical clock endpoint POST /_clock/set_current_utc (deliberately
outside the prefix). Storage is in-memory only; nothing is seeded at startup.
"""
import os

from flask import Flask

import db
from errors import ApiError
from helpers import authorize, body, error_response, ok_object, parse_dt, req_field
from routes import assets, distribution, packs, platforms, safety, tools, warranty
from services import apply_sunset_transitions

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (platforms, packs, tools, assets, warranty, distribution, safety):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def _handle_405(_err):
    return error_response(ApiError("ERR_NOT_FOUND", "Method not allowed"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    return error_response(ApiError("ERR_VALIDATION", str(err), 500))


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize(["PlatformAdmin"])
    data = body()
    to_iso8601 = parse_dt(req_field(data, "to_iso8601"), "to_iso8601")
    db.set_clock(to_iso8601)
    apply_sunset_transitions()
    return ok_object({})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
