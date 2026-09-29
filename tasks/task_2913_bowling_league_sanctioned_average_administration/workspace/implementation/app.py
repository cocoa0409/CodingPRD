"""Bowling League & Sanctioned Average Administration API.

In-memory only: every dict in store.py starts empty on each boot and no entity
is ever seeded. All state is created through the endpoints of PRD 4.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from envelope import error_body
from errors import ApiError
from routes_award import awards
from routes_core import core
from routes_match import matches
from routes_money import money
from routes_protest import protests
from routes_read import read
from routes_remit import remit

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

app.register_blueprint(core)
app.register_blueprint(remit)
app.register_blueprint(matches)
app.register_blueprint(money)
app.register_blueprint(awards)
app.register_blueprint(protests)
app.register_blueprint(read)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


@app.errorhandler(HTTPException)
def handle_http_error(exc):
    if exc.code in (400, 405, 415):
        return jsonify(error_body("ERR_INVALID_REQUEST", exc.description)), 400
    return jsonify(error_body("ERR_INVALID_REQUEST", exc.description)), exc.code


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
