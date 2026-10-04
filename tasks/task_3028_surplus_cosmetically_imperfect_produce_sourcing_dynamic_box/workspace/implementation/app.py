"""Entry point: error handlers and route registration (§2.2).

The store is created empty on every boot. Nothing here seeds, preloads or
registers any entity; every row a test needs is built through the API surface.
"""

import os
import traceback

from flask import Flask

import envelope
from common import ApiError


def create_app():
    # static_folder=None keeps the surface to exactly the declared routes.
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    from routes import (boxes, centers, claims, clock, customers, lots, quotes,
                        subscriptions, suppliers)

    app.register_blueprint(clock.bp)
    app.register_blueprint(customers.bp)
    app.register_blueprint(subscriptions.bp)
    app.register_blueprint(centers.bp)
    app.register_blueprint(suppliers.bp)
    app.register_blueprint(lots.bp)
    app.register_blueprint(quotes.bp)
    app.register_blueprint(boxes.bp)
    app.register_blueprint(claims.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return envelope.error_response("ERR_INVALID_REQUEST",
                                       "No route matches the requested path.", 404)

    @app.errorhandler(405)
    def handle_method(err):
        return envelope.error_response("ERR_INVALID_REQUEST",
                                       "The method is not allowed for this path.", 405)

    @app.errorhandler(400)
    def handle_bad_request(err):
        return envelope.error_response("ERR_INVALID_REQUEST",
                                       "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err.error_id, err.message,
                                           err.http_status)
        traceback.print_exc()
        return envelope.error_response("ERR_INVALID_REQUEST",
                                       "The request could not be processed.", 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)