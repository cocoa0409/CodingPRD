"""IVD reagent manufacturing traceability API (PRD sections 1-5).

The whole system of record lives in process memory; nothing is seeded, nothing
is read from disk, and a fresh process starts with fourteen empty collections.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import allocations as allocations_routes
from routes import bridging_studies as bridging_studies_routes
from routes import clock as clock_routes
from routes import complaints as complaints_routes
from routes import design_control_records as design_control_records_routes
from routes import distribution as distribution_routes
from routes import fill_runs as fill_runs_routes
from routes import material_lots as material_lots_routes
from routes import material_specifications as material_specifications_routes
from routes import product_specifications as product_specifications_routes
from routes import reagent_lots as reagent_lots_routes
from routes import stability_studies as stability_studies_routes
from routes import test_results as test_results_routes

BLUEPRINTS = (
    clock_routes.bp,
    material_specifications_routes.bp,
    material_lots_routes.bp,
    product_specifications_routes.bp,
    design_control_records_routes.bp,
    reagent_lots_routes.bp,
    fill_runs_routes.bp,
    test_results_routes.bp,
    stability_studies_routes.bp,
    bridging_studies_routes.bp,
    complaints_routes.bp,
    distribution_routes.bp,
    allocations_routes.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(400)
    def _bad_request(_error):
        return error_response("ERR_INVALID_REQUEST",
                              "The request body could not be parsed as JSON.", 400)

    @app.errorhandler(404)
    def _not_found(_error):
        return error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "The method is not allowed for this route.", 405)

    @app.errorhandler(415)
    def _unsupported_media_type(_error):
        return error_response("ERR_INVALID_REQUEST",
                              "The request body could not be parsed as JSON.", 400)

    @app.errorhandler(Exception)
    def _internal(error):
        if isinstance(error, ApiError):
            return error_response(error.error_id, error.message, error.http_status)
        return error_response("ERR_INTERNAL", str(error) or "Internal error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or 10000)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
            threaded=True)
