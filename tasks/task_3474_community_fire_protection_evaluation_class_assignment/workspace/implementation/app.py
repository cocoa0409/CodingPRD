"""Fire Protection Classification API — entry point.

Flask app wiring: blueprints per domain plus envelope-shaped error handlers.
Boots empty; in-memory store only; listens on $PORT (default 10000), 0.0.0.0.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_payload
from routes_community import bp as bp_community
from routes_cycle import bp as bp_cycle
from routes_classification import bp as bp_classification
from routes_field import bp as bp_field
from routes_water import bp as bp_water
from routes_credits import bp as bp_credits
from routes_insurance import bp as bp_insurance
from routes_reeval import bp as bp_reeval
from routes_appeals import bp as bp_appeals


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (bp_community, bp_cycle, bp_classification, bp_field, bp_water,
               bp_credits, bp_insurance, bp_reeval, bp_appeals):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_payload(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify(error_payload("ERR_NOT_FOUND", "route not found")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return jsonify(error_payload("ERR_METHOD_NOT_ALLOWED", "method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_internal(e):
        return jsonify(error_payload("ERR_INTERNAL", "internal server error")), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
