"""Flask bootstrap: error handlers + route registration.

Storage is entirely in-memory (store.DB); every fresh process boot starts with
an empty store and the logical clock at 2026-09-01T00:00:00Z. No seeding, no
persistence, no wall-clock reads.
"""
import os
import traceback

from flask import Flask

import routes_agencies
import routes_clock
import routes_collections
import routes_foia
import routes_pulls
import routes_repros
import routes_researchers
import routes_restrictions
import routes_reviews
import routes_schedules
import routes_transfers
from envelope import error_response
from errors import ApiError

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

for bp in (
    routes_agencies.bp,
    routes_schedules.bp,
    routes_transfers.bp,
    routes_collections.bp,
    routes_reviews.bp,
    routes_researchers.bp,
    routes_pulls.bp,
    routes_repros.bp,
    routes_foia.bp,
    routes_restrictions.bp,
    routes_clock.bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_not_found(_e):
    # Unmatched route: keep the standard error envelope shape.
    return error_response(ApiError("ERR_INVALID_REQUEST", 404, "route not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_e):
    return error_response(
        ApiError("ERR_INVALID_REQUEST", 405, "method not allowed")
    )


@app.errorhandler(Exception)
def handle_unexpected(e):
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST", 500, "internal error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
