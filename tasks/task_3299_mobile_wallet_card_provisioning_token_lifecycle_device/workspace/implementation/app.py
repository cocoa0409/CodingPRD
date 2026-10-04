# =============================================================================
# App entry point: error handlers + route registration
# =============================================================================
import os

from flask import Flask

import db
from errors import ApiError, ERROR_STATUS
from response import error_body

from routes import (
    authorizations, card_accounts, card_artifacts, cardholders, clock,
    devices, disputes, issuer_agreements, issuers, merchant_programs,
    provisioning, tokens, transit,
)


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err.error_id, err.message), err.http_status

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_body("ERR_NOT_FOUND", "Resource not found"), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_body("ERR_NOT_FOUND", "Method not allowed"), 405

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        app.logger.exception("unexpected error")
        return error_body("ERR_VALIDATION", str(err)), 500

    app.register_blueprint(clock.bp)
    app.register_blueprint(cardholders.bp)
    app.register_blueprint(devices.bp)
    app.register_blueprint(issuers.bp)
    app.register_blueprint(issuer_agreements.bp)
    app.register_blueprint(card_accounts.bp)
    app.register_blueprint(card_artifacts.bp)
    app.register_blueprint(provisioning.bp)
    app.register_blueprint(tokens.bp)
    app.register_blueprint(authorizations.bp)
    app.register_blueprint(disputes.bp)
    app.register_blueprint(merchant_programs.bp)
    app.register_blueprint(transit.bp)

    @app.before_request
    def _serialize():
        # The store is single-process in-memory; serialize requests so version
        # bumps and cascades are atomic under the test harness.
        db.lock().acquire()

    @app.after_request
    def _release(resp):
        db.lock().release()
        return resp

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
