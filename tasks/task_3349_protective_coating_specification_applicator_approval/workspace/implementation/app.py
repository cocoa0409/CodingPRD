"""Flask app factory: blueprint registration and error handlers only."""
import os

from flask import Flask

import applicators
import applications
import clockops
import flat
import investigations
import prep_inspections
import projects
import regulations
import reports
import specifications
import substitutions
import systems
import warranties
import work_orders
from errors import ApiError
from response import error_resp


def create_app():
    app = Flask(__name__)
    for module in (clockops, systems, regulations, applicators, projects,
                   specifications, substitutions, work_orders, prep_inspections,
                   applications, reports, warranties, investigations, flat):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_resp(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_not_found(e):
        return error_resp('ERR_INVALID_REQUEST', 404, 'route not found')

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return error_resp('ERR_INVALID_REQUEST', 405, 'method not allowed')

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_resp('ERR_INVALID_REQUEST', 500, 'internal server error')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
            threaded=True, use_reloader=False)
