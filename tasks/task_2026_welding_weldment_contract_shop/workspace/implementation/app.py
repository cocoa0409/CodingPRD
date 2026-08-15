"""Welding & Weldment Contract Shop API — entry point.

In-memory store only; the store starts empty on every boot (no seeding).
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response
from routes import shops, materials, docs, quals, production, joints, quality, flat


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(shops.bp)
    app.register_blueprint(materials.bp)
    app.register_blueprint(docs.bp)
    app.register_blueprint(quals.bp)
    app.register_blueprint(production.bp)
    app.register_blueprint(joints.bp)
    app.register_blueprint(quality.bp)
    flat.register_flat_routes(app)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INTERNAL", 500, str(e))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
