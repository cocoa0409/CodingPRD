"""Application entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError, STATUS_BY_ERROR, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)

import routes_agency
import routes_contracts
import routes_milestones
import routes_workflow
import routes_migration
import routes_interfaces
import routes_uat_training
import routes_golive_support

app.register_blueprint(routes_agency.bp)
app.register_blueprint(routes_contracts.bp)
app.register_blueprint(routes_milestones.bp)
app.register_blueprint(routes_workflow.bp)
app.register_blueprint(routes_migration.bp)
app.register_blueprint(routes_interfaces.bp)
app.register_blueprint(routes_uat_training.bp)
app.register_blueprint(routes_golive_support.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, "resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, "method not allowed", 404)


@app.errorhandler(400)
def handle_400(err):
    return error_response(ERR_INVALID_REQUEST, "malformed request", 400)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.message, err.http_status)
    return error_response(ERR_INVALID_REQUEST, str(err), 400)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
