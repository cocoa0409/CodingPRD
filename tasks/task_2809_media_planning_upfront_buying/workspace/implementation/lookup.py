"""Identifier resolution (PRD 2.8): one not-found error per entity family."""

from errors import ApiError
from store import sorted_records, store

NOT_FOUND = {
    "advertisers": "ERR_ADVERTISER_NOT_FOUND",
    "campaigns": "ERR_CAMPAIGN_NOT_FOUND",
    "allocations": "ERR_ALLOCATION_NOT_FOUND",
    "sellers": "ERR_SELLER_NOT_FOUND",
    "forecasts": "ERR_FORECAST_NOT_FOUND",
    "negotiations": "ERR_NEGOTIATION_NOT_FOUND",
    "buys": "ERR_BUY_NOT_FOUND",
    "units": "ERR_BUY_UNIT_NOT_FOUND",
    "reports": "ERR_REPORT_NOT_FOUND",
    "make_goods": "ERR_MAKE_GOOD_NOT_FOUND",
    "rights": "ERR_RIGHTS_EXERCISE_NOT_FOUND",
    "runs": "ERR_RECONCILIATION_RUN_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
}


def get(collection, identifier):
    """Resolve an identifier or raise the collection's own 404."""
    table = getattr(store, collection)
    record = table.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(NOT_FOUND[collection])
    return record


def find(collection, **criteria):
    """Every record of a collection matching all criteria, default sorted."""
    table = getattr(store, collection)
    out = []
    for record in table.values():
        for key, value in criteria.items():
            if record.get(key) != value:
                break
        else:
            out.append(record)
    return sorted_records(out)
