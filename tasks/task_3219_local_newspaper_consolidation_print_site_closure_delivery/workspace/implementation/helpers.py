"""Helpers shared by the resource blueprints."""
from flask import jsonify

from core import DB, envelope, paginate
from models import new_row, apply_input, bump, touch


def ok(data, code=200, pagination=None):
    rtype = "array" if isinstance(data, list) else "object"
    return jsonify(envelope(data, rtype, pagination)), code


def ok_object(data, code=200):
    return jsonify(envelope(data, "object")), code


def ok_list(rows, limit, offset, code=200):
    page, paging = paginate(rows, limit, offset)
    return jsonify(envelope(page, "array", paging)), code


def create(coll, data, required, system=None, extra_allowed=()):
    row = new_row(coll, system=system)
    apply_input(coll, row, data, required, extra_allowed=extra_allowed)
    return DB.put(coll, row)


def sort_by_created(rows):
    return sorted(rows, key=lambda r: (str(r.get("created_at") or ""),
                                       str(r.get("id") or "")))


def hub_id(param):
    return param