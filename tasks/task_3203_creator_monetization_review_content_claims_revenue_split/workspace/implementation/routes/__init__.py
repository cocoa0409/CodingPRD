"""HTTP route registration."""

from flask import Flask

from routes.claims import bp as claims_bp
from routes.channels import bp as channels_bp
from routes.clock import bp as clock_bp
from routes.content_items import bp as content_items_bp
from routes.payouts import bp as payouts_bp
from routes.reference_files import bp as reference_files_bp
from routes.revenue import bp as revenue_bp


def register_routes(app: Flask):
    app.register_blueprint(clock_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(content_items_bp)
    app.register_blueprint(reference_files_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(revenue_bp)
    app.register_blueprint(payouts_bp)