"""Blueprint registry.  Every route module contributes exactly one blueprint."""
from routes import (claims, clock, coverage_parts, equipment_items,
                    installation_floaters, jobsites, policies, rate_rules,
                    transit_shipments, value_reports, vehicles)

BLUEPRINTS = [
    rate_rules.bp,
    policies.bp,
    coverage_parts.bp,
    equipment_items.bp,
    jobsites.bp,
    installation_floaters.bp,
    vehicles.bp,
    transit_shipments.bp,
    value_reports.bp,
    claims.bp,
    clock.bp,
]
