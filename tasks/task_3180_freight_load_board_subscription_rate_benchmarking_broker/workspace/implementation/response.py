from flask import jsonify

from util import iso_ms, new_request_id, now_dt


class APIError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_ms(now_dt()),
    }


def success(data, http_status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), http_status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def register_error_handlers(app):
    @app.errorhandler(APIError)
    def _handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def _handle_404(err):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Not found")), 404

    @app.errorhandler(405)
    def _handle_405(err):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed")), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(err):
        if isinstance(err, APIError):
            return jsonify(error_body(err.error_id, err.message)), err.http_status
        return jsonify(error_body("ERR_INVALID_REQUEST", str(err))), 400
