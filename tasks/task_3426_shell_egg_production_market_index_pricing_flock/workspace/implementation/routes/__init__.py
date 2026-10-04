"""Route registration: one blueprint per domain module."""

from .capital import bp as capital_bp
from .clock import bp as clock_bp
from .complexes import bp as complexes_bp
from .customers import bp as customers_bp
from .disease import bp as disease_bp
from .feed import bp as feed_bp
from .flocks import bp as flocks_bp
from .houses import bp as houses_bp
from .orders import bp as orders_bp
from .packing import bp as packing_bp
from .quotations import bp as quotations_bp

ALL_BLUEPRINTS = [
    clock_bp,
    complexes_bp,
    customers_bp,
    disease_bp,
    feed_bp,
    flocks_bp,
    houses_bp,
    orders_bp,
    packing_bp,
    quotations_bp,
    capital_bp,
]
