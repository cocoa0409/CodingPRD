"""App entry point."""
import os
from flask import Flask, jsonify
from core import ApiError, error_response, new_req_id, req_ts
import routes_accounts
import routes_billing
import routes_campaigns
import routes_ads
import routes_auctions


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_accounts.bp)
    app.register_blueprint(routes_billing.bp)
    app.register_blueprint(routes_campaigns.bp)
    app.register_blueprint(routes_ads.bp)
    app.register_blueprint(routes_auctions.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        body = {
            "meta": {"api_request_id": new_req_id(), "api_request_timestamp": req_ts()},
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
        }
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(e):
        body = {
            "meta": {"api_request_id": new_req_id(), "api_request_timestamp": req_ts()},
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
        }
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, ApiError):
            return error_response(e)
        body = {
            "meta": {"api_request_id": new_req_id(), "api_request_timestamp": req_ts()},
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": str(e)},
        }
        return jsonify(body), 400

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
