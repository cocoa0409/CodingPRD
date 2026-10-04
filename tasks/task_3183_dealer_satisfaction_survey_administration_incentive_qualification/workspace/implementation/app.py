import os

from flask import Flask

import errors as err
import routes_core
import routes_instrument
import routes_integrity
import routes_invitations
import routes_settlement
from response import error_response, success_object

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_instrument.bp)
app.register_blueprint(routes_invitations.bp)
app.register_blueprint(routes_integrity.bp)
app.register_blueprint(routes_settlement.bp)


@app.errorhandler(err.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, err.ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", str(e), 400)


@app.get("/healthz")
def healthz():
    return success_object({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
