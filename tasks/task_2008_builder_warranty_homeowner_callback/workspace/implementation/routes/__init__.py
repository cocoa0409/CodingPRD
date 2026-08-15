from routes.homeowners import bp as homeowners_bp
from routes.homes import bp as homes_bp
from routes.service_requests import bp as service_requests_bp
from routes.work_orders import bp as work_orders_bp
from routes.trade_partners import bp as trade_partners_bp
from routes.chargebacks import bp as chargebacks_bp
from routes.reserves import bp as reserves_bp
from routes.claims import bp as claims_bp
from routes.ops import bp as ops_bp


def register_routes(app):
    for bp in (homeowners_bp, homes_bp, service_requests_bp, work_orders_bp,
               trade_partners_bp, chargebacks_bp, reserves_bp, claims_bp, ops_bp):
        app.register_blueprint(bp)
