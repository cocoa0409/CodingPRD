"""App entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_contracts
import routes_setup
import routes_rates
import routes_reservations
import routes_finance
import routes_projects
import routes_people
import routes_incidents
import routes_flat

for mod in (routes_contracts, routes_setup, routes_rates, routes_reservations,
            routes_finance, routes_projects, routes_people, routes_incidents,
            routes_flat):
    app.register_blueprint(mod.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_INVALID_REQUEST", 404, "Not found")


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_generic(e):
    return error("ERR_INVALID_REQUEST", 400, str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
