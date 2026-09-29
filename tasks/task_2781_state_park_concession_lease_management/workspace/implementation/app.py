"""State Park Concession Lease Management API — entry point.

Storage is in-memory only and starts completely empty: no entity is seeded,
preloaded or hardcoded at startup. Every row is created through a declared
endpoint.
"""
import os

from flask import Flask

from envelope import fail
from errors import ApiError
from router import ROUTES

import routes.clock            # noqa: F401
import routes.parks            # noqa: F401
import routes.opportunities    # noqa: F401
import routes.prospectuses     # noqa: F401
import routes.offerors         # noqa: F401
import routes.proposals        # noqa: F401
import routes.leases           # noqa: F401
import routes.bonds            # noqa: F401
import routes.improvements     # noqa: F401
import routes.plans            # noqa: F401
import routes.reports          # noqa: F401
import routes.reconciliations  # noqa: F401
import routes.audits           # noqa: F401
import routes.compliance       # noqa: F401

PREFIXES = ("/api/v1", "")

app = Flask(__name__)
app.url_map.strict_slashes = False


def _register():
    seen = set()
    for rule, methods, func in ROUTES:
        for index, prefix in enumerate(PREFIXES):
            endpoint = "%s_%d" % (func.__name__, index)
            if endpoint in seen:
                continue
            seen.add(endpoint)
            app.add_url_rule(prefix + rule, endpoint, func, methods=list(methods))


_register()


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return fail(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _handle_404(exc):
    return fail("ERR_NOT_FOUND", "No such route", 404)


@app.errorhandler(405)
def _handle_405(exc):
    return fail("ERR_METHOD_NOT_ALLOWED", "Method not allowed for this route", 405)


@app.errorhandler(400)
def _handle_400(exc):
    return fail("ERR_INVALID_REQUEST", "Malformed request", 400)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return fail(exc.error_id, exc.message, exc.http_status)
    app.logger.exception("unhandled error")
    return fail("ERR_INVALID_REQUEST", "Unhandled server error: %s" % (exc,), 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
