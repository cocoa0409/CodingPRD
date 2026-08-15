"""Flat, shop-agnostic two-segment GET endpoints for every child entity."""

from flask import request

from db import db
from errors import ApiError, ERR_NOT_FOUND
from helpers import paginate
from middleware import current_user
from response import success_object, success_list
import serializers


# (url_segment, store_attr, serializer, list_filters)
FLAT_RESOURCES = [
    ("welders", "welders", serializers.welder_out, ["shop_id"]),
    ("ndt-vendors", "ndt_vendors", serializers.ndt_vendor_out, ["shop_id"]),
    ("ovens", "ovens", serializers.oven_out, ["shop_id"]),
    ("pqrs", "pqrs", serializers.pqr_out, ["shop_id"]),
    ("wps", "wps", serializers.wps_out, ["shop_id", "pqr_id", "superseded_by_id"]),
    ("welder-qualifications", "qualifications", serializers.qualification_out,
     ["shop_id", "welder_id", "wps_id"]),
    ("consumable-lots", "lots", serializers.lot_out,
     ["shop_id", "oven_id", "status"]),
    ("consumable-issues", "issues", serializers.issue_out,
     ["shop_id", "lot_id", "oven_id", "issued_to_welder_id"]),
    ("fixtures", "fixtures", serializers.fixture_out, ["shop_id"]),
    ("shop-orders", "orders", serializers.order_out, ["shop_id"]),
    ("weldments", "weldments", serializers.weldment_out,
     ["shop_id", "shop_order_id", "fixture_id"]),
    ("joints", "joints", serializers.joint_out, ["shop_id", "weldment_id", "wps_id"]),
    ("weld-passes", "weld_passes", serializers.weld_pass_out,
     ["shop_id", "joint_id", "welder_id", "qualification_id", "consumable_lot_id"]),
    ("distortion-reports", "distortion_reports", serializers.distortion_report_out,
     ["shop_id", "weldment_id", "joint_id"]),
    ("inspections", "inspections", serializers.inspection_out,
     ["shop_id", "joint_id", "vendor_id"]),
    ("traveler-sign-offs", "sign_offs", serializers.sign_off_out,
     ["shop_id", "weldment_id"]),
]


def register_flat_routes(app):
    for segment, store_attr, serializer, filters in FLAT_RESOURCES:
        table_name = store_attr

        def make_get_one(table_name=table_name, serializer=serializer, segment=segment):
            def get_one(record_id):
                current_user()
                rec = getattr(db, table_name).get(record_id)
                if rec is None:
                    raise ApiError(ERR_NOT_FOUND, 404, "Resource not found")
                return success_object(serializer(rec))
            return get_one

        def make_list(table_name=table_name, serializer=serializer, filters=filters):
            def list_all():
                current_user()
                records = list(getattr(db, table_name).values())
                for param in filters:
                    value = request.args.get(param)
                    if value is not None:
                        records = [r for r in records if r.get(param) == value]
                page, limit, offset, total = paginate(records)
                return success_list([serializer(r) for r in page], limit, offset, total)
            return list_all

        app.add_url_rule(
            f"/weld-shop/{segment}/<record_id>",
            endpoint=f"flat_get_{segment}",
            view_func=make_get_one(),
            methods=["GET"],
        )
        app.add_url_rule(
            f"/weld-shop/{segment}",
            endpoint=f"flat_list_{segment}",
            view_func=make_list(),
            methods=["GET"],
        )
