"""Blueprint registry: every declared endpoint is mounted from these modules."""

from routes.read import bp as read_bp
from routes.schemes import bp as schemes_bp
from routes.assessors import bp as assessors_bp
from routes.applications import bp as applications_bp
from routes.planning import bp as planning_bp
from routes.findings import bp as findings_bp
from routes.decisions import bp as decisions_bp
from routes.complaints import bp as complaints_bp
from routes.clock import bp as clock_bp

BLUEPRINTS = (
    read_bp,
    schemes_bp,
    assessors_bp,
    applications_bp,
    planning_bp,
    findings_bp,
    decisions_bp,
    complaints_bp,
    clock_bp,
)
