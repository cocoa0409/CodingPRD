import os
from flask import Flask
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response
from services.core import sweep_entitlement_expiry

app = Flask(__name__)


@app.before_request
def _expiry_sweep():
    sweep_entitlement_expiry()


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(400)
def handle_400(e):
    return error_response(ERR_INVALID_REQUEST, "Invalid request", 400)


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response(ERR_INVALID_REQUEST, str(e), 400)


from routes.catalog import bp as catalog_bp
from routes.configurations import bp as configurations_bp
from routes.orders import bp as orders_bp
from routes.build import bp as build_bp
from routes.waves import bp as waves_bp
from routes.services_api import bp as services_api_bp

app.register_blueprint(catalog_bp)
app.register_blueprint(configurations_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(build_bp)
app.register_blueprint(waves_bp)
app.register_blueprint(services_api_bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
