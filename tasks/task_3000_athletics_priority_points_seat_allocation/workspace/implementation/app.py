"""Athletics Priority Points and Seat Allocation Service.

A single Flask process holding every collection in memory.  Nothing is seeded,
nothing is persisted: a restart is a factory reset, which is exactly what the
per-test isolation of the harness expects.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import auth
import clock
import envelope
import routes_assignments
import routes_disputes
import routes_donors
import routes_events
import routes_recalc
import routes_sections
import routes_transfers
import validation as v
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

app.register_blueprint(routes_donors.bp)
app.register_blueprint(routes_recalc.bp)
app.register_blueprint(routes_disputes.bp)
app.register_blueprint(routes_transfers.bp)
app.register_blueprint(routes_sections.bp)
app.register_blueprint(routes_events.bp)
app.register_blueprint(routes_assignments.bp)


# ---------------------------------------------------------------------------
# The logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------
@app.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require(auth.EVERY_ROLE)
    body = v.body_dict()
    instant = v.instant_field(body, "to_iso8601")
    clock.CLOCK.set(instant)
    return envelope.ok({})


# ---------------------------------------------------------------------------
# Error handling: every failure leaves through the standard error envelope
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(error):
    return envelope.error_response(error)


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    status = error.code or 500
    if status == 404:
        error_id = "ERR_INVALID_REQUEST"
    elif status == 405:
        error_id = "ERR_INVALID_REQUEST"
    elif status in (400, 415):
        error_id = "ERR_INVALID_REQUEST"
    else:
        error_id = "ERR_INVALID_REQUEST"
    body = envelope.error_body(error_id, error.description or error.name)
    return jsonify(body), status


@app.errorhandler(Exception)
def handle_unexpected(error):
    body = envelope.error_body("ERR_INVALID_REQUEST",
                               "unexpected server error: %s" % error)
    return jsonify(body), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
