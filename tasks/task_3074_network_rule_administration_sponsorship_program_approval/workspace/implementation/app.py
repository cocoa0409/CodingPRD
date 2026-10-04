"""Entry point: Flask app, error handlers, blueprint registration."""

import os

from flask import Flask

from errors import ApiError
from response import error_response, ok

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes.members import bp as members_bp
from routes.participants import bp as participants_bp
from routes.merchants import bp as merchants_bp
from routes.bin_ranges import bp as bin_ranges_bp
from routes.programs import bp as programs_bp
from routes.certification_tests import bp as cert_tests_bp
from routes.rules import bp as rules_bp
from routes.violations import bp as violations_bp
from routes.disputes import bp as disputes_bp
from routes.interchange import bp as interchange_bp
from routes.fraud import bp as fraud_bp
from routes.settlement import bp as settlement_bp
from routes.clock import bp as clock_bp

for bp in (
    clock_bp, members_bp, participants_bp, merchants_bp, bin_ranges_bp,
    programs_bp, cert_tests_bp, rules_bp, violations_bp, disputes_bp,
    interchange_bp, fraud_bp, settlement_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found", 404))


@app.errorhandler(Exception)
def handle_generic(err):
    import traceback
    traceback.print_exc()
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(err), 400))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
