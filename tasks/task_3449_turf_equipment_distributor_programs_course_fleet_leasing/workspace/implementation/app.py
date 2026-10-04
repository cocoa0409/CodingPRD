"""Turf Equipment Leasing API — Flask app factory and entry point.

Mounts every domain blueprint under the /turf prefix. Storage is in-memory
dicts and starts empty on every boot; nothing is seeded.
"""
import os

from flask import Flask

import admin
import appraisals
import catalog
import distributors
import helpers
import irrigation
import leases
import parts_orders
import units
import warranty


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (distributors, catalog, parts_orders, leases, units,
                   appraisals, warranty, irrigation, admin):
        app.register_blueprint(module.bp, url_prefix="/turf")

    @app.errorhandler(helpers.ApiError)
    def handle_api_error(e):
        return helpers.render_error(e)

    @app.errorhandler(404)
    def handle_404(e):
        return helpers.render_error(helpers.ApiError("ERR_NOT_FOUND", "resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return helpers.render_error(helpers.ApiError("ERR_NOT_FOUND", "resource not found"))

    @app.errorhandler(400)
    def handle_400(e):
        return helpers.render_error(helpers.ApiError("ERR_INVALID_REQUEST", "malformed request"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
