"""Entry point.

The evaluator's entire contract is `bash start.sh` from ./implementation/, which
execs this module. The server binds 0.0.0.0 and listens on $PORT (default 10000).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

from errors import ApiError
from response import error
from routes.claims import bp as claims_bp
from routes.core import bp as core_bp
from routes.coverage import bp as coverage_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(core_bp)
app.register_blueprint(coverage_bp)
app.register_blueprint(claims_bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    from errors import ERR_RESOURCE_NOT_FOUND

    return error(ERR_RESOURCE_NOT_FOUND, "The requested path does not exist.", 404)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    from errors import ERR_INVALID_REQUEST

    return error(ERR_INVALID_REQUEST, "The HTTP method is not allowed for this path.", 400)


@app.errorhandler(500)
def handle_internal_error(exc):
    from errors import ERR_INVALID_REQUEST

    app.logger.exception("unhandled error")
    return error(ERR_INVALID_REQUEST, "The request could not be processed.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)