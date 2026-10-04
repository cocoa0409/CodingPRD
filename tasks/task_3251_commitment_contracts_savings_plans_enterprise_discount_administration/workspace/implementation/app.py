import os
from flask import Flask
from store import ApiError
from response import err_response


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response(ApiError('ERR_NOT_FOUND', 404, 'resource not found'))

    @app.errorhandler(405)
    def handle_405(e):
        return err_response(ApiError('ERR_NOT_FOUND', 404, 'resource not found'))

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err_response(e)
        return err_response(ApiError('ERR_INVALID_REQUEST', 400, 'unexpected error: ' + str(e)))

    from routes_orgs import bp as bp_orgs
    from routes_accounts import bp as bp_accounts
    from routes_agreements import bp as bp_agreements
    from routes_tiers import bp as bp_tiers
    from routes_amendments import bp as bp_amendments
    from routes_plans import bp as bp_plans
    from routes_usage import bp as bp_usage
    from routes_credits import bp as bp_credits
    from routes_invoices import bp as bp_invoices
    from routes_trueup import bp as bp_trueup
    from routes_forecasts import bp as bp_forecasts

    app.register_blueprint(bp_orgs)
    app.register_blueprint(bp_accounts)
    app.register_blueprint(bp_agreements)
    app.register_blueprint(bp_tiers)
    app.register_blueprint(bp_amendments)
    app.register_blueprint(bp_plans)
    app.register_blueprint(bp_usage)
    app.register_blueprint(bp_credits)
    app.register_blueprint(bp_invoices)
    app.register_blueprint(bp_trueup)
    app.register_blueprint(bp_forecasts)

    return app


app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
