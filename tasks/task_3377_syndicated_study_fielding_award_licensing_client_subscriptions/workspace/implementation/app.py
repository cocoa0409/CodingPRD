"""Entry point: Flask app assembly, error handlers, route registration."""
import os

from flask import Flask

import envelope
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    from routes_studies import bp as studies_bp
    from routes_methodology import bp as methodology_bp
    from routes_frames import bp as frames_bp
    from routes_responses import bp as responses_bp
    from routes_scoring import bp as scoring_bp
    from routes_licenses import bp as licenses_bp
    from routes_registry import bp as registry_bp
    from routes_subscriptions import bp as subscriptions_bp
    from routes_insights import bp as insights_bp

    for bp in (
        studies_bp,
        methodology_bp,
        frames_bp,
        responses_bp,
        scoring_bp,
        licenses_bp,
        registry_bp,
        subscriptions_bp,
        insights_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return envelope.err(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return envelope.err("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return envelope.err("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return envelope.err("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
