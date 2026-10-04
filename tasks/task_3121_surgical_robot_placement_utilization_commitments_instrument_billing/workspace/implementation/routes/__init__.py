"""Route blueprints, one module per resource group."""

from routes.accounts import bp as accounts_bp
from routes.agreements import bp as agreements_bp
from routes.cases import bp as cases_bp
from routes.configs import bp as configs_bp
from routes.expansion import bp as expansion_bp
from routes.ops import bp as ops_bp
from routes.readiness import bp as readiness_bp
from routes.service import bp as service_bp
from routes.systems import bp as systems_bp
from routes.training import bp as training_bp

ALL_BLUEPRINTS = (
    ops_bp,
    accounts_bp,
    readiness_bp,
    configs_bp,
    agreements_bp,
    systems_bp,
    cases_bp,
    training_bp,
    service_bp,
    expansion_bp,
)