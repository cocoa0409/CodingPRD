"""Entry point: error handlers and route registration.

The store is process-local and starts empty; importing this module registers
routes and nothing else.  No entity is seeded, preloaded or hardcoded at boot --
every row a caller observes was created through a declared endpoint.
"""
import os
import traceback

from flask import Flask, jsonify, request

import db
import response
from errors import ApiError
from routes import catering, catalog, equipment, platform, production, promotions, scales, staff, stores, subtickets, waste

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = False


def _register_routes():
    for module in (platform, stores, catalog, staff, equipment, production,
                   subtickets, promotions, scales, catering, waste):
        module.register(app)


_register_routes()


@app.errorhandler(ApiError)
def handle_api_error(error):
    return jsonify(response.error_body(db.get(), error.error_id, error.message)), \
        error.http_status


@app.errorhandler(404)
def handle_not_found(error):
    store = db.get()
    return jsonify(response.error_body(store, "ERR_NOT_FOUND",
                                       "The addressed resource does not exist.")), 404


@app.errorhandler(405)
def handle_method(error):
    store = db.get()
    return jsonify(response.error_body(store, "ERR_INVALID_REQUEST",
                                       "The method is not allowed for this path.")), 400


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return handle_api_error(error)
    traceback.print_exc()
    store = db.get()
    return jsonify(response.error_body(store, "ERR_INVALID_REQUEST",
                                       "The request could not be processed.")), 400


@app.route("/_health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False)