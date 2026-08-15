import os
from flask import Flask, jsonify
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import programs, framework, profiles, market, bands, departments, employees, mapping, exceptions, refresh, clock_routes  # noqa: E402

app.register_blueprint(programs.bp)
app.register_blueprint(framework.bp)
app.register_blueprint(profiles.bp)
app.register_blueprint(market.bp)
app.register_blueprint(bands.bp)
app.register_blueprint(departments.bp)
app.register_blueprint(employees.bp)
app.register_blueprint(mapping.bp)
app.register_blueprint(exceptions.bp)
app.register_blueprint(refresh.bp)
app.register_blueprint(clock_routes.bp)


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", "resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", "method not allowed", 404)


@app.errorhandler(400)
def handle_400(err):
    return error_response("ERR_INVALID_REQUEST", "malformed request", 400)


@app.errorhandler(500)
def handle_500(err):
    return error_response("ERR_INVALID_REQUEST", "internal error", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
