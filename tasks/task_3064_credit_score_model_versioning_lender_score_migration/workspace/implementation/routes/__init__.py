"""Route package."""

from routes.bureaus import bp as bureaus_bp
from routes.score_models import bp as score_models_bp
from routes.score_variants import bp as score_variants_bp
from routes.consumers import bp as consumers_bp
from routes.archive_samples import bp as archive_samples_bp
from routes.validation_studies import bp as validation_studies_bp
from routes.reference_sets import bp as reference_sets_bp
from routes.score_results import bp as score_results_bp
from routes.reason_codes import bp as reason_codes_bp
from routes.licenses import bp as licenses_bp
from routes.fee_ledger_entries import bp as fee_ledger_entries_bp
from routes.model_documentation import bp as model_documentation_bp
from routes.migration_events import bp as migration_events_bp
from routes.score_discovery_requests import bp as score_discovery_requests_bp
from routes.clock import bp as clock_bp

BLUEPRINTS = [
    bureaus_bp,
    score_models_bp,
    score_variants_bp,
    consumers_bp,
    archive_samples_bp,
    validation_studies_bp,
    reference_sets_bp,
    score_results_bp,
    reason_codes_bp,
    licenses_bp,
    fee_ledger_entries_bp,
    model_documentation_bp,
    migration_events_bp,
    score_discovery_requests_bp,
    clock_bp,
]