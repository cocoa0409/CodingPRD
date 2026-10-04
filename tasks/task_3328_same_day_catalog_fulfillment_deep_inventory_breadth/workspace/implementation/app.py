"""Flask application entry point.

Boots an empty world: the in-memory store is constructed fresh on import and
nothing is seeded, so a per-test reboot via start.sh always begins from a
blank state. The logical clock starts at 2026-09-01T00:00:00Z.

Error mapping keeps the two request-validation priorities (PRD section 2.9)
ahead of everything else: authentication, then authorization, then the
domain-specific rejections raised by the service layer.
"""

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from db import db
from errors import ApiError
from response import error_body

import views_catalog
import views_core
import views_orders
import views_square

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_body(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    return error_body("ERR_INVALID_REQUEST", exc.description or "Invalid request.",
                      exc.code or 400)


@app.errorhandler(Exception)
def _unexpected(exc):
    return error_body("ERR_INVALID_REQUEST", str(exc), 400)


views_core.register(app)
views_catalog.register(app)
views_orders.register(app)
views_square.register(app)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)