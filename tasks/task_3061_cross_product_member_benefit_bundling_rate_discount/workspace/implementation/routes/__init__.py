"""Flask blueprints, one module per resource group."""

from routes import clock, coaching, crosssell, cycles, deposits, entitlements, holdings, loans
from routes import members, notices, rewards, rules

BLUEPRINTS = (
    clock.BP,
    members.BP,
    holdings.BP,
    loans.BP,
    rules.BP,
    deposits.BP,
    entitlements.BP,
    rewards.BP,
    cycles.BP,
    notices.BP,
    coaching.BP,
    crosssell.BP,
)


def register(app):
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)