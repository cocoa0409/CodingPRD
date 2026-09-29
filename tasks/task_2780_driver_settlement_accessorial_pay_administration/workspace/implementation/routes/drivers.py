"""Driver records, the employment axis and the maintenance escrow account
(PRD sections 3.2 and 3.3)."""
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
from services import escrow as escrow_service

bp = Blueprint("drivers", __name__)

ADMIN = constants.ROLE_PAYROLL_ADMIN
CLERK = constants.ROLE_SETTLEMENT_CLERK
APPROVER = constants.ROLE_SETTLEMENT_APPROVER
AUDITOR = constants.ROLE_COMPLIANCE_AUDITOR
DRIVER = constants.ROLE_DRIVER

OFFICE_READ = (ADMIN, CLERK, APPROVER, AUDITOR)
ALL_READ = (ADMIN, CLERK, APPROVER, AUDITOR, DRIVER)

EMPLOYMENT_TRANSITIONS = {
    ("ONBOARDING", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
}


def find_driver(driver_id):
    driver = db.drivers.get(driver_id)
    if driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")
    return driver


@bp.route("/driver-pay/drivers", methods=["POST"])
def create_driver():
    middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["legal_name", "driver_type"])
    record = {
        "legal_name": validators.string_value(body, "legal_name", required=True),
        "driver_type": validators.enum_value(body, "driver_type", constants.DRIVER_TYPES, required=True),
        "pay_package_id": None,
        "home_state": validators.string_value(body, "home_state"),
        "per_diem_elected": validators.bool_value(body, "per_diem_elected", default=False),
        "employment_status": "ONBOARDING",
        "terminated_at": None,
        "escrow_status": "NOT_REQUIRED",
        "escrow_target_cents": 0,
        "escrow_monthly_deduction_cents": 0,
        "escrow_funded_at": None,
        "escrow_return_due_at": None,
        "escrow_returned_at": None,
    }
    db.stamp_new(record)
    db.drivers[record["id"]] = record
    return response.object_response(serializers.driver(record), 201)


@bp.route("/driver-pay/drivers", methods=["GET"])
def list_drivers():
    middleware.authorize(*OFFICE_READ)
    rows = db.ordered(db.drivers)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("employment_status", "employment_status", constants.EMPLOYMENT_STATUSES),
            ("driver_type", "driver_type", constants.DRIVER_TYPES),
            ("escrow_status", "escrow_status", constants.ESCROW_STATUSES),
            ("pay_package_id", "pay_package_id", None),
        ],
    )
    return listing.page(rows, request.args, serializers.driver)


@bp.route("/driver-pay/drivers/<driver_id>", methods=["GET"])
def read_driver(driver_id):
    user_id, role = middleware.authorize(*ALL_READ)
    middleware.check_scope(user_id, role, driver_id)
    return response.object_response(serializers.driver(find_driver(driver_id)))


@bp.route("/driver-pay/drivers/<driver_id>/assign-pay-package", methods=["POST"])
def assign_pay_package(driver_id):
    middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["pay_package_id"])
    package_id = validators.id_value(body, "pay_package_id", required=True)

    driver = find_driver(driver_id)
    package = db.pay_packages.get(package_id)
    if package is None:
        raise ApiError("ERR_PAY_PACKAGE_NOT_FOUND")
    if driver["driver_type"] != package["driver_type"]:
        raise ApiError(
            "ERR_INVALID_FIELD_VALUE",
            "The driver_type of the driver and of the pay package must agree.",
        )
    if package["status"] != "ACTIVE":
        raise ApiError("ERR_PAY_PACKAGE_NOT_ACTIVE")
    if driver["employment_status"] not in ("ONBOARDING", "ACTIVE"):
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")

    driver["pay_package_id"] = package_id
    driver["escrow_target_cents"] = package["escrow_target_cents"]
    driver["escrow_monthly_deduction_cents"] = package["escrow_monthly_deduction_cents"]
    if package["escrow_required"] and driver["escrow_status"] == "NOT_REQUIRED":
        # The balance stays at 0 so the first settlement begins accrual.
        driver["escrow_status"] = "COLLECTING"
    db.touch(driver)
    return response.object_response(serializers.driver(driver))


@bp.route("/driver-pay/drivers/<driver_id>/status", methods=["POST"])
def set_driver_status(driver_id):
    middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["new_status"])
    new_status = validators.enum_value(body, "new_status", constants.EMPLOYMENT_STATUSES, required=True)
    terminated_at = validators.ts_value(body, "terminated_at")

    driver = find_driver(driver_id)
    current = driver["employment_status"]
    if (current, new_status) not in EMPLOYMENT_TRANSITIONS:
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")

    if new_status == "ACTIVE" and current == "ONBOARDING":
        package = db.pay_packages.get(driver["pay_package_id"]) if driver["pay_package_id"] else None
        if package is None:
            raise ApiError("ERR_DRIVER_HAS_NO_PAY_PACKAGE")
        if package["status"] != "ACTIVE":
            raise ApiError("ERR_PAY_PACKAGE_NOT_ACTIVE")

    driver["employment_status"] = new_status
    if new_status == "TERMINATED":
        driver["terminated_at"] = terminated_at if terminated_at is not None else clock.now()
    db.touch(driver)
    return response.object_response(serializers.driver(driver))


