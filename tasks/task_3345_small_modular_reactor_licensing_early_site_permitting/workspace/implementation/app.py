"""Flask app bootstrap for the SMR Licensing & Early Site Permitting API."""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from store import error_response, init_clock


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    init_clock()

    from routes_dca import bp as bp_dca
    from routes_sar_rai import bp as bp_sar_rai
    from routes_programs import bp as bp_programs
    from routes_vendors import bp as bp_vendors
    from routes_permits import bp as bp_permits
    from routes_subscriptions import bp as bp_subs
    from routes_workforce import bp as bp_workforce
    from routes_clock import bp as bp_clock

    for bp in (bp_dca, bp_sar_rai, bp_programs, bp_vendors, bp_permits,
               bp_subs, bp_workforce, bp_clock):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_e):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(400)
    def _bad_request(_e):
        return error_response(ERR_VALIDATION, "malformed request", 400)

    @app.errorhandler(Exception)
    def _unhandled(e):
        app.logger.exception("unhandled: %s", e)
        return error_response(ERR_VALIDATION, f"internal error: {type(e).__name__}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
