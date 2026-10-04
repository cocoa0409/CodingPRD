"""Application entry point."""
import os
import sys

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError
from respond import error_response, success
from routes import accounts, contracts, devices, license_pools, partners, rma, transfers, virtual_accounts

app = Flask(__name__)

for module in (accounts, partners, virtual_accounts, license_pools, devices, contracts, rma, transfers):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))


@app.get("/api/health")
def health():
    return success({"status": "ok"}, 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
