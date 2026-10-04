from routes.clubs_tiers import bp as clubs_tiers_bp
from routes.memberships import bp as memberships_bp
from routes.household import bp as household_bp
from routes.providers import bp as providers_bp
from routes.calls import bp as calls_bp
from routes.settlement import bp as settlement_bp
from routes.ancillary import bp as ancillary_bp
from routes.clock import bp as clock_bp

ALL_BLUEPRINTS = [
    clock_bp,
    clubs_tiers_bp,
    memberships_bp,
    household_bp,
    providers_bp,
    calls_bp,
    settlement_bp,
    ancillary_bp,
]
