"""Application factory, error handlers, blueprint registration, entrypoint."""
import os

from flask import Flask, g

from errors import ApiError
from util import err_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _reset_bump_registry():
        g._bumped = set()

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return err_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def _handle_404(e):
        return err_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_405(e):
        return err_response("ERR_NOT_FOUND", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        return err_response("ERR_INTERNAL", 500, "Internal server error")

    from analysis_plans import bp as analysis_plans_bp
    from clock_route import bp as clock_bp
    from contracts import bp as contracts_bp
    from design_plans import bp as design_plans_bp
    from dissemination import bp as dissemination_bp
    from irb import bp as irb_bp
    from participants import bp as participants_bp
    from records import bp as records_bp
    from reports import bp as reports_bp
    from restricted_use_files import bp as ruf_bp
    from sites import bp as sites_bp
    from studies import bp as studies_bp
    from waves import bp as waves_bp

    app.register_blueprint(contracts_bp)
    app.register_blueprint(studies_bp)
    app.register_blueprint(design_plans_bp)
    app.register_blueprint(irb_bp)
    app.register_blueprint(sites_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(waves_bp)
    app.register_blueprint(records_bp)
    app.register_blueprint(analysis_plans_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(ruf_bp)
    app.register_blueprint(dissemination_bp)
    app.register_blueprint(clock_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
