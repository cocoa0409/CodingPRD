"""Route registration: one blueprint per resource group."""

from routes import (
    agreements,
    changeorders,
    contractors,
    milestones,
    registry,
    reviews,
    royalties,
)

MODULES = (registry, agreements, milestones, reviews, changeorders, contractors, royalties)


def register_all(app):
    for module in MODULES:
        app.register_blueprint(module.bp)
