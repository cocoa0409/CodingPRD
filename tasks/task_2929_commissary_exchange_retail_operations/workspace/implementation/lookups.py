"""Identifier resolution.  Each addressable collection has its own not-found
code, and the code returned always names the resource whose identifier failed
(PRD 2.10)."""

from db import db
from errors import ApiError


def _resolve(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def store(identifier):
    return _resolve(db.stores, identifier, "ERR_STORE_NOT_FOUND")


def patron(identifier):
    return _resolve(db.patrons, identifier, "ERR_PATRON_NOT_FOUND")


def product(identifier):
    return _resolve(db.products, identifier, "ERR_PRODUCT_NOT_FOUND")


def assortment(identifier):
    return _resolve(db.assortments, identifier, "ERR_ASSORTMENT_NOT_FOUND")


def sale(identifier):
    return _resolve(db.sales, identifier, "ERR_SALE_NOT_FOUND")


def sale_line(identifier):
    return _resolve(db.sale_lines, identifier, "ERR_SALE_LINE_NOT_FOUND")


def delegation(identifier):
    return _resolve(db.delegations, identifier, "ERR_DELEGATION_NOT_FOUND")


def project(identifier):
    return _resolve(db.projects, identifier, "ERR_PROJECT_NOT_FOUND")


def special_order(identifier):
    return _resolve(db.special_orders, identifier, "ERR_SPECIAL_ORDER_NOT_FOUND")


def program(identifier):
    return _resolve(db.programs, identifier, "ERR_MWR_PROGRAM_NOT_FOUND")
