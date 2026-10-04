"""Route blueprints, one module per resource domain."""

from routes.charges import bp as charges_bp
from routes.clock_routes import bp as clock_bp
from routes.conciliation import bp as conciliation_bp
from routes.determinations import bp as determinations_bp
from routes.disclosures import bp as disclosures_bp
from routes.investigation import bp as investigation_bp
from routes.mediation import bp as mediation_bp
from routes.reference import bp as reference_bp
from routes.rts import bp as rts_bp
from routes.systemic import bp as systemic_bp

ALL_BLUEPRINTS = (
    clock_bp,
    reference_bp,
    charges_bp,
    mediation_bp,
    investigation_bp,
    determinations_bp,
    conciliation_bp,
    rts_bp,
    systemic_bp,
    disclosures_bp,
)
