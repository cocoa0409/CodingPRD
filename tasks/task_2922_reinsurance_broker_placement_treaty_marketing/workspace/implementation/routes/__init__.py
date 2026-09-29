"""Blueprint registration for every route module."""
from routes import (
    claims,
    counterparties,
    evidence,
    exposures,
    layers,
    lines,
    money,
    programs,
    quotes,
)

BLUEPRINTS = (
    counterparties.bp,
    programs.bp,
    exposures.bp,
    layers.bp,
    quotes.bp,
    lines.bp,
    money.bp,
    claims.bp,
    evidence.bp,
)


def register(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
