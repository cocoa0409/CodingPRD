"""Teacher Classroom Funding API — entry point.

Flask app, error handlers, route registration. Storage is in-memory only;
every fresh process boots with empty state. The server listens on
0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import register_all

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.status, err.message)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_NOT_FOUND", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % err)


register_all(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
