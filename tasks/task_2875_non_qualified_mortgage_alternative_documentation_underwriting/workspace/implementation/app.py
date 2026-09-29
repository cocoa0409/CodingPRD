"""Non-QM alternative-documentation underwriting API (in-memory, stateless boot)."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, respond_error
import routes_audit
import routes_borrower
import routes_config
import routes_exception
import routes_fees
import routes_loanfile
import routes_pool
import routes_valuation
import routes_worksheet


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    for module in (routes_config, routes_borrower, routes_loanfile, routes_worksheet,
                   routes_valuation, routes_fees, routes_exception, routes_audit,
                   routes_pool):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return respond_error(error)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return respond_error(ApiError("ERR_NOT_FOUND", "resource not found"))
        if error.code == 405:
            return respond_error(ApiError("ERR_NOT_FOUND", "method not allowed"))
        if error.code in (400, 415):
            return respond_error(ApiError("ERR_INVALID_REQUEST", "malformed request body"))
        return respond_error(ApiError("ERR_INVALID_REQUEST", error.description or "error"))

    @app.errorhandler(Exception)
    def _unhandled(error):
        wrapped = ApiError("ERR_INVALID_REQUEST", "unhandled server error: %s" % error)
        wrapped.http_status = 500
        return respond_error(wrapped)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
