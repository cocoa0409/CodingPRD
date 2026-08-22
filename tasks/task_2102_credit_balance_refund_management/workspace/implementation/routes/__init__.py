from routes.ops import bp as ops_bp
from routes.payers import bp as payers_bp
from routes.accounts import bp as accounts_bp
from routes.credit_balances import bp as credit_balances_bp
from routes.findings import bp as findings_bp
from routes.refunds import bp as refunds_bp
from routes.batches import bp as batches_bp
from routes.takebacks import bp as takebacks_bp
from routes.medicare import bp as medicare_bp
from routes.escheatment import bp as escheatment_bp
from routes.reports import bp as reports_bp

ALL_BLUEPRINTS = (
    ops_bp,
    payers_bp,
    accounts_bp,
    credit_balances_bp,
    findings_bp,
    refunds_bp,
    batches_bp,
    takebacks_bp,
    medicare_bp,
    escheatment_bp,
    reports_bp,
)
