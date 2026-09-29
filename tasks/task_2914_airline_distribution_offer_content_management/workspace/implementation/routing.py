"""Helpers that keep the PRD 2.10 validation precedence honest.

Path and body references have to be *resolved* before an ownership comparison
(step 2) can be made, yet a resolution failure (steps 4-5) must not outrank an
earlier check. `Pending` defers the not-found error until the caller decides
the precedence order is right.
"""
from errors import ApiError


class Pending:
    def __init__(self):
        self.error = None

    def resolve(self, table, key, error_id):
        entity = table.get(key) if isinstance(key, str) else None
        if entity is None and self.error is None:
            self.error = ApiError(error_id)
        return entity

    def raise_if_missing(self):
        if self.error is not None:
            raise self.error


def owner_of(entity, field="partner_id"):
    if entity is None:
        return None
    return entity.get(field)


def resolve_owned(table, key, error_id, actor, field="partner_id"):
    """Resolve a path id, apply the step-2 ownership check, defer the 404.

    Returns (pending, entity). The caller performs shape validation and then
    calls pending.raise_if_missing() so a 403 outranks a 404 while a 404 still
    outranks every body-level check.
    """
    pending = Pending()
    entity = pending.resolve(table, key, error_id)
    actor.require_owner(owner_of(entity, field))
    return pending, entity


def precheck_self(actor, raw, field):
    """Step-2 ownership on a body field naming the acting partner itself."""
    if not actor.entity_backed:
        return
    value = raw.get(field)
    if isinstance(value, str) and value != actor.user_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "The acting principal does not own the target resource.")


def precheck_ref(actor, raw, field, table, owner_field="partner_id"):
    """Step-2 ownership on a body field naming an owned resource."""
    if not actor.entity_backed:
        return
    value = raw.get(field)
    if not isinstance(value, str):
        return
    entity = table.get(value)
    if entity is not None:
        actor.require_owner(owner_of(entity, owner_field))
