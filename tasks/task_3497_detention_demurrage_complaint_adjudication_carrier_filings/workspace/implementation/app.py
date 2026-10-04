"""FMC Detention & Demurrage Complaint Adjudication API — Flask entry point."""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    from routes import (
        carriers,
        tariffs,
        contracts,
        agreements,
        licenses,
        invoices,
        disputes,
        complaints,
        enforcement,
        congestion,
        clock_route,
    )

    for mod in (
        carriers,
        tariffs,
        contracts,
        agreements,
        licenses,
        invoices,
        disputes,
        complaints,
        enforcement,
        congestion,
        clock_route,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
