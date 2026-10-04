"""Flask entry point: registers blueprints and error handlers."""
import os

import flask
from werkzeug.exceptions import HTTPException

from helpers import ApiError, error_response, meta_base
from routes import (clock_orgs, agreements, products, anniversaries, entitlements,
                    stepups, deployments, snapshots, trueup, trueup_transitions,
                    benefits, cloud, hosting, shortfall)


def create_app():
    app = flask.Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (clock_orgs, agreements, products, anniversaries, entitlements,
                   stepups, deployments, snapshots, trueup, trueup_transitions,
                   benefits, cloud, hosting, shortfall):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(HTTPException)
    def handle_http_error(e):
        status = e.code or 500
        if status == 404:
            body = {"meta": meta_base(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."}}
        elif status == 405:
            body = {"meta": meta_base(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."}}
        else:
            body = {"meta": meta_base(), "response_type": "error",
                    "data": {"error_id": "ERR_INVALID_REQUEST", "message": e.description or "Request error."}}
        return flask.make_response(flask.jsonify(body), status)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        body = {"meta": meta_base(), "response_type": "error",
                "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Unexpected server error."}}
        return flask.make_response(flask.jsonify(body), 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
