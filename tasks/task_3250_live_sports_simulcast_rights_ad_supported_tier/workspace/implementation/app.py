"""Flask app entry point."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import err_resp
from routes.properties import bp as properties_bp
from routes.windows import bp as windows_bp
from routes.territory import bp as territory_bp
from routes.viewers import bp as viewers_bp
from routes.capacity import bp as capacity_bp
from routes.ads import bp as ads_bp
from routes.partners import bp as partners_bp
from routes.misc import bp as misc_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (properties_bp, windows_bp, territory_bp, viewers_bp,
               capacity_bp, ads_bp, partners_bp, misc_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return err_resp(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return err_resp(ERR_NOT_FOUND[0], 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return err_resp(ERR_NOT_FOUND[0], 404, "resource not found")

    @app.errorhandler(400)
    def handle_400(err):
        return err_resp(ERR_INVALID_REQUEST[0], 400, "bad request")

    @app.errorhandler(Exception)
    def handle_exc(err):
        if isinstance(err, ApiError):
            return err_resp(err.error_id, err.http_status, err.message)
        return err_resp("ERR_INTERNAL", 500, str(err))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
