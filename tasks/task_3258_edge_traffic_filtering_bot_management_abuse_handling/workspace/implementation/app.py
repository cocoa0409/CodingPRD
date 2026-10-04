import os

from flask import Flask

from core import ApiError, error_response, err_not_found
import routes_misc
import routes_zones
import routes_children

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _nf(err):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def _mna(err):
    return error_response(err_not_found("Resource not found"))


routes_misc.register(app)
routes_zones.register(app)
routes_children.register(app)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
