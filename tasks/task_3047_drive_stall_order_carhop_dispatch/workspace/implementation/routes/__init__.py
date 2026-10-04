"""Route blueprints."""
from flask import Blueprint

locations_bp = Blueprint("locations", __name__)
catalog_bp = Blueprint("catalog", __name__)
customers_bp = Blueprint("customers", __name__)
stalls_bp = Blueprint("stalls", __name__)
orders_bp = Blueprint("orders", __name__)
offers_bp = Blueprint("offers", __name__)
service_targets_bp = Blueprint("service_targets", __name__)
carhops_bp = Blueprint("carhops", __name__)
runs_bp = Blueprint("runs", __name__)
tips_bp = Blueprint("tips", __name__)
flat_bp = Blueprint("flat", __name__)
clock_bp = Blueprint("clock", __name__)

# Import route modules so their decorators register against the blueprints.
from . import (  # noqa: E402,F401
    locations,
    catalog,
    customers,
    stalls,
    orders,
    offers,
    service_targets,
    carhops,
    runs,
    tips,
    flat,
    clock,
)
