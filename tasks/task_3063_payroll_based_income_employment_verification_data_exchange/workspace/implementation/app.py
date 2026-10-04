"""Flask application entry point. The store boots empty."""
from flask import Flask, jsonify

import clock
import response
import routes_core
import routes_flow
import store
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

store.reset()
clock.reset()

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_flow.bp)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return jsonify(response.error(error.error_id, error.message)), error.http_status


@app.errorhandler(404)
def handle_not_found(error):
    return jsonify(response.error("ERR_NOT_FOUND", "The addressed resource does not exist.")), 404


@app.errorhandler(405)
def handle_method(error):
    return jsonify(response.error("ERR_NOT_FOUND", "The addressed resource does not exist.")), 404


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return handle_api_error(error)
    return jsonify(response.error("ERR_INVALID_STATE", str(error))), 409


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)