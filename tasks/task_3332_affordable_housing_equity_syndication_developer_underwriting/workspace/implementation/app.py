"""Affordable Housing Equity Syndication API — application entry point.

The store starts empty on every boot: nothing is seeded, preloaded or
registered here.  The only startup state is the logical clock's pinned default
instant (2026-09-01T00:00:00Z).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
import store
from routes_admin import bp as admin_bp
from routes_allocations import bp as allocations_bp
from routes_calls import bp as calls_bp
from routes_exits import bp as exits_bp
from routes_funds import bp as funds_bp
from routes_guarantees import bp as guarantees_bp
from routes_projects import bp as projects_bp
from routes_reviews import bp as reviews_bp
from routes_subscriptions import bp as subscriptions_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (admin_bp, funds_bp, subscriptions_bp, projects_bp, allocations_bp,
                  calls_bp, guarantees_bp, reviews_bp, exits_bp):
    app.register_blueprint(blueprint)


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    return response.error(errors.ERR_INVALID_REQUEST,
                          exc.description or exc.name, exc.code or 500)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    app.logger.exception("unhandled error")
    return response.error(errors.ERR_INVALID_REQUEST, str(exc), 500)


@app.get("/health")
def health():
    return response.ok({"status": "ok"}, 200)


def main():
    store.reset()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
