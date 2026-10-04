"""Route registration for the custody RIA API surface."""

from routes import (accounts, alternatives, batches, billing, evidence, feeds,
                    firms, models, money, ops, transfers)


def register_all(api):
    ops.register(api)
    firms.register(api)
    accounts.register(api)
    transfers.register(api)
    models.register(api)
    billing.register(api)
    alternatives.register(api)
    money.register(api)
    evidence.register(api)
    feeds.register(api)
    batches.register(api)