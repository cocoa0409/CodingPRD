"""Route registration. One blueprint per resource group; all routes live in a
flat URL hierarchy (api_prefix is empty).
"""
from routes import (
    clock_routes,
    compliance,
    concepts,
    discontinuation,
    formulas,
    launch_plans,
    line_reviews,
    manufacturers,
    partners,
    products,
    quotes,
    slots,
    trends,
)


def register_all(app):
    for module in (
        clock_routes,
        trends,
        concepts,
        products,
        manufacturers,
        formulas,
        quotes,
        compliance,
        partners,
        line_reviews,
        slots,
        launch_plans,
        discontinuation,
    ):
        app.register_blueprint(module.bp)
