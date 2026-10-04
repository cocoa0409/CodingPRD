"""Entry point for the electrical-prefabrication coordination service.

The whole HTTP surface lives in ``routes.bp``; the PRD mounts every declared
endpoint under the ``/prefab`` prefix, so the blueprint is registered with
``url_prefix="/prefab"``.  Domain failures raised as ``core.ApiError`` render
the §2.2 error envelope (``meta`` / ``response_type: "error"`` /
``data.error_id`` + ``data.message``).

Nothing is seeded here: the in-memory store in ``core`` starts empty on every
boot so a fresh ``bash start.sh`` is a clean slate.
"""

import os

from flask import Flask

from core import ApiError, envelope_error
import routes


def create_app():
    app = Flask(__name__)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes.bp, url_prefix="/prefab")

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return envelope_error(error.error_id, error.message), error.http_status

    @app.errorhandler(404)
    def handle_not_found(_error):
        return (
            envelope_error(
                "ERR_REFERENCED_ENTITY_NOT_FOUND",
                "The requested route or resource is not addressable on this service.",
            ),
            404,
        )

    @app.errorhandler(405)
    def handle_method_not_allowed(_error):
        return (
            envelope_error(
                "ERR_INVALID_PREFAB_TRANSITION",
                "The requested method is not declared for this route.",
            ),
            405,
        )

    @app.errorhandler(500)
    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return envelope_error(error.error_id, error.message), error.http_status
        return (
            envelope_error(
                "ERR_INVALID_PREFAB_TRANSITION",
                "The request could not be completed as supplied.",
            ),
            400,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))