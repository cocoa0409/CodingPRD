"""Pool Route Brokerage API -- entry point, error handlers, route registration."""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from responses import error_response
from routes.accounts import bp as accounts_bp
from routes.attrition import bp as attrition_bp
from routes.billing import bp as billing_bp
from routes.clock import bp as clock_bp
from routes.deals import bp as deals_bp
from routes.escrow import bp as escrow_bp
from routes.licenses import bp as licenses_bp
from routes.listings import bp as listings_bp
from routes.parties import bp as parties_bp
from routes.profiles import bp as profiles_bp
from routes.settlements import bp as settlements_bp
from routes.valuations import bp as valuations_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (clock_bp, profiles_bp, parties_bp, listings_bp, accounts_bp, billing_bp,
                      valuations_bp, deals_bp, escrow_bp, licenses_bp, attrition_bp,
                      settlements_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        return error_response("ERR_VALIDATION", exc.description or "Bad request",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return error_response("ERR_INTERNAL", "Unexpected server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
