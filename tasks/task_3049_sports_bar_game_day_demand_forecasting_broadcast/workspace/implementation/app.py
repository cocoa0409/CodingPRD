"""Sports Bar Game-Day platform — Flask entry point."""
import os
from datetime import datetime

from flask import Flask, jsonify

import db
from errors import ApiError, invalid_request, not_found
from util import success, error_body, auth, body, require, parse_dt, iso_ts
import services

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err)


@app.errorhandler(404)
def handle_404(err):
    return error_body(not_found("Resource does not exist"))


@app.errorhandler(405)
def handle_405(err):
    return error_body(not_found("Resource does not exist"))


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, ApiError):
        return error_body(err)
    return error_body(invalid_request(str(err)))


from util import serialize, serialize_list  # re-exported for route modules


# ---------------------------------------------------------------- clock

@app.post("/api/_clock/set_current_utc")
def set_clock():
    auth(["PlatformAdmin"])
    data = body()
    to_iso8601 = require(data, "to_iso8601")
    dt = parse_dt(to_iso8601, "to_iso8601")
    db.set_now(dt)
    services.on_clock_change()
    return success({"current_utc": iso_ts(db.now())})


# Register route blueprints
from routes_core import bp as core_bp            # noqa: E402
from routes_guests import bp as guests_bp        # noqa: E402
from routes_checks import bp as checks_bp        # noqa: E402
from routes_staffing import bp as staffing_bp    # noqa: E402
from routes_games import bp as games_bp          # noqa: E402

app.register_blueprint(core_bp)
app.register_blueprint(guests_bp)
app.register_blueprint(checks_bp)
app.register_blueprint(staffing_bp)
app.register_blueprint(games_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
