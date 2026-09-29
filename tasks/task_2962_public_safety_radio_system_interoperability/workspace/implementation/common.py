"""Shared route helpers: list pagination and agency-scope enforcement."""
import db
import response
import validate
from errors import ApiError

PREFIX = "/radio-system"

ANY_ROLE = validate.ALL_ROLES


def list_endpoint(collection, serializer, filters=()):
    limit, offset = validate.pagination()
    items = db.rows(collection)
    for field, value in filters:
        if value is not None:
            items = [row for row in items if row.get(field) == value]
    total = len(items)
    page = items[offset:offset + limit]
    return response.ok_list([serializer(row) for row in page], limit, offset, total)


def require_scope(actor, owner_agency_id):
    """Precedence step 9: agency-backed roles act only on their own rows."""
    if actor.is_agency_backed and actor.user_id != owner_agency_id:
        raise ApiError("ERR_AGENCY_SCOPE_VIOLATION")


def check_occ(parent, field, body):
    """Precedence step 8: the pinned parent version must match exactly."""
    expected = validate.req_int(body, field, 0)
    if expected != parent["version"]:
        raise ApiError("ERR_STALE_VERSION")
    return expected
