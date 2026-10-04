"""Entry point: Flask app, error handlers, route registration."""
import os
from flask import Flask
from errors import ApiError
from response import error_response, success

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

import routes_circles
import routes_consent
import routes_places
import routes_fixes
import routes_crashes
import routes_subscription
import routes_clock

app.register_blueprint(routes_circles.bp)
app.register_blueprint(routes_consent.bp)
app.register_blueprint(routes_places.bp)
app.register_blueprint(routes_fixes.bp)
app.register_blueprint(routes_crashes.bp)
app.register_blueprint(routes_subscription.bp)
app.register_blueprint(routes_clock.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    from errors import err_not_found
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    from errors import err_not_found
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(500)
def handle_500(err):
    from errors import err_invalid_request
    return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(getattr(err, "original_exception", err))))


@app.route("/health", methods=["GET"])
def health():
    return success({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
