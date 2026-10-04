"""Bank Data Connectivity Consent API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.clock import bp as clock_bp
from routes.institutions import bp as institutions_bp
from routes.recipients import bp as recipients_bp
from routes.tiers import bp as tiers_bp
from routes.consents import bp as consents_bp
from routes.connections import bp as connections_bp
from routes.webhooks import bp as webhooks_bp
from routes.deletion import bp as deletion_bp
from routes.audit import bp as audit_bp


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (clock_bp, institutions_bp, recipients_bp, tiers_bp, consents_bp,
               connections_bp, webhooks_bp, deletion_bp, audit_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(500)
    def handle_500(e):
        return error_response("ERR_INVALID_REQUEST", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
