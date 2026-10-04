"""Shared route plumbing: auth ladder, envelope emission, not-found helpers."""

from functools import wraps

from flask import jsonify, request

from core import auth, envelope, store
from core.errors import ApiError, fail


def api(roles):
    """Wrap a view with the authentication/authorisation ladder and envelope."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            store.begin_request()
            try:
                role, user_id = auth.authenticate()
                auth.authorize(role, roles)
                result = fn(role, user_id, *args, **kwargs)
                if not isinstance(result, envelope.Result):
                    result = envelope.Result(200, result)
                body = envelope.ok(
                    result.data, result.response_type, result.pagination
                )
                return jsonify(body), result.status
            except ApiError as exc:
                return jsonify(envelope.error(exc.error_id, exc.message)), exc.http_status
            except Exception as exc:  # pragma: no cover - defensive
                return (
                    jsonify(envelope.error("ERR_INTERNAL_ERROR", "%s: %s" % (type(exc).__name__, exc))),
                    500,
                )
            finally:
                store.end_request()

        return wrapper

    return decorator


def path_param(name):
    return request.view_args.get(name) if request.view_args else None


def resolve(collection, record_id, label):
    """Ladder 3 — a path identifier must resolve, left to right."""
    record = store.find(collection, record_id)
    if record is None:
        fail("ERR_NOT_FOUND", "%s %r does not exist" % (label, record_id))
    return record


def resolve_listing(listing_id):
    return resolve("listings", listing_id, "ClassListing")


def resolve_section(listing, section_id):
    section = resolve("sections", section_id, "Section")
    if section["class_listing_id"] != listing["id"]:
        fail("ERR_NOT_FOUND", "Section %r does not belong to this listing" % (section_id,))
    return section
