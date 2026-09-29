"""Public Safety Radio System Interoperability API.

Flask application factory and error plumbing. Storage is in-memory only: a
fresh process starts with every collection empty and the logical clock parked
at 2026-08-01T00:00:00Z. Nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import agencies
from routes import campaigns
from routes import changes
from routes import keysets
from routes import misc
from routes import patches
from routes import siteevents
from routes import sites
from routes import talkgroups
from routes import talkpaths
from routes import templates
from routes import units

BLUEPRINTS = (
    agencies.bp,
    sites.bp,
    templates.bp,
    changes.bp,
    units.bp,
    keysets.bp,
    campaigns.bp,
    talkgroups.bp,
    patches.bp,
    siteevents.bp,
    talkpaths.bp,
    misc.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        if status == 404:
            error_id = "ERR_INVALID_REQUEST"
            message = "The requested route does not exist."
        elif status == 405:
            error_id = "ERR_INVALID_REQUEST"
            message = "The HTTP method is not allowed for this route."
        elif status >= 500:
            error_id = "ERR_INVALID_REQUEST"
            message = "The server could not complete the request."
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = exc.description or "The request payload is malformed or invalid."
            status = 400
        return response.error(error_id, message, status)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        return response.error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
