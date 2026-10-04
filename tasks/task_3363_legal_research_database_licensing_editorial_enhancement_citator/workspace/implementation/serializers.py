"""Entity serializers: strip internal fields and emit the PRD field sets."""

from db import store


def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def seats_used(subscription_id):
    """seats_used is computed, never stored: count of ACTIVE-seated users."""
    return sum(
        1
        for u in store.users.values()
        if u["seat_subscription_id"] == subscription_id and u["seat_status"] == "ACTIVE"
    )


def serialize_document(doc):
    return _public(doc)


def serialize_reference(ref):
    return _public(ref)


def serialize_headnote(hn):
    return _public(hn)


def serialize_plan(plan):
    return _public(plan)


def serialize_account(account):
    return _public(account)


def serialize_subscription(sub):
    data = _public(sub)
    data["seats_used"] = seats_used(sub["id"])
    return data


def serialize_user(user):
    return _public(user)


def serialize_usage_event(event):
    return _public(event)


def serialize_invoice(inv):
    return _public(inv)


def serialize_agreement(agreement):
    return _public(agreement)


def serialize_statement(stmt):
    return _public(stmt)


def serialize_order(order):
    return _public(order)
