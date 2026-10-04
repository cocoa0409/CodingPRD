"""Application entry point: registers routes and error handlers."""
import os
from flask import Flask
from errors import ApiError
from response import error_response
from routes.families import bp as families_bp
from routes.children import bp as children_bp
from routes.connections import bp as connections_bp
from routes.devices import bp as devices_bp
from routes.content import bp as content_bp
from routes.escalations import bp as escalations_bp
from routes.districts import bp as districts_bp
from routes.clock import bp as clock_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (families_bp, children_bp, connections_bp, devices_bp,
           content_bp, escalations_bp, districts_bp, clock_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method(_err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(err) or "Unexpected error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
