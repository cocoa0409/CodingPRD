"""Route blueprints. Each module registers the endpoints of one workflow area."""

from routes.clock import bp as clock_bp
from routes.funds import bp as funds_bp
from routes.protocols import bp as protocols_bp
from routes.holds import bp as holds_bp
from routes.referrals import bp as referrals_bp
from routes.facilities import bp as facilities_bp
from routes.assignments import bp as assignments_bp
from routes.enrollments import bp as enrollments_bp
from routes.pledges import bp as pledges_bp
from routes.travel import bp as travel_bp
from routes.affiliates import bp as affiliates_bp
from routes.milestones import bp as milestones_bp
from routes.survivorship import bp as survivorship_bp
from routes.services import bp as services_bp
from routes.siblings import bp as siblings_bp

ALL_BLUEPRINTS = [
    clock_bp,
    funds_bp,
    protocols_bp,
    holds_bp,
    referrals_bp,
    facilities_bp,
    assignments_bp,
    enrollments_bp,
    pledges_bp,
    travel_bp,
    affiliates_bp,
    milestones_bp,
    survivorship_bp,
    services_bp,
    siblings_bp,
]