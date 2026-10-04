"""Election Night Race Calling API — Flask bootstrap (api_prefix "")."""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_events
import routes_counties
import routes_contests
import routes_feeds
import routes_stringers
import routes_reports
import routes_calls
import routes_recounts
import routes_coverage
import routes_media

for module in (
    routes_events, routes_counties, routes_contests, routes_feeds,
    routes_stringers, routes_reports, routes_calls, routes_recounts,
    routes_coverage, routes_media,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(err):
    from errors import ApiError as _AE
    return error_response(_AE("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(err):
    from errors import ApiError as _AE
    return error_response(_AE("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    from errors import ApiError as _AE
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(_AE("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
