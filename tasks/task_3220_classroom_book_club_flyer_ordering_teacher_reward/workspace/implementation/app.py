"""Classroom Book Club API — Flask entry point."""

import os

from flask import Flask

import errors
from errors import ApiError
from routes import schools, teachers, titles, promotions, cycles, orders, fairs, donations, redemptions, ops

app = Flask(__name__)

for mod in (schools, teachers, titles, promotions, cycles, orders, fairs, donations, redemptions, ops):
    app.register_blueprint(mod.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    from flask import jsonify
    return jsonify(errors.error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(err):
    from flask import jsonify
    return jsonify(errors.error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(err):
    from flask import jsonify
    return jsonify(errors.error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(Exception)
def handle_unexpected(err):
    from flask import jsonify
    if isinstance(err, ApiError):
        return jsonify(errors.error_body(err.error_id, err.message)), err.http_status
    app.logger.exception("unexpected error")
    return jsonify(errors.error_body("ERR_INVALID_REQUEST", str(err))), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
