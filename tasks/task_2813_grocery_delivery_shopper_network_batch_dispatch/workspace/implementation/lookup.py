"""Path/body identifier resolution (rank 3 and rank 6 of PRD 2.8) and paging."""
from errors import fail
from response import ok_list
from store import all_rows, db, sort_key
from validation import pagination


def _find(collection, key, error_id):
    if not isinstance(key, str):
        fail(error_id)
    row = collection.get(key)
    if row is None:
        fail(error_id)
    return row


def retailer(key):
    return _find(db.retailers, key, "ERR_RETAILER_NOT_FOUND")


def catalog_item(key):
    return _find(db.catalog_items, key, "ERR_CATALOG_ITEM_NOT_FOUND")


def customer(key):
    return _find(db.customers, key, "ERR_CUSTOMER_NOT_FOUND")


def shopper(key):
    return _find(db.shoppers, key, "ERR_SHOPPER_NOT_FOUND")


def order(key):
    return _find(db.orders, key, "ERR_ORDER_NOT_FOUND")


def order_line(key):
    return _find(db.order_lines, key, "ERR_ORDER_LINE_NOT_FOUND")


def batch(key):
    return _find(db.batches, key, "ERR_BATCH_NOT_FOUND")


def replacement(key):
    return _find(db.replacements, key, "ERR_REPLACEMENT_NOT_FOUND")


def rating(key):
    return _find(db.shopper_ratings, key, "ERR_RATING_NOT_FOUND")


def payout(key):
    return _find(db.payouts, key, "ERR_PAYOUT_NOT_FOUND")


def credit_entry(key):
    return _find(db.credits, key, "ERR_CREDIT_ENTRY_NOT_FOUND")


def paged(collection, serializer, predicate=None):
    """List endpoint helper: order by created_at ASC, then apply the page window."""
    limit, offset = pagination()
    rows = all_rows(collection) if not isinstance(collection, list) else sorted(collection, key=sort_key)
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    total = len(rows)
    window = rows[offset : offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
