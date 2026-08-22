from . import (
    clock_routes,
    party_routes,
    judgment_routes,
    filing_routes,
    asset_routes,
    enforcement_routes,
    exemption_routes,
    exam_routes,
    offer_routes,
    agreement_routes,
    payment_routes,
)

MODULES = (
    clock_routes,
    party_routes,
    judgment_routes,
    filing_routes,
    asset_routes,
    enforcement_routes,
    exemption_routes,
    exam_routes,
    offer_routes,
    agreement_routes,
    payment_routes,
)


def register(app):
    for module in MODULES:
        module.register(app)
