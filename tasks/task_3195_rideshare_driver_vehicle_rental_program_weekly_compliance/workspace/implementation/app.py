"""Rideshare Driver Vehicle Rental Program & Weekly Compliance API.

Entry point: registers every route group, wires the authentication/RBAC gate and
the standard error envelope.  The store is in-memory and starts empty on every
boot -- nothing is seeded here or anywhere else at import time.
"""

import os
import re

from flask import Flask
from werkzeug.exceptions import HTTPException

import middleware
from errors import ApiError
from response import error_response, request_id

import routes_agreements
import routes_drivers
import routes_facts
import routes_maintenance
import routes_payments
import routes_purchases
import routes_vehicles
import routes_weeks

app = Flask(__name__)
app.url_map.strict_slashes = False

# Order matters: the two-segment literal actions must be tried before the
# sub-collection patterns they could be mistaken for.
_BLUEPRINTS = (
    routes_drivers.bp,
    routes_vehicles.bp,
    routes_agreements.bp,
    routes_weeks.bp,
    routes_maintenance.bp,
    routes_payments.bp,
    routes_purchases.bp,
    routes_facts.bp,
)

for blueprint in _BLUEPRINTS:
    app.register_blueprint(blueprint)


def _template(name):
    """Normalise a Werkzeug rule to the catalogue's shape: every path variable
    is written `{id}`, which is what the RBAC matrix and the body schemas key on."""
    return re.sub(r"<(?:[^:<>]+:)?[^<>]+>", "{id}", name).rstrip("/")


# Build the route table: (template, method, rule) with static rules first so an
# exact literal segment is preferred over a variable one at the same depth.
_ROUTE_TABLE = []
for rule in app.url_map.iter_rules():
    if rule.endpoint == "static":
        continue
    template = _template(str(rule.rule))
    for method in sorted(rule.methods):
        if method in ("HEAD", "OPTIONS"):
            continue
        _ROUTE_TABLE.append((template, method, rule))
_ROUTE_TABLE.sort(key=lambda item: (0 if "{" not in item[0] else 1, -len(item[0])))


@app.before_request
def _gate():
    from flask import request

    if request.method == "OPTIONS":
        return None
    # Werkzeug has already matched when a rule exists; when it has not (an
    # unknown path, or a known path with an unwelcome method) the request is
    # not addressable at all and is reported as a missing resource.
    if request.url_rule is None:
        return error_response("ERR_NOT_FOUND",
                              "No route matches %s %s." % (request.method, request.path), 404)
    template = _template(str(request.url_rule.rule))
    role, _user_id = middleware.authenticate()
    middleware.authorize(role, request.method, template)
    return None


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    if exc.code == 405:
        return error_response("ERR_NOT_FOUND", "Method not allowed for this path.", 404)
    return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.", exc.code or 400)


@app.errorhandler(Exception)
def _handle_unexpected(exc):
    return error_response("ERR_INVALID_REQUEST", str(exc) or "Request failed.", 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))