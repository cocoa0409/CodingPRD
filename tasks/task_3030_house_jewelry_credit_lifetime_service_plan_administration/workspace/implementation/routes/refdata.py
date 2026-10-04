"""Bench shops and protection bundles."""

from flask import request

from db import DB
from middleware import guard
from response import (ApiError, Err, as_int, as_str, body, created_obj,
                      ensure_known, ok_list, ok_obj, pagination,
                      sorted_by_created)
from services import core


def register(app):
    # --- vendor shops ----------------------------------------------------
    @app.route("/vendor-shops", methods=["POST"])
    def create_vendor_shop():
        guard(["ChainAdmin"])
        data = body()
        ensure_known(data, ["shop_code", "shop_name", "base_turnaround_days",
                            "rush_surcharge_cents"],
                     optional=("rush_surcharge_cents",))
        shop_code = as_str(data, "shop_code")
        if core.vendor_shop_by_code(shop_code) is not None:
            raise ApiError(Err.DUPLICATE_STONE_CODE, "The shop code is already on file.")
        row = core.new_row(
            "vendor_shops",
            shop_code=shop_code,
            shop_name=as_str(data, "shop_name"),
            vendor_status="ACTIVE",
            base_turnaround_days=as_int(data, "base_turnaround_days", required=True),
            rush_surcharge_cents=as_int(data, "rush_surcharge_cents", default=0),
            open_repair_count=0,
        )
        return created_obj(row)

    @app.route("/vendor-shops", methods=["GET"])
    def list_vendor_shops():
        guard(["ChainAdmin", "StoreManager", "CustomerService"])
        limit, offset = pagination()
        rows = DB.all("vendor_shops")
        status = request.args.get("vendor_status")
        if status is not None:
            rows = [r for r in rows if r["vendor_status"] == status]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    # --- protection bundles ----------------------------------------------
    @app.route("/protection-bundles", methods=["POST"])
    def create_bundle():
        guard(["ChainAdmin"])
        data = body()
        ensure_known(data, ["bundle_code", "display_name", "lifetime_plan_fee_cents",
                            "stone_limit_labor_cents", "stone_limit_parts_cents",
                            "inspection_interval_days", "inspection_cure_days"],
                     optional=("inspection_interval_days", "inspection_cure_days"))
        bundle_code = as_str(data, "bundle_code")
        if any(b["bundle_code"] == bundle_code for b in DB.all("bundles")):
            raise ApiError(Err.DUPLICATE_STONE_CODE, "The bundle code is already on file.")
        row = core.new_row(
            "bundles",
            bundle_code=bundle_code,
            display_name=as_str(data, "display_name"),
            bundle_status="CURRENT",
            lifetime_plan_fee_cents=as_int(data, "lifetime_plan_fee_cents", required=True),
            stone_limit_labor_cents=as_int(data, "stone_limit_labor_cents", required=True),
            stone_limit_parts_cents=as_int(data, "stone_limit_parts_cents", required=True),
            inspection_interval_days=as_int(data, "inspection_interval_days", default=180),
            inspection_cure_days=as_int(data, "inspection_cure_days", default=30),
        )
        return created_obj(row)

    @app.route("/protection-bundles", methods=["GET"])
    def list_bundles():
        guard(["ChainAdmin", "StoreManager", "SalesAssociate", "CustomerService"])
        limit, offset = pagination()
        rows = DB.all("bundles")
        status = request.args.get("bundle_status")
        if status is not None:
            rows = [r for r in rows if r["bundle_status"] == status]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/protection-bundles/<ident>/retire", methods=["POST"])
    def retire_bundle(ident):
        guard(["ChainAdmin"])
        bundle = core.fetch("bundles", ident, "protection bundle")
        bundle["bundle_status"] = "RETIRED"
        core.touch(bundle)
        return ok_obj(bundle)