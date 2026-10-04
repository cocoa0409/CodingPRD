"""Route package: blueprints are registered here so app.py owns only wiring."""

from routes.clock import bp as clock_bp
from routes.accounts import bp as accounts_bp
from routes.clusters import bp as clusters_bp
from routes.links import bp as links_bp
from routes.trips import bp as trips_bp
from routes.incidents import bp as incidents_bp
from routes.enforcement import bp as enforcement_bp
from routes.reports import bp as reports_bp
from routes.checks import bp as checks_bp
from routes.policies import bp as policies_bp

BLUEPRINTS = (
    clock_bp,
    accounts_bp,
    clusters_bp,
    links_bp,
    trips_bp,
    incidents_bp,
    enforcement_bp,
    reports_bp,
    checks_bp,
    policies_bp,
)


def register_blueprints(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)