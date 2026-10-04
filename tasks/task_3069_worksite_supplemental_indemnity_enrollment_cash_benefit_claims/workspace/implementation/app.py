"""Application entry point: Flask app, auth before_request, error handlers, route registration."""
import os
import sys

from flask import Flask, jsonify

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import errors as E
from errors import ApiError
from middleware import authenticate
from response import error_response

app = Flask(__name__)


@app.before_request
def _auth():
    # Only enforce auth on API paths handled by this app; the before_request runs
    # for everything, so scope it to our blueprints by skipping the clock path
    # inside authenticate().
    uid, role = authenticate()
    # stash for handlers via flask.g? Simpler: attach to request context
    from flask import g
    g.user_id = uid
    g.role = role


@app.errorhandler(ApiError)
def _api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _not_found(_e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _method_not_allowed(_e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def _unhandled(exc):
    # Never leak a bare 500 HTML page; surface as a structured error.
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.message, exc.http_status)
    app.logger.exception("unhandled")
    return error_response("ERR_INVALID_REQUEST", str(exc) or "Internal error", 400)


def _wrap(handler):
    """Inject (role, user_id) from flask.g into handlers that declare them."""
    import functools
    import inspect
    sig = inspect.signature(handler)
    params = list(sig.parameters.keys())

    @functools.wraps(handler)
    def wrapper(**kwargs):
        from flask import g
        args = []
        for name in params:
            if name == "role":
                args.append(g.get("role"))
            elif name == "user_id":
                args.append(g.get("user_id"))
            else:
                args.append(kwargs[name])
        return handler(*args)

    return wrapper


def register(bp):
    """Register a blueprint, wrapping each view to inject role/user_id."""
    app.register_blueprint(bp)
    for endpoint, view_func in list(app.view_functions.items()):
        if endpoint.startswith(bp.name + "."):
            app.view_functions[endpoint] = _wrap(view_func)


# Import and register blueprints
from routes import clock_routes  # noqa: E402
from routes import employer_groups  # noqa: E402
from routes import benefit_counselors  # noqa: E402
from routes import enrollment_campaigns  # noqa: E402
from routes import policy_series  # noqa: E402
from routes import employees  # noqa: E402
from routes import policies  # noqa: E402
from routes import claims  # noqa: E402
from routes import claim_documents  # noqa: E402
from routes import wellness_benefits  # noqa: E402
from routes import payroll  # noqa: E402

# clock routes do NOT take role/user_id — register directly
app.register_blueprint(clock_routes.bp)

for _bp in (
    employer_groups.bp,
    benefit_counselors.bp,
    enrollment_campaigns.bp,
    policy_series.bp,
    employees.bp,
    policies.bp,
    claims.bp,
    claim_documents.bp,
    wellness_benefits.bp,
    payroll.bp,
):
    register(_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
