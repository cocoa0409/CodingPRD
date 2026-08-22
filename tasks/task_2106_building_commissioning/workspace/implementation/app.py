"""Building Commissioning API — entry point."""
import os
import sys
import threading

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ApiError, error_response  # noqa: E402
from routes.baselines import bp as baselines_bp  # noqa: E402
from routes.checklists import bp as checklists_bp  # noqa: E402
from routes.credits import bp as credits_bp  # noqa: E402
from routes.deferred_tests import bp as deferred_tests_bp  # noqa: E402
from routes.deliverables import bp as deliverables_bp  # noqa: E402
from routes.equipment import bp as equipment_bp  # noqa: E402
from routes.functional_tests import bp as functional_tests_bp  # noqa: E402
from routes.issues import bp as issues_bp  # noqa: E402
from routes.plans import bp as plans_bp  # noqa: E402
from routes.projects import bp as projects_bp  # noqa: E402
from routes.requirements import bp as requirements_bp  # noqa: E402
from routes.submittals import bp as submittals_bp  # noqa: E402

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for blueprint in (
    projects_bp, requirements_bp, plans_bp, submittals_bp, equipment_bp,
    checklists_bp, functional_tests_bp, issues_bp, deferred_tests_bp,
    deliverables_bp, credits_bp, baselines_bp,
):
    app.register_blueprint(blueprint)

_REQUEST_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _REQUEST_LOCK.acquire()


@app.teardown_request
def _release_lock(exc=None):
    try:
        _REQUEST_LOCK.release()
    except RuntimeError:
        pass


@app.errorhandler(ApiError)
def _handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _handle_http_error(exc):
    if exc.code == 404:
        return error_response("ERR_PROJECT_NOT_FOUND", "Resource not found.", 404)
    if exc.code == 405:
        return error_response("ERR_VALIDATION", "Method not allowed.", 400)
    return error_response("ERR_VALIDATION", exc.description or "Bad request.",
                          exc.code if exc.code and exc.code < 500 else 400)


@app.errorhandler(Exception)
def _handle_unexpected(exc):  # pragma: no cover
    app.logger.exception("Unhandled error")
    return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc, 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
