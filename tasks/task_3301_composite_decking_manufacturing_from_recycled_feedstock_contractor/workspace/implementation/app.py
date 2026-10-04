"""Application entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask, jsonify

from errors import ApiError, raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from util import req_meta

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": req_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": req_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": req_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": req_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)},
    }
    return jsonify(body), 400


from routes import plants, suppliers, feedstock, formulations, product_lines  # noqa: E402
from routes import production, board_lots, dealers, commitments, contractors  # noqa: E402
from routes import leads, registrations, claims, merch  # noqa: E402

for mod in (plants, suppliers, feedstock, formulations, product_lines,
            production, board_lots, dealers, commitments, contractors,
            leads, registrations, claims, merch):
    app.register_blueprint(mod.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
