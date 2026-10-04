"""Registration applications: drafting, submit/resubmit, withdraw, decisions."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from services.cascade import approval_cascade, cleanup_proposed_rows
from validate import (
    as_enum,
    as_int,
    as_list,
    as_str,
    paginate,
    parse_body,
    reject_unknown,
    validate_use_site,
)

bp = Blueprint("applications", __name__)

OPEN_APPLICATION_STATUSES = ("DRAFT", "IN_REVIEW", "DATA_DEFICIENCY")


def get_application_or_404(application_id):
    app = store["applications"].get(application_id)
    if app is None:
        err("ERR_APPLICATION_NOT_FOUND", "Application %s does not exist." % application_id)
    return app


def _required_studies_present(application, accepted_only):
    required = constants.REQUIRED_STUDY_TYPES[application["use_pattern"]]
    studies = [
        s for s in store["studies"].values() if s.get("application_id") == application["id"]
    ]
    for study_type in required:
        if accepted_only:
            if not any(
                s["study_type"] == study_type and s["status"] == "ACCEPTED" for s in studies
            ):
                return False
        else:
            if not any(s["study_type"] == study_type for s in studies):
                return False
    return True


@bp.post("/registration-applications")
def create_application():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(
        data, ["product_id", "use_pattern", "requested_classification", "proposed_use_sites"]
    )
    product_id = as_str(data, "product_id", required=True)
    use_pattern = as_enum(data, "use_pattern", constants.USE_PATTERNS, required=True)
    requested_classification = as_enum(
        data, "requested_classification", constants.CLASSIFICATIONS, required=True
    )
    proposed_use_sites = as_list(data, "proposed_use_sites", required=True)
    sites = [validate_use_site(s) for s in proposed_use_sites]

    # Stage 4: existence. Stage 5: ownership.
    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The product belongs to another registrant.")

    # Stage 8: the absolute rate cap applies at application creation.
    for site in sites:
        if site["max_application_rate_lbs_acre"] > float(constants.ABSOLUTE_RATE_CAP_LBS_ACRE):
            err(
                "ERR_RATE_EXCEEDS_SAFETY_CAP",
                "max_application_rate_lbs_acre exceeds the 8.0 lbs/acre absolute cap.",
            )

    row = new_row()
    row.update(
        {
            "product_id": product_id,
            "registrant_ref": caller["user_id"],
            "use_pattern": use_pattern,
            "requested_classification": requested_classification,
            "status": "DRAFT",
            "submitted_at": None,
            "review_due_at": None,
            "deficiency_count": 0,
            "payment_cents": None,
            "decided_at": None,
            "final_classification": None,
        }
    )
    store["applications"][row["id"]] = row

    for site in sites:
        site_row = new_row()
        site_row.update(site)
        site_row.update(
            {
                "product_id": product_id,
                "origin": "INITIAL_APPLICATION",
                "status": "PROPOSED",
                "pre_removal_status": None,
                "removed_at": None,
            }
        )
        store["use_sites"][site_row["id"]] = site_row

    return ok(row, status=201)


@bp.get("/registration-applications")
def list_applications():
    require_auth()
    rows = list(store["applications"].values())
    for key in ("product_id", "registrant_ref", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/registration-applications/<application_id>")
def get_application(application_id):
    require_auth()
    return ok(get_application_or_404(application_id))


@bp.post("/registration-applications/<application_id>/submit")
def submit_application(application_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["payment_cents"])
    if "payment_cents" in data and data["payment_cents"] is not None:
        payment = as_int(data, "payment_cents")
    else:
        payment = None

    application = get_application_or_404(application_id)
    product = store["products"][application["product_id"]]
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The application belongs to another registrant.")

    # Stage 7: state gates.
    if application["status"] == "DRAFT":
        if product["status"] != "UNREGISTERED":
            err("ERR_PRODUCT_NOT_UNREGISTERED", "First submit requires the product UNREGISTERED.")
        # Stage 8: required studies of any status must be present.
        if not _required_studies_present(application, accepted_only=False):
            err(
                "ERR_MISSING_REQUIRED_STUDIES",
                "Required study types for the use pattern are not present.",
            )
        # Stage 9: one open application per product.
        for other in store["applications"].values():
            if (
                other["id"] != application["id"]
                and other["product_id"] == application["product_id"]
                and other["status"] in OPEN_APPLICATION_STATUSES
            ):
                err(
                    "ERR_DUPLICATE_OPEN_APPLICATION",
                    "Another application of this product is already open.",
                )
        # Stage 12: exact filing fee.
        fee = constants.APPLICATION_FEE_CENTS[application["use_pattern"]]
        if payment != fee:
            err(
                "ERR_INCORRECT_FEE_PAYMENT",
                "payment_cents must equal %d for %s." % (fee, application["use_pattern"]),
            )
        now = clock.now()
        application["submitted_at"] = now
        application["review_due_at"] = now + timedelta(
            days=constants.APPLICATION_REVIEW_DAYS[application["use_pattern"]]
        )
        application["payment_cents"] = payment
        application["status"] = "IN_REVIEW"
        touch(application)
    elif application["status"] == "DATA_DEFICIENCY":
        # Resubmission: payment_cents MUST be omitted; no second fee.
        if payment is not None:
            err("ERR_INVALID_REQUEST", "payment_cents must be omitted on resubmission.")
        if not _required_studies_present(application, accepted_only=False):
            err(
                "ERR_MISSING_REQUIRED_STUDIES",
                "Required study types for the use pattern are not present.",
            )
        # submitted_at refreshes; review_due_at is NOT recomputed.
        application["submitted_at"] = clock.now()
        application["status"] = "IN_REVIEW"
        touch(application)
    else:
        err(
            "ERR_APPLICATION_NOT_SUBMITTABLE",
            "Only a DRAFT or DATA_DEFICIENCY application can be submitted.",
        )
    return ok(application)


@bp.post("/registration-applications/<application_id>/withdraw")
def withdraw_application(application_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["reason"])
    if "reason" in data and data["reason"] is not None:
        as_str(data, "reason")

    application = get_application_or_404(application_id)
    product = store["products"][application["product_id"]]
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The application belongs to another registrant.")

    if application["status"] not in OPEN_APPLICATION_STATUSES:
        err("ERR_APPLICATION_ALREADY_DECIDED", "The application is already terminal.")
    application["status"] = "WITHDRAWN"
    touch(application)
    cleanup_proposed_rows(application["product_id"], clock.now())
    return ok(application)


@bp.post("/registration-applications/<application_id>/review-decisions")
def decide_application(application_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRATION_REVIEWER])
    data = parse_body()
    reject_unknown(data, ["decision", "deficiency_notes", "final_classification"])
    decision = as_enum(data, "decision", ["APPROVE", "DENY", "DEFICIENCY"], required=True)
    if "deficiency_notes" in data and data["deficiency_notes"] is not None:
        as_str(data, "deficiency_notes")
    final_classification = as_enum(
        data, "final_classification", constants.CLASSIFICATIONS, required=False
    )
    # Conditional requiredness (stage 3): final_classification on APPROVE.
    if decision == "APPROVE" and final_classification is None:
        err("ERR_INVALID_REQUEST", "final_classification is required on an APPROVE decision.")

    application = get_application_or_404(application_id)
    product = store["products"][application["product_id"]]

    if application["status"] != "IN_REVIEW":
        err("ERR_APPLICATION_NOT_IN_REVIEW", "The application is not IN_REVIEW.")

    now = clock.now()
    if decision == "DEFICIENCY":
        application["status"] = "DATA_DEFICIENCY"
        application["deficiency_count"] += 1
        if data.get("deficiency_notes") is not None:
            application["deficiency_notes"] = data["deficiency_notes"]
        touch(application)
        return ok(application)

    if decision == "DENY":
        application["status"] = "DENIED"
        application["decided_at"] = now
        touch(application)
        cleanup_proposed_rows(application["product_id"], now)
        return ok(application)

    # APPROVE gate chain (PRD 3.4), in validation-pipeline order.
    if not _required_studies_present(application, accepted_only=True):
        err(
            "ERR_MISSING_REQUIRED_STUDIES",
            "Every required study type needs at least one ACCEPTED study.",
        )
    assessments = [
        a for a in store["risk_assessments"].values() if a["application_id"] == application["id"]
    ]
    if not assessments:
        err("ERR_NO_RISK_ASSESSMENT", "No risk assessment exists for the application.")
    latest = max(assessments, key=lambda a: a["assessment_seq"])
    if latest["level_of_concern_exceeded"]:
        err("ERR_LOC_EXCEEDED", "The latest risk assessment exceeds the level of concern.")
    if application["use_pattern"] in ("FOOD_USE", "MIXED_USE"):
        has_proposed_tolerance = any(
            t["product_id"] == application["product_id"] and t["status"] == "PROPOSED"
            for t in store["tolerances"].values()
        )
        if not has_proposed_tolerance:
            err(
                "ERR_NO_PROPOSED_TOLERANCE",
                "A food-use approval requires a PROPOSED tolerance on the product.",
            )
    if caller["user_id"] == latest["assessor_ref"]:
        err(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "The assessor of the latest risk assessment cannot approve the application.",
        )

    application["status"] = "APPROVED"
    application["decided_at"] = now
    application["final_classification"] = final_classification
    touch(application)
    approval_cascade(application, product, now)
    return ok(application)


@bp.get("/registration-applications/<application_id>/study-submissions")
def list_application_studies(application_id):
    require_auth()
    get_application_or_404(application_id)
    rows = [
        s for s in store["studies"].values() if s.get("application_id") == application_id
    ]
    for key in ("study_type", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/registration-applications/<application_id>/risk-assessments")
def list_application_risk_assessments(application_id):
    require_auth()
    get_application_or_404(application_id)
    rows = [
        a for a in store["risk_assessments"].values() if a["application_id"] == application_id
    ]
    # assessment_seq is 1-based in creation order, so created_at-ascending
    # pagination order coincides with assessment_seq order.
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)
