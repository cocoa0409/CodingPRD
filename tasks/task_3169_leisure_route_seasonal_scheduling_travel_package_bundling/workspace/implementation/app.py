"""Application entry point: Flask app, error handlers, blueprint registration."""

import os

from flask import Flask

from errors import ApiError
from response import ok, _meta

app = Flask(__name__)

from routes.stations import bp as stations_bp
from routes.routes import bp as routes_bp
from routes.season_windows import bp as windows_bp
from routes.publications import bp as pubs_bp
from routes.aircraft import bp as aircraft_bp
from routes.flight_instances import bp as flights_bp
from routes.crew import bp as crew_bp
from routes.supplier_offers import bp as offers_bp
from routes.bookings import bp as bookings_bp
from routes.disruptions import bp as disruptions_bp
from routes.supplier_settlements import bp as settlements_bp
from routes.clock import bp as clock_bp

app.register_blueprint(stations_bp)
app.register_blueprint(routes_bp)
app.register_blueprint(windows_bp)
app.register_blueprint(pubs_bp)
app.register_blueprint(aircraft_bp)
app.register_blueprint(flights_bp)
app.register_blueprint(crew_bp)
app.register_blueprint(offers_bp)
app.register_blueprint(bookings_bp)
app.register_blueprint(disruptions_bp)
app.register_blueprint(settlements_bp)
app.register_blueprint(clock_bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return body, err.http_status


@app.errorhandler(404)
def handle_not_found(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": "ERR_NOT_FOUND",
            "message": "The requested resource does not exist",
        },
    }
    return body, 404


@app.errorhandler(405)
def handle_method_not_allowed(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": "ERR_METHOD_NOT_ALLOWED",
            "message": "The requested method is not allowed on this resource",
        },
    }
    return body, 405


@app.errorhandler(500)
def handle_internal_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": "ERR_INTERNAL",
            "message": "An internal server error occurred",
        },
    }
    return body, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