@bp.route("/driver-pay/drivers/<driver_id>/escrow/close", methods=["POST"])
def close_escrow(driver_id):
    middleware.authorize(ADMIN)
    driver = find_driver(driver_id)
    if driver["employment_status"] != "TERMINATED":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")
    if driver["escrow_status"] not in ("COLLECTING", "FUNDED"):
        raise ApiError("ERR_ESCROW_NOT_ACTIVE")
    driver["escrow_status"] = "CLOSING"
    driver["escrow_return_due_at"] = clock.plus_days(
        driver["terminated_at"], constants.ESCROW_RETURN_DAYS
    )
    db.touch(driver)
    return response.object_response(serializers.driver(driver))


@bp.route("/driver-pay/drivers/<driver_id>/escrow/deductions", methods=["POST"])
def record_deduction(driver_id):
    user_id, _role = middleware.authorize(ADMIN)
    body = validators.body_of(request)
    # The supporting document is required on a manual deduction (PRD 3.3).
    validators.require(body, ["amount_cents", "reason_code", "document_ref", "expected_driver_version"])
    magnitude = validators.int_value(body, "amount_cents", required=True, minimum=0)
    reason_code = validators.enum_value(body, "reason_code", constants.ESCROW_REASON_CODES, required=True)
    document_ref = validators.string_value(body, "document_ref", required=True)
    expected = validators.int_value(body, "expected_driver_version", required=True, minimum=0)

    driver = find_driver(driver_id)
    if expected != driver["version"]:
        raise ApiError("ERR_STALE_DRIVER_VERSION")
    if driver["employment_status"] != "ACTIVE":
        raise ApiError("ERR_DRIVER_NOT_ACTIVE")
    if driver["escrow_status"] not in ("COLLECTING", "FUNDED"):
        raise ApiError("ERR_ESCROW_NOT_ACTIVE")
    if reason_code not in constants.PERMISSIBLE_DEDUCTION_REASONS:
        raise ApiError("ERR_DEDUCTION_NOT_PERMISSIBLE")
    if magnitude > queries.escrow_balance(driver_id):
        raise ApiError("ERR_ESCROW_INSUFFICIENT_BALANCE")

    entry = escrow_service.append(
        driver,
        "PERMISSIBLE_DEDUCTION",
        -magnitude,
        reason_code,
        user_id,
        document_ref=document_ref,
    )
    bumps = 1 + escrow_service.drive_axis(driver)
    db.touch(driver, bump=bumps)
    return response.object_response(serializers.escrow_transaction(entry), 201)


@bp.route("/driver-pay/drivers/<driver_id>/escrow/return", methods=["POST"])
def return_escrow(driver_id):
    user_id, _role = middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["payment_reference"])
    validators.string_value(body, "payment_reference", required=True)

    driver = find_driver(driver_id)
    if driver["escrow_status"] != "CLOSING":
        raise ApiError("ERR_ESCROW_NOT_ACTIVE")
    due_at = driver.get("escrow_return_due_at")
    if due_at is None or clock.now() < due_at:
        raise ApiError("ERR_ESCROW_RETURN_NOT_DUE")
    if queries.corrections_of(driver_id, "PENDING"):
        raise ApiError(
            "ERR_ESCROW_RETURN_NOT_DUE",
            "A pending retroactive correction must be resolved before the principal is returned.",
        )

    balance = queries.escrow_balance(driver_id)
    escrow_service.append(
        driver,
        "RETURN_DISBURSEMENT",
        -balance,
        "TERMINATION_RETURN",
        user_id,
    )
    driver["escrow_status"] = "RETURNED"
    driver["escrow_returned_at"] = clock.now()
    db.touch(driver)
    return response.object_response(serializers.driver(driver))


@bp.route("/driver-pay/escrow-transactions", methods=["GET"])
def list_escrow_transactions():
    user_id, role = middleware.authorize(*ALL_READ)
    rows = db.ordered(db.escrow_transactions)
    rows = listing.apply_filters(
        rows,
        request.args,
        [
            ("driver_id", "driver_id", None),
            ("settlement_id", "settlement_id", None),
            ("reverses_transaction_id", "reverses_transaction_id", None),
            ("txn_type", "txn_type", constants.ESCROW_TXN_TYPES),
        ],
    )
    rows = listing.narrow_to_driver(rows, role, user_id)
    return listing.page(rows, request.args, serializers.escrow_transaction)


def find_entry(entry_id):
    entry = db.escrow_transactions.get(entry_id)
    if entry is None:
        raise ApiError("ERR_ESCROW_TRANSACTION_NOT_FOUND")
    return entry


@bp.route("/driver-pay/escrow-transactions/<entry_id>", methods=["GET"])
def read_escrow_transaction(entry_id):
    user_id, role = middleware.authorize(*ALL_READ)
    entry = find_entry(entry_id)
    middleware.check_scope(user_id, role, entry["driver_id"])
    return response.object_response(serializers.escrow_transaction(entry))


@bp.route("/driver-pay/escrow-transactions/<entry_id>/reverse", methods=["POST"])
def reverse_escrow_transaction(entry_id):
    user_id, _role = middleware.authorize(ADMIN)
    body = validators.body_of(request)
    validators.require(body, ["reason_code"])
    reason_code = validators.enum_value(body, "reason_code", constants.ESCROW_REASON_CODES, required=True)

    entry = find_entry(entry_id)
    driver = find_driver(entry["driver_id"])
    if driver["escrow_status"] not in ("COLLECTING", "FUNDED"):
        raise ApiError("ERR_ESCROW_NOT_ACTIVE")

    reversal = escrow_service.append(
        driver,
        "REVERSAL",
        -entry["amount_cents"],
        reason_code,
        user_id,
        reverses_transaction_id=entry["id"],
    )
    bumps = 1 + escrow_service.drive_axis(driver)
    db.touch(driver, bump=bumps)
    return response.object_response(serializers.escrow_transaction(reversal), 201)
