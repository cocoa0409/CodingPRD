"""Entry point: Flask app assembly and error handling."""
import os

from flask import Flask

from db import db
from errors import ApiError, ERR_NOT_FOUND
from response import error_response
import routes_clock
import routes_editors
import routes_pages
import routes_revisions
import routes_disputes
import routes_protection
import routes_vandalism
import routes_campaigns
import routes_banners
import routes_donations
import routes_grants
import routes_legal
import routes_transparency

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (routes_clock, routes_editors, routes_pages, routes_revisions,
               routes_disputes, routes_protection, routes_vandalism,
               routes_campaigns, routes_banners, routes_donations,
               routes_grants, routes_legal, routes_transparency):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error_response("ERR_INTERNAL", str(exc), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
