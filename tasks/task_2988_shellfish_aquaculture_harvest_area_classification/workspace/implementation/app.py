"""Shellfish Harvest Classification API — Flask application entry point.

All state lives in process memory (see core.Store); every launch of this
module starts from an entirely empty store with no seeded entities.
"""

import os

from flask import Flask, jsonify

from core import envelope_error
from errors import ApiError

import routes_area
import routes_dealer
import routes_growout
import routes_harvest
import routes_investigation
import routes_lease
import routes_lot
import routes_misc
import routes_seed
import routes_shipment

API_PREFIX = "/shellfish"

BLUEPRINTS = [
    routes_area.bp,
    routes_lease.bp,
    routes_seed.bp,
    routes_growout.bp,
    routes_harvest.bp,
    routes_lot.bp,
    routes_dealer.bp,
    routes_shipment.bp,
    routes_investigation.bp,
    routes_misc.bp,
]


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        if blueprint is None:
            continue
        app.register_blueprint(blueprint, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(envelope_error(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_not_found(err):
        return (
            jsonify(
                envelope_error(
                    "ERR_INVALID_REQUEST", "The requested resource does not exist."
                )
            ),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return (
            jsonify(
                envelope_error(
                    "ERR_INVALID_REQUEST",
                    "The HTTP method is not allowed for this resource.",
                )
            ),
            405,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return jsonify(envelope_error(err.error_id, err.message)), err.http_status
        return (
            jsonify(
                envelope_error(
                    "ERR_INVALID_REQUEST",
                    "The request could not be processed: %s" % (err,),
                )
            ),
            400,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
