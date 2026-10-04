"""National Food Bank Network — donated load allocation API.

Entry point: registers the route blueprints and maps every failure to the
scaffold's error envelope.  State lives in process memory only; every boot
starts from an empty store.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ERR_INVALID_REQUEST, ApiError
from routes import agreements, audits, bids, loads, members, misc, programs, recalls

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = False


@app.errorhandler(ApiError)
def _api_error(exc):
    return envelope.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(HTTPException)
def _http_error(exc):
    return envelope.error_response(
        ERR_INVALID_REQUEST,
        exc.description or "the request could not be routed",
        exc.code or 400,
    )


@app.errorhandler(Exception)
def _unexpected(exc):  # pragma: no cover - defensive
    return envelope.error_response(
        ERR_INVALID_REQUEST, "the request could not be processed", 500)


for _blueprint in (members.bp, agreements.bp, loads.bp, bids.bp, recalls.bp,
                   audits.bp, programs.bp, misc.bp):
    app.register_blueprint(_blueprint)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        use_reloader=False,
    )
