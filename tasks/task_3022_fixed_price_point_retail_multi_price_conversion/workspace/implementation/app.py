"""Entry point.

The store is empty at import: nothing below seeds, preloads or registers an
entity. Every row the process ever holds was built through a declared
endpoint, and every row dies with the process, so each per-test reboot under
`prd-bench-local-run --isolation per-test-server` starts genuinely clean.

Routing is hand-rolled rather than Flask's `@app.route`, so that path
parameters are extracted inside the request context and the auth checks of
PRD §2.1 can run before any identifier is resolved (PRD §2.8).
"""

import os
import sys
import traceback

from flask import Flask, request

# Make sibling modules importable regardless of the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common  # noqa: E402
import routes  # noqa: E402,F401  (registers every view via @route)

from errors import ApiError, ERR_METHOD_NOT_ALLOWED, ERR_NOT_FOUND  # noqa: E402
from response import error_response  # noqa: E402

app = Flask(__name__)
app.json.sort_keys = False


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def dispatch(path):
    try:
        status, handler, roles, params = common.match_view(request.method, path)

        if status == "no_match":
            raise ApiError(ERR_NOT_FOUND)
        if status == "method_not_allowed":
            raise ApiError(ERR_METHOD_NOT_ALLOWED)

        # PRD §2.1 — both auth checks run before any resource lookup.
        common.check_auth(roles)

        # PRD §2.8 — path identifiers resolve left to right, in the order the
        # path declares them, because each handler does its own lookups in
        # that order before touching any business rule.
        result = handler(**params)
        return result
    except ApiError as exc:
        return error_response(exc.error_id, exc.message, exc.http_status)
    except Exception:  # pragma: no cover - defensive
        traceback.print_exc()
        return error_response("ERR_INTERNAL", "Internal server error.", 500)


@app.errorhandler(404)
def not_found(_):
    return error_response(ERR_NOT_FOUND, "The requested path does not resolve.", 404)


@app.errorhandler(405)
def method_not_allowed(_):
    return error_response(ERR_METHOD_NOT_ALLOWED, "The HTTP method is not allowed on this path.", 405)


@app.errorhandler(Exception)
def unhandled(_):  # pragma: no cover - defensive
    return error_response("ERR_INTERNAL", "Internal server error.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)