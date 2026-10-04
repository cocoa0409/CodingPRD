import os

from flask import Flask

from db import db
from response import register_error_handlers
import routes_authority
import routes_bookings
import routes_credit
import routes_fraud
import routes_orgs
import routes_posts
import routes_rates
import routes_subs


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    register_error_handlers(app)
    for module in (
        routes_orgs,
        routes_subs,
        routes_posts,
        routes_bookings,
        routes_rates,
        routes_credit,
        routes_authority,
        routes_fraud,
    ):
        app.register_blueprint(module.bp)

    @app.before_request
    def _serialize():
        db.lock.acquire()

    @app.after_request
    def _release(response):
        db.lock.release()
        return response

    @app.teardown_request
    def _release_on_error(exc):
        while db.lock._is_owned():
            try:
                db.lock.release()
            except RuntimeError:
                break

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
