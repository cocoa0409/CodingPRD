"""Blueprint registry.

Every business blueprint is mounted under `/upfront`; the admin clock
capability is mounted at the root because its path is `/_clock/...`.
"""

from routes.advertisers import bp as advertisers_bp
from routes.allocations import bp as allocations_bp
from routes.buy_units import bp as buy_units_bp
from routes.buys import bp as buys_bp
from routes.campaigns import bp as campaigns_bp
from routes.clock import bp as clock_bp
from routes.delivery_reports import bp as delivery_reports_bp
from routes.forecasts import bp as forecasts_bp
from routes.invoices import bp as invoices_bp
from routes.make_goods import bp as make_goods_bp
from routes.negotiations import bp as negotiations_bp
from routes.reconciliation import bp as reconciliation_bp
from routes.rights import bp as rights_bp
from routes.sellers import bp as sellers_bp

UPFRONT_BLUEPRINTS = (
    advertisers_bp,
    campaigns_bp,
    allocations_bp,
    sellers_bp,
    forecasts_bp,
    negotiations_bp,
    buys_bp,
    buy_units_bp,
    delivery_reports_bp,
    make_goods_bp,
    rights_bp,
    reconciliation_bp,
    invoices_bp,
)

ROOT_BLUEPRINTS = (clock_bp,)
