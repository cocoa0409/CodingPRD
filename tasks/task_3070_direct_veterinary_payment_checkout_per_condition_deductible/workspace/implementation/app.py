"""Flask app entry point: blueprint registration + error handling."""
import os

from flask import Flask, jsonify

import core
import routes_part1
import routes_part2

app = Flask(__name__)
app.register_blueprint(routes_part1.bp, url_prefix="/vetpay")
app.register_blueprint(routes_part2.bp, url_prefix="/vetpay")


@app.errorhandler(core.ApiError)
def handle_api_error(e):
    return core.err(e)


@app.errorhandler(404)
def handle_404(e):
    return core.err(core.ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return core.err(core.ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, core.ApiError):
        return core.err(e)
    app.logger.exception("unhandled error")
    return core.err(core.ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
