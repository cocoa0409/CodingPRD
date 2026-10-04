"""Entry point: error handlers, route registration, and the server launcher.

The store is empty at boot.  Nothing here seeds, preloads or registers any
entity: every row in the system is created through a declared endpoint.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from respond import error_body

import views.billing
import views.campaigns
import views.claims
import views.designs
import views.installers
import views.labor
import views.lots
import views.orders
import views.systems
import views.transfers
import views.units

ROUTE_MODULES = (
    views.installers,
    views.designs,
    views.lots,
    views.systems,
    views.units,
    views.claims,
    views.labor,
    views.transfers,
    views.campaigns,
    views.orders,
    views.billing,
)


def create_app():
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.json.sort_keys = False

    for module in ROUTE_MODULES:
        module.register(app)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        # Unknown route or unsupported method: the envelope still applies.
        error_id = ("ERR_RESOURCE_NOT_FOUND" if exc.code == 404
                    else "ERR_INVALID_REQUEST_BODY")
        return error_body(error_id, exc.description or exc.name), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_body("ERR_INVALID_REQUEST_BODY", str(exc)), 400

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)