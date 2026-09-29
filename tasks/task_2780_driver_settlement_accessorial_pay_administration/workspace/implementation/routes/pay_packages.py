"""Pay-package configuration endpoints (PRD section 3.1)."""
from flask import Blueprint, request

import clock
import constants
import db
import listing
import middleware
import queries
import response
import serializers
import validators
from errors import ApiError

bp = Blueprint("pay_packages", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

OFFICE_READ = (ADMIN, CLERK, APPROVER, AUDITOR)


def find_package(package_id):
    package = db.pay_packages.get(package_id)
    if package is None:
        raise ApiError("ERR_PAY_PACKAGE_NOT_FOUND")
    return package


@bp.route("/driver-pay/pay-packages", methods=["POST"])
def create_pay_package():
    middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(
        body, ["name", "driver_type", "mileage_guide", "per_diem_method", "escrow_required"]
    )
    record = {
        "name": validators.string_value(body, "name", required=True),
        "driver_type": validators.enum_value(body, "driver_type", constants.DRIVER_TYPES, required=True),
        "mileage_guide": validators.enum_value(body, "mileage_guide", constants.MILEAGE_GUIDES, required=True),
        "per_diem_method": validators.enum_value(body, "per_diem_method", constants.PER_DIEM_METHODS, required=True),
        "escrow_required": validators.bool_value(body, "escrow_required", required=True),
        "escrow_target_cents": validators.int_value(body, "escrow_target_cents", default=0, minimum=0),
        "escrow_monthly_deduction_cents": validators.int_value(
            body, "escrow_monthly_deduction_cents", default=0, minimum=0
        ),
        "status": "DRAFT",
        "supersedes_pay_package_id": None,
        "has_pending_revision": False,
        "activated_at": None,
        "retired_at": None,
    }
    db.stamp_new(record)
    db.pay_packages[record["id"]] = record
    return response.object_response(serializers.pay_package(record), 201)


@bp.route("/driver-pay/pay-packages", methods=["GET"])
def list_pay_packages():
    middleware.authorize(*OFFICE_READ)
    rows = db.ordered(db.pay_packages)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("status", "status", constants.PAY_PACKAGE_STATUSES),
            ("driver_type", "driver_type", constants.DRIVER_TYPES),
            ("supersedes_pay_package_id", "supersedes_pay_package_id", None),
        ],
    )
    return listing.page(rows, request.args, serializers.pay_package)


@bp.route("/driver-pay/pay-packages/<package_id>", methods=["GET"])
def read_pay_package(package_id):
    middleware.authorize(*OFFICE_READ)
    return response.object_response(serializers.pay_package(find_package(package_id)))


@bp.route("/driver-pay/pay-packages/<package_id>/components", methods=["POST"])
def append_component(package_id):
    middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["component_type", "unit", "rate_value", "sequence"])
    component_type = validators.enum_value(body, "component_type", constants.COMPONENT_TYPES, required=True)
    unit = validators.enum_value(body, "unit", constants.COMPONENT_UNITS, required=True)
    rate_value = validators.int_value(body, "rate_value", required=True, minimum=1)
    sequence = validators.int_value(body, "sequence", required=True, minimum=1)
    taxable = validators.bool_value(body, "taxable", default=True)
    if constants.COMPONENT_UNIT_PAIRS[component_type] != unit:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "A %s component must be expressed in %s."
            % (component_type, constants.COMPONENT_UNIT_PAIRS[component_type]),
        )

    package = find_package(package_id)
    if package["status"] != "DRAFT":
        raise ApiError("ERR_PAY_PACKAGE_NOT_ACTIVE")

    existing = queries.components_of(package_id)
    for other in existing:
        if other["sequence"] == sequence or other["component_type"] == component_type:
            raise ApiError("ERR_DUPLICATE_COMPONENT")

    if component_type == "HOURLY" and package["driver_type"] in ("OWNER_OPERATOR", "LEASED_OPERATOR"):
        raise ApiError("ERR_COMPONENT_TYPE_NOT_ALLOWED")
    if component_type == "REVENUE_PERCENT" and package["driver_type"] in ("COMPANY_SOLO", "COMPANY_TEAM"):
        raise ApiError("ERR_COMPONENT_TYPE_NOT_ALLOWED")

    component = {
        "pay_package_id": package_id,
        "component_type": component_type,
        "unit": unit,
        "rate_value": rate_value,
        "taxable": taxable,
        "sequence": sequence,
    }
    db.stamp_log(component)
    db.pay_components[component["id"]] = component
    db.touch(package)
    return response.object_response(serializers.pay_component(component), 201)


