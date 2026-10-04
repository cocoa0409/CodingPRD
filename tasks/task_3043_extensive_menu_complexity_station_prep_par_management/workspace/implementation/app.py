import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.restaurants import bp as restaurants_bp
from routes.menu_revisions import bp as menu_revisions_bp
from routes.recipes import bp as recipes_bp
from routes.prep_items import bp as prep_items_bp
from routes.stations import bp as stations_bp
from routes.station_pars import bp as station_pars_bp
from routes.cooks import bp as cooks_bp
from routes.demand_forecasts import bp as demand_forecasts_bp
from routes.prep_lists import bp as prep_lists_bp
from routes.prep_batches import bp as prep_batches_bp
from routes.shift_assignments import bp as shift_assignments_bp
from routes.bakery_orders import bp as bakery_orders_bp
from routes.waste_entries import bp as waste_entries_bp
from routes.service_tickets import bp as service_tickets_bp


def create_app():
    app = Flask(__name__)

    for bp in (
        clock_bp,
        restaurants_bp,
        menu_revisions_bp,
        recipes_bp,
        prep_items_bp,
        stations_bp,
        station_pars_bp,
        cooks_bp,
        demand_forecasts_bp,
        prep_lists_bp,
        prep_batches_bp,
        shift_assignments_bp,
        bakery_orders_bp,
        waste_entries_bp,
        service_tickets_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.http_status, err.message)
        return error_response("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
