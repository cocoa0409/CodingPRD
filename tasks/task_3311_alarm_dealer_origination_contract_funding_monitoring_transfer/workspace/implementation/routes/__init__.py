"""Route groups."""

from routes import (alarms, assumptions, attrition, contracts, customers,
                    dealers, monitoring)


def register_all(app):
    dealers.register(app)
    contracts.register(app)
    customers.register(app)
    monitoring.register(app)
    alarms.register(app)
    attrition.register(app)
    from routes import visits
    visits.register(app)
    assumptions.register(app)