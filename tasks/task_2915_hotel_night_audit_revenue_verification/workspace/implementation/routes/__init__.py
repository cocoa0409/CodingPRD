from routes.clock import bp as clock_bp
from routes.properties import bp as properties_bp
from routes.outlets import bp as outlets_bp
from routes.ledger_accounts import bp as ledger_accounts_bp
from routes.periods import bp as periods_bp
from routes.business_dates import bp as business_dates_bp
from routes.folios import bp as folios_bp
from routes.journal import bp as journal_bp
from routes.tickets import bp as tickets_bp
from routes.batches import bp as batches_bp
from routes.allowances import bp as allowances_bp
from routes.documents import bp as documents_bp
from routes.cards import bp as cards_bp
from routes.reports import bp as reports_bp

BLUEPRINTS = (
    clock_bp,
    properties_bp,
    outlets_bp,
    ledger_accounts_bp,
    periods_bp,
    business_dates_bp,
    folios_bp,
    journal_bp,
    tickets_bp,
    batches_bp,
    allowances_bp,
    documents_bp,
    cards_bp,
    reports_bp,
)
