"""Route package for the Integrated Payer-Provider Budgeting API."""

from routes.admin import bp as admin_bp
from routes.appointments import bp as appointments_bp
from routes.budgets import bp as budgets_bp
from routes.claims import bp as claims_bp
from routes.integrations import bp as integrations_bp
from routes.network import bp as network_bp
from routes.quality import bp as quality_bp
from routes.referrals import bp as referrals_bp
from routes.regions import bp as regions_bp
from routes.sites import bp as sites_bp
from routes.transfers import bp as transfers_bp

ALL_BLUEPRINTS = (
    regions_bp,
    sites_bp,
    network_bp,
    appointments_bp,
    referrals_bp,
    claims_bp,
    budgets_bp,
    transfers_bp,
    quality_bp,
    integrations_bp,
    admin_bp,
)