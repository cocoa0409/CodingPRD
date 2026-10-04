"""App entry point: Flask app, error handlers, route registration."""

import os

from flask import Flask, jsonify

from errors import ApiError
from helpers import envelope_error, envelope_ok

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return envelope_error(err)


@app.errorhandler(404)
def handle_404(err):
    return envelope_error(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return envelope_error(ApiError("ERR_NOT_FOUND", "Method not allowed", 404))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return envelope_error(err)
    return envelope_error(ApiError("ERR_INTERNAL", str(err), 500))


# Register route blueprints
from routes.charts import bp as charts_bp
from routes.providers import bp as providers_bp
from routes.labels import bp as labels_bp
from routes.titles import bp as titles_bp
from routes.enforcement import bp as enforcement_bp
from routes.misc import bp as misc_bp

app.register_blueprint(charts_bp)
app.register_blueprint(providers_bp)
app.register_blueprint(labels_bp)
app.register_blueprint(titles_bp)
app.register_blueprint(enforcement_bp)
app.register_blueprint(misc_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
