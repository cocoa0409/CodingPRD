"""ESOP Administration API -- entry point.

Storage is in-memory only and starts empty on every boot.  Nothing is seeded,
preloaded or hardcoded; every entity is created by callers through the
declared endpoints.
"""

import os

from flask import Flask

import responses
from routes.allocations import bp as allocations_bp
from routes.distributions import bp as distributions_bp
from routes.loans import bp as loans_bp
from routes.participants import bp as participants_bp
from routes.plans import bp as plans_bp
from routes.puts import bp as puts_bp
from routes.statements import bp as statements_bp
from routes.valuations import bp as valuations_bp


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(plans_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(valuations_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(puts_bp)
    app.register_blueprint(statements_bp)

    @app.errorhandler(404)
    def not_found(_exc):
        return responses.error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def method_not_allowed(_exc):
        return responses.error("ERR_INVALID_REQUEST", "Method not allowed for this route.", 405)

    @app.errorhandler(400)
    def bad_request(_exc):
        return responses.error("ERR_INVALID_REQUEST", "The request payload is malformed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
