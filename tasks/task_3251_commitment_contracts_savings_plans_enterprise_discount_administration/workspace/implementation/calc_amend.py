from decimal import Decimal
from store import STORE, parse_dt


def amendment_rate_for(agreement, service_family, hour_start):
    """Return the discount_rate (Decimal) of the amendment covering this family+hour, or None.

    Half-open window [effective_from, effective_to). Assumes non-overlapping per family
    (enforced at creation); first match wins.
    """
    if agreement is None:
        return None
    for am in STORE.amendments.values():
        if am['agreement_id'] != agreement['id'] or am['service_family'] != service_family:
            continue
        if am['effective_from'] <= hour_start < am['effective_to']:
            return Decimal(str(am['discount_rate']))
    return None
