"""The chain's diamond ledger."""

from flask import request

from db import DB
from middleware import guard
from response import (ApiError, Err, as_enum, as_num, as_str, body, created_obj,
                      ensure_known, ok_list, ok_obj, pagination, sorted_by_created)
from services import core


def register(app):
    @app.route("/diamonds", methods=["POST"])
    def create_diamond():
        guard(["SalesAssociate", "ChainAdmin"])
        data = body()
        ensure_known(data, ["stone_code", "stone_kind", "carat", "origin_registry"],
                     optional=("origin_registry",))
        stone_code = as_str(data, "stone_code")
        if any(d["stone_code"] == stone_code for d in DB.all("diamonds")):
            raise ApiError(Err.DUPLICATE_STONE_CODE, "The stone code is already on file.")
        diamond = core.new_row(
            "diamonds",
            stone_code=stone_code,
            stone_kind=as_enum(data, "stone_kind", ("NATURAL", "LAB_GROWN")),
            carat=as_num(data, "carat", required=True),
            origin_registry=as_str(data, "origin_registry", required=False),
            owner_customer_id=None,
            custody_status="IN_CASE",
        )
        return created_obj(diamond)

    @app.route("/diamonds", methods=["GET"])
    def list_diamonds():
        guard(["ChainAdmin", "StoreManager", "SalesAssociate", "CreditAnalyst"])
        limit, offset = pagination()
        rows = DB.all("diamonds")
        owner = request.args.get("owner_customer_id")
        if owner is not None:
            rows = [r for r in rows if r["owner_customer_id"] == owner]
        custody = request.args.get("custody_status")
        if custody is not None:
            rows = [r for r in rows if r["custody_status"] == custody]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/diamonds/<ident>", methods=["GET"])
    def get_diamond(ident):
        guard(["ChainAdmin", "StoreManager", "SalesAssociate", "CustomerService"])
        return ok_obj(core.fetch("diamonds", ident, "diamond"))