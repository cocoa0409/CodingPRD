"""Route registration: one module per resource group."""

from routes import (assignments, backorders, catalog, certifications, clock,
                    exchanges, instruments, quotes, support, warranty)

MODULES = (
    clock,
    catalog,
    assignments,
    quotes,
    instruments,
    warranty,
    support,
    backorders,
    exchanges,
    certifications,
)


def register_all(app):
    for module in MODULES:
        module.register(app)