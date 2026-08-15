"""Route registration."""


def register_all(app):
    from routes import (clock, clients, carriers, contracts, shipments,
                        invoices, exceptions, finance, payments, claims,
                        analytics)
    for module in (clock, clients, carriers, contracts, shipments, invoices,
                   exceptions, finance, payments, claims, analytics):
        module.register(app)
