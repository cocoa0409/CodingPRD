"""Route package."""
from routes import (  # noqa: F401
    clock,
    compliance_routes,
    counseling_routes,
    dose_order_routes,
    dose_routes,
    exception_routes,
    guest_routes,
    inventory_routes,
    patient_routes,
    privilege_routes,
    program_routes,
    user_routes,
)

ALL = [
    clock,
    program_routes,
    user_routes,
    patient_routes,
    dose_order_routes,
    dose_routes,
    privilege_routes,
    exception_routes,
    inventory_routes,
    counseling_routes,
    guest_routes,
    compliance_routes,
]


def register(app):
    for module in ALL:
        app.register_blueprint(module.bp)