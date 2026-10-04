"""Appraisal issuance and insurance replacement coordination."""

from flask import request

from db import DB
from middleware import guard
from response import (ApiError, Err, as_enum, as_str, body, created_obj,
                      ensure_known, ok_list, ok_obj, pagination, sorted_by_created)
from services import core

READ_ROLES = ["ChainAdmin", "StoreManager", "CustomerService"]


def register(app):
    @app.route("/appraisals", methods=["POST"])
    def create_appraisal():
        guard(["StoreManager", "CustomerService"])
        data = body()
        ensure_known(data, ["repair_id", "customer_id", "appraisal_kind",
                            "insurance_schedule_ref"],
                     optional=("insurance_schedule_ref",))
        repair_id = as_str(data, "repair_id")
        customer_id = as_str(data, "customer_id")
        kind = as_enum(data, "appraisal_kind", ("INSURANCE", "REPLACEMENT"))
        repair = core.fetch("repairs", repair_id, "repair")
        core.fetch("customers", customer_id, "customer")
        appraisal = core.issue_appraisal(
            repair, customer_id, kind,
            as_str(data, "insurance_schedule_ref", required=False))
        core.touch(repair)
        return created_obj(appraisal)

    @app.route("/appraisals", methods=["GET"])
    def list_appraisals():
        guard(READ_ROLES)
        limit, offset = pagination()
        rows = DB.all("appraisals")
        for field in ("repair_id", "customer_id", "appraisal_kind", "appraisal_status"):
            value = request.args.get(field)
            if value is not None:
                rows = [r for r in rows if r[field] == value]
        rows = sorted_by_created(rows)
        return ok_list(rows, limit, offset, len(rows))

    @app.route("/appraisals/<ident>", methods=["GET"])
    def get_appraisal(ident):
        guard(READ_ROLES)
        return ok_obj(core.fetch("appraisals", ident, "appraisal"))

    @app.route("/appraisals/<ident>/advise-insurer", methods=["POST"])
    def advise_insurer(ident):
        guard(["CustomerService"])
        data = body()
        ensure_known(data, ["insurance_schedule_ref"])
        reference = as_str(data, "insurance_schedule_ref")
        appraisal = core.fetch("appraisals", ident, "appraisal")
        # Priority 32: an insurance advice needs an issued REPLACEMENT appraisal.
        if appraisal["appraisal_kind"] != "REPLACEMENT":
            raise ApiError(Err.APPRAISAL_REQUIRED,
                           "Only a REPLACEMENT appraisal may be circulated.")
        registration = _registration_for_appraisal(appraisal)
        if registration is None:
            raise ApiError(Err.APPRAISAL_REQUIRED,
                           "The repair file carries no issued replacement appraisal.")
        if appraisal["appraisal_status"] not in ("ISSUED", "CIRCULATED"):
            raise ApiError(Err.APPRAISAL_REQUIRED)
        if registration["replacement_claims_used"] >= 1:
            raise ApiError(Err.CLAIM_ALREADY_USED)

        appraisal["appraisal_status"] = "CIRCULATED"
        appraisal["insurance_schedule_ref"] = reference
        appraisal["circulated_at"] = __import__("db").iso(DB.now())
        registration["replacement_claims_used"] += 1
        core.touch(appraisal)
        core.touch(registration)
        return ok_obj(appraisal)


def _registration_for_appraisal(appraisal):
    repair = DB.get("repairs", appraisal["repair_id"])
    if repair is None:
        return None
    return DB.get("registrations", repair.get("registration_id"))