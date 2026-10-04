"""Meat & Poultry Inspection API — Flask bootstrap.

Mounts every resource under /inspection plus the platform logical-clock
endpoint POST /_clock/set_current_utc (outside the prefix, PRD §2.4). The
store starts completely empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

import store
from envelope import error_response, get_body, success_object
from errors import ApiError, raise_err, ERR_INVALID_REQUEST

import routes_appeals
import routes_assignments
import routes_enforcement
import routes_establishments
import routes_grants
import routes_humane
import routes_inspectors
import routes_labels
import routes_nrs
import routes_pathogens
import routes_recalls
import routes_windows

app = Flask(__name__)

for module in (
    routes_establishments,
    routes_grants,
    routes_inspectors,
    routes_windows,
    routes_assignments,
    routes_nrs,
    routes_enforcement,
    routes_humane,
    routes_pathogens,
    routes_labels,
    routes_recalls,
    routes_appeals,
):
    app.register_blueprint(module.bp)


# --- Platform logical clock (outside the /inspection prefix) ------------------

@app.post("/_clock/set_current_utc")
def set_current_utc():
    from authz import require_roles
    from validate import require_present

    require_roles("ProgramAdministrator")
    body = get_body()
    to_iso8601 = require_present(body, "to_iso8601")
    if not isinstance(to_iso8601, str):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 timestamp string")
    try:
        echo = store.clock_set(to_iso8601)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 timestamp")
    return success_object({"current_utc": echo})


# --- Error handling: every failure uses the §2.2 error envelope ---------------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    # Unmatched route — not reachable via any PRD §4 path.
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
