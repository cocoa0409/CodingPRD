"""Entry point: registers blueprints, error handlers and boots the server."""
import os

from flask import Flask, jsonify, request

from core import ApiError, DB, envelope
from bp import delivery, editions, hubs, markets, newsroom, ops, sites, subscribers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (hubs, sites, markets, editions, delivery, subscribers, newsroom, ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        payload = envelope({"error_id": err.error_id, "message": err.message}, "error")
        return jsonify(payload), err.http_status

    @app.errorhandler(404)
    def handle_404(_err):
        payload = envelope({"error_id": "ERR_RESOURCE_NOT_FOUND",
                            "message": "The requested path does not resolve."}, "error")
        return jsonify(payload), 404

    @app.errorhandler(405)
    def handle_405(_err):
        payload = envelope({"error_id": "ERR_INVALID_REQUEST",
                            "message": "The method is not allowed for this path."}, "error")
        return jsonify(payload), 405

    @app.errorhandler(Exception)
    def handle_generic(err):
        if isinstance(err, ApiError):
            payload = envelope({"error_id": err.error_id, "message": err.message}, "error")
            return jsonify(payload), err.http_status
        app.logger.exception("unhandled error")
        payload = envelope({"error_id": "ERR_INVALID_REQUEST",
                            "message": "The request could not be processed."}, "error")
        return jsonify(payload), 400

    @app.get("/health")
    def health():
        return jsonify(envelope({"status": "ok"}, "object")), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)