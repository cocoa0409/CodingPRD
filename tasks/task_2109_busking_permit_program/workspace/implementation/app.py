"""Busking Permit Program API — Flask entry point.

Storage is in-memory only and nothing is seeded: every entity a test needs is
built through the declared API surface.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_body

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_unknown_route(_err):
    return error_body("ERR_INVALID_REQUEST", "Unknown route", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_body("ERR_INVALID_REQUEST", "Method not allowed for this route", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_body("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 400)


from routes import (applications, auditions, bookings, clock, closures,  # noqa: E402
                    complaints, invoices, lottery, ops, performers, permits,
                    pitches, readings, zones)

for module in (zones, pitches, performers, applications, auditions, permits,
               invoices, lottery, bookings, readings, complaints, closures,
               ops, clock):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