@bp.route("/driver-pay/pay-packages/<package_id>/components", methods=["GET"])
def list_components(package_id):
    middleware.authorize(ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)
    find_package(package_id)
    rows = queries.components_of(package_id)
    return listing.page(rows, request.args, serializers.pay_component)


@bp.route("/driver-pay/pay-packages/<package_id>/activate", methods=["POST"])
def activate_package(package_id):
    middleware.authorize(ADMIN)
    package = find_package(package_id)
    if package["status"] != "DRAFT":
        raise ApiError("ERR_PAY_PACKAGE_NOT_ACTIVE")
    if package["escrow_required"] and (
        package["escrow_target_cents"] <= 0 or package["escrow_monthly_deduction_cents"] <= 0
    ):
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "An escrow package must carry a positive target and monthly deduction.",
        )
    components = queries.components_of(package_id)
    if not any(c["component_type"] in ("PER_MILE", "REVENUE_PERCENT") for c in components):
        raise ApiError("ERR_PACKAGE_HAS_NO_LINEHAUL_COMPONENT")

    package["status"] = "ACTIVE"
    package["activated_at"] = clock.now()
    db.touch(package)

    predecessor_id = package["supersedes_pay_package_id"]
    if predecessor_id:
        predecessor = db.pay_packages.get(predecessor_id)
        if predecessor is not None and predecessor["status"] == "ACTIVE":
            predecessor["status"] = "RETIRED"
            predecessor["retired_at"] = clock.now()
            predecessor["has_pending_revision"] = False
            db.touch(predecessor)
    return response.object_response(serializers.pay_package(package))


@bp.route("/driver-pay/pay-packages/<package_id>/revise", methods=["POST"])
def revise_package(package_id):
    middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["expected_pay_package_version"])
    expected = validators.int_value(body, "expected_pay_package_version", required=True, minimum=0)
    name = validators.string_value(body, "name")
    per_diem_method = validators.enum_value(body, "per_diem_method", constants.PER_DIEM_METHODS)
    escrow_target = validators.int_value(body, "escrow_target_cents", minimum=0)
    escrow_monthly = validators.int_value(body, "escrow_monthly_deduction_cents", minimum=0)
    validators.check_enum(body.get("mileage_guide"), "mileage_guide", constants.MILEAGE_GUIDES)

    package = find_package(package_id)
    if expected != package["version"]:
        raise ApiError("ERR_STALE_PAY_PACKAGE_VERSION")
    if package["status"] != "ACTIVE":
        raise ApiError("ERR_PAY_PACKAGE_NOT_ACTIVE")
    if package["has_pending_revision"]:
        raise ApiError("ERR_PAY_PACKAGE_REVISION_PENDING")

    successor = {
        "name": name if name is not None else package["name"],
        "driver_type": package["driver_type"],
        # The mileage guide is immutable across a revision chain.
        "mileage_guide": package["mileage_guide"],
        "per_diem_method": per_diem_method if per_diem_method is not None else package["per_diem_method"],
        "escrow_required": package["escrow_required"],
        "escrow_target_cents": escrow_target if escrow_target is not None else package["escrow_target_cents"],
        "escrow_monthly_deduction_cents": (
            escrow_monthly if escrow_monthly is not None else package["escrow_monthly_deduction_cents"]
        ),
        "status": "DRAFT",
        "supersedes_pay_package_id": package_id,
        "has_pending_revision": False,
        "activated_at": None,
        "retired_at": None,
    }
    db.stamp_new(successor)
    db.pay_packages[successor["id"]] = successor

    for component in queries.components_of(package_id):
        copy = {
            "pay_package_id": successor["id"],
            "component_type": component["component_type"],
            "unit": component["unit"],
            "rate_value": component["rate_value"],
            "taxable": component["taxable"],
            "sequence": component["sequence"],
        }
        db.stamp_log(copy)
        db.pay_components[copy["id"]] = copy

    package["has_pending_revision"] = True
    db.touch(package)
    return response.object_response(serializers.pay_package(successor), 201)


@bp.route("/driver-pay/pay-packages/<package_id>/retire", methods=["POST"])
def retire_package(package_id):
    middleware.authorize(ADMIN)
    package = find_package(package_id)
    if package["status"] != "ACTIVE":
        raise ApiError("ERR_PAY_PACKAGE_NOT_ACTIVE")
    if package["has_pending_revision"]:
        raise ApiError("ERR_PAY_PACKAGE_REVISION_PENDING")
    package["status"] = "RETIRED"
    package["retired_at"] = clock.now()
    db.touch(package)
    return response.object_response(serializers.pay_package(package))
