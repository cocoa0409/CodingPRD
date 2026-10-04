"""Flask app entrypoint: registers blueprints and error handlers."""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
from routes import batches, clock, evs, grants, items, keys, orgs, pools, products, servers, users

app = Flask(__name__)

for module in (clock, orgs, pools, products, grants, users, servers, items, keys, batches, evs):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    from errors import err
    return error_response(err("ERR_INVALID_REQUEST", "route not found"))


@app.errorhandler(405)
def handle_405(e):
    from errors import err
    return error_response(err("ERR_INVALID_REQUEST", "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    from errors import err
    return error_response(err("ERR_INVALID_REQUEST", str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
