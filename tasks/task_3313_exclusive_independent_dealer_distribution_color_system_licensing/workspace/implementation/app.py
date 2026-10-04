"""Application entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError, err_not_found, err_invalid_request
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import regions
    import catalog
    import dealers
    import equipment
    import licenses
    import orders
    import contractors
    import coop
    import channel_events
    import formulation
    import ops

    for module in (regions, catalog, dealers, equipment, licenses, orders,
                   contractors, coop, channel_events, formulation, ops):
        app.register_blueprint(module.bp, url_prefix="/dealer-network")

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body, status = error_body(e.error_id, e.message, e.http_status)
        return jsonify(body), status

    @app.errorhandler(404)
    def handle_404(e):
        body, status = error_body("ERR_NOT_FOUND", "resource not found", 404)
        return jsonify(body), status

    @app.errorhandler(405)
    def handle_405(e):
        body, status = error_body("ERR_NOT_FOUND", "method not allowed", 404)
        return jsonify(body), status

    @app.errorhandler(400)
    def handle_400(e):
        body, status = error_body("ERR_INVALID_REQUEST", "malformed request", 400)
        return jsonify(body), status

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            body, status = error_body(e.error_id, e.message, e.http_status)
            return jsonify(body), status
        body, status = error_body("ERR_INVALID_REQUEST", f"unexpected error: {e}", 400)
        return jsonify(body), status

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
