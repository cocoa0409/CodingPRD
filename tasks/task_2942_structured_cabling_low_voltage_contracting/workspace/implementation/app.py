"""Structured Cabling & Low-Voltage Contracting API.

Entry point: route registration, the PRD 2.2 error envelope and the process-wide
write lock. The store boots empty on every process start — nothing is seeded.
"""

import os

from flask import Flask, g, jsonify

import store
from envelope import error_body, error_response
from errors import ApiError
from routes.cables import cables_bp
from routes.clock import clock_bp
from routes.link_routes import link_routes_bp
from routes.links import links_bp
from routes.mac import mac_bp
from routes.pathways import pathways_bp
from routes.projects import projects_bp
from routes.racks import racks_bp
from routes.rooms import rooms_bp
from routes.tests import tests_bp
from routes.trade import trade_bp
from routes.warranty import warranty_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config["JSON_SORT_KEYS"] = False

for blueprint in (projects_bp, rooms_bp, racks_bp, pathways_bp, cables_bp, links_bp,
                  link_routes_bp, tests_bp, warranty_bp, mac_bp, trade_bp, clock_bp):
    app.register_blueprint(blueprint)


@app.before_request
def _acquire_lock():
    """One request at a time: every handler reads and writes shared ledgers."""
    store.lock.acquire()
    g._holds_lock = True


@app.teardown_request
def _release_lock(exc=None):
    if getattr(g, "_holds_lock", False):
        g._holds_lock = False
        try:
            store.lock.release()
        except RuntimeError:
            pass


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_not_found(err):
    return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 404


@app.errorhandler(405)
def _handle_method_not_allowed(err):
    return jsonify(error_body("ERR_INVALID_REQUEST",
                             "That method is not allowed on this route.")), 405


@app.errorhandler(400)
def _handle_bad_request(err):
    return jsonify(error_body("ERR_INVALID_REQUEST", "The request is malformed.")), 400


@app.errorhandler(Exception)
def _handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    app.logger.exception("unhandled error")
    return jsonify(error_body("ERR_INVALID_REQUEST", "Unhandled server error: %s" % err)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
