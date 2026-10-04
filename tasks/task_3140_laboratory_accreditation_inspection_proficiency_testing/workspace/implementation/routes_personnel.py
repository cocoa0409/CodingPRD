"""Personnel records, competency assessments, and method validations."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from flask import request

import services
import store
from auth import require_auth
from errors import ApiError
from helpers import (
    ALL_READERS,
    body,
    get_or_404,
    new_record,
    public,
    require_fields,
)
from util import fmt_instant, fmt_ts, is_num, list_response, parse_ts, success

PERSONNEL_ROLES = {"DIRECTOR", "TECHNICAL_SUPERVISOR", "TESTING_PERSONNEL"}


def register_personnel_routes(app):

    # ---------------- personnel ----------------

    @app.route("/personnel-records", methods=["POST"])
    def create_personnel():
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(data, ["enrollment_id", "person_name", "personnel_role"])
        if not isinstance(data["person_name"], str) or not data["person_name"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "person_name must be a non-empty string")
        if data["personnel_role"] not in PERSONNEL_ROLES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "unknown personnel_role")
        with store.lock():
            enr = get_or_404("enrollments", data["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
            if enr["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            rec = new_record(
                {
                    "enrollment_id": enr["id"],
                    "person_name": data["person_name"],
                    "personnel_role": data["personnel_role"],
                    "qualification_status": "PROVISIONAL",
                    "consecutive_failed_assessments": 0,
                }
            )
            store.STORES["personnel_records"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/personnel-records", methods=["GET"])
    def list_personnel():
        require_auth(ALL_READERS)
        items = list(store.STORES["personnel_records"].values())
        enr = request.args.get("enrollment_id")
        if enr is not None:
            items = [p for p in items if p["enrollment_id"] == enr]
        return list_response(items)

    @app.route("/personnel-records/<personnelId>", methods=["GET"])
    def get_personnel(personnelId):
        require_auth(ALL_READERS)
        rec = get_or_404("personnel_records", personnelId, "ERR_PERSONNEL_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/personnel-records/<personnelId>/verify-qualification", methods=["POST"])
    def verify_qualification(personnelId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            rec = get_or_404("personnel_records", personnelId, "ERR_PERSONNEL_NOT_FOUND")
            if rec["qualification_status"] != "PROVISIONAL":
                raise ApiError("ERR_INVALID_STATE", 409, "personnel is not PROVISIONAL")
            rec["qualification_status"] = "QUALIFIED"
            services.touch(rec)
            enr = store.STORES["enrollments"].get(rec["enrollment_id"])
            if enr:
                services.refresh_postures_for_laboratory(enr["laboratory_id"])
        return success(public(rec), status=200)

    # ---------------- competency assessments ----------------

    @app.route("/competency-assessments", methods=["POST"])
    def create_assessment():
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(data, ["personnel_id", "assessed_at", "element_scores"])
        with store.lock():
            person = get_or_404("personnel_records", data["personnel_id"], "ERR_PERSONNEL_NOT_FOUND")
            assessed = parse_ts(data["assessed_at"])
            scores = data["element_scores"]
            if not isinstance(scores, list) or len(scores) != 6:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "element_scores must contain exactly 6 values"
                )
            for s in scores:
                if not is_num(s) or s < 0 or s > 100:
                    raise ApiError(
                        "ERR_INVALID_REQUEST",
                        400,
                        "each element score must be a number in 0..100",
                    )
            enr = get_or_404("enrollments", person["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
            if enr["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            if enr["status"] == "CEASED":
                raise ApiError("ERR_ENROLLMENT_INACTIVE", 409, "enrollment is CEASED")
            priors = [
                a
                for a in store.STORES["competency_assessments"].values()
                if a["personnel_id"] == person["id"]
            ]
            if priors:
                latest = max(priors, key=lambda a: a["_assessed_dt"])
                if assessed <= latest["_assessed_dt"]:
                    raise ApiError(
                        "ERR_ASSESSMENT_OVERLAP",
                        409,
                        "assessed_at must be strictly after the latest prior assessment",
                    )
            # composite: round-then-sum
            weights = [
                (Decimal(str(s)) / Decimal("600")).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                for s in scores
            ]
            composite = float(
                (Decimal(100) * sum(weights)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )
            passed = composite >= 85.0 and min(scores) >= 70
            valid_until = assessed + timedelta(days=365)
            rec = new_record(
                {
                    "personnel_id": person["id"],
                    "assessed_at": fmt_instant(assessed),
                    "element_scores": list(scores),
                    "composite_score": composite,
                    "passed": passed,
                    "valid_until": fmt_instant(valid_until),
                }
            )
            rec["_assessed_dt"] = assessed
            rec["_valid_until_dt"] = valid_until
            store.STORES["competency_assessments"][rec["id"]] = rec
            # drive personnel status
            changed = False
            if passed:
                if person["qualification_status"] != "QUALIFIED":
                    person["qualification_status"] = "QUALIFIED"
                    changed = True
                if person["consecutive_failed_assessments"] != 0:
                    person["consecutive_failed_assessments"] = 0
                    changed = True
            else:
                person["consecutive_failed_assessments"] += 1
                changed = True
                if person["consecutive_failed_assessments"] >= 2:
                    if person["qualification_status"] != "DISQUALIFIED":
                        person["qualification_status"] = "DISQUALIFIED"
                else:
                    if person["qualification_status"] in ("QUALIFIED",):
                        person["qualification_status"] = "COMPETENCY_REVIEW"
            if changed:
                services.touch(person)
                services.refresh_postures_for_laboratory(enr["laboratory_id"])
        return success(public(rec), status=201)

    @app.route("/competency-assessments", methods=["GET"])
    def list_assessments():
        require_auth(ALL_READERS)
        items = list(store.STORES["competency_assessments"].values())
        pid = request.args.get("personnel_id")
        if pid is not None:
            items = [a for a in items if a["personnel_id"] == pid]
        return list_response(items)

    @app.route("/competency-assessments/<assessmentId>", methods=["GET"])
    def get_assessment(assessmentId):
        require_auth(ALL_READERS)
        rec = get_or_404(
            "competency_assessments", assessmentId, "ERR_NOT_FOUND"
        )
        return success(public(rec), status=200)

    # ---------------- method validations ----------------

    @app.route("/method-validations", methods=["POST"])
    def create_method_validation():
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(
            data,
            [
                "enrollment_id",
                "method_name",
                "instrument_name",
                "correlation_r_squared",
                "precision_cv_pct",
            ],
        )
        if not isinstance(data["method_name"], str) or not data["method_name"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "method_name must be a non-empty string")
        if not isinstance(data["instrument_name"], str) or not data["instrument_name"].strip():
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "instrument_name must be a non-empty string"
            )
        if not is_num(data["correlation_r_squared"]):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "correlation_r_squared must be a number"
            )
        if not is_num(data["precision_cv_pct"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "precision_cv_pct must be a number")
        with store.lock():
            enr = get_or_404("enrollments", data["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
            if enr["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            rec = new_record(
                {
                    "enrollment_id": enr["id"],
                    "method_name": data["method_name"],
                    "instrument_name": data["instrument_name"],
                    "correlation_r_squared": data["correlation_r_squared"],
                    "precision_cv_pct": data["precision_cv_pct"],
                    "status": "DRAFT",
                }
            )
            store.STORES["method_validations"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/method-validations", methods=["GET"])
    def list_method_validations():
        require_auth(ALL_READERS)
        items = list(store.STORES["method_validations"].values())
        enr = request.args.get("enrollment_id")
        if enr is not None:
            items = [m for m in items if m["enrollment_id"] == enr]
        return list_response(items)

    @app.route("/method-validations/<mvId>", methods=["GET"])
    def get_method_validation(mvId):
        require_auth(ALL_READERS)
        rec = get_or_404("method_validations", mvId, "ERR_METHOD_VALIDATION_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/method-validations/<mvId>/submit", methods=["POST"])
    def submit_method_validation(mvId):
        user_id, role = require_auth(["LaboratoryDirector"])
        with store.lock():
            rec = get_or_404("method_validations", mvId, "ERR_METHOD_VALIDATION_NOT_FOUND")
            if rec["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", 409, "method validation is not DRAFT")
            enr = store.STORES["enrollments"].get(rec["enrollment_id"])
            if enr and enr["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "LaboratoryDirector may only act for their own laboratory",
                )
            rec["status"] = "SUBMITTED"
            services.touch(rec)
        return success(public(rec), status=200)

    @app.route("/method-validations/<mvId>/approve", methods=["POST"])
    def approve_method_validation(mvId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            rec = get_or_404("method_validations", mvId, "ERR_METHOD_VALIDATION_NOT_FOUND")
            if rec["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "method validation is not SUBMITTED")
            enr = store.STORES["enrollments"].get(rec["enrollment_id"])
            if not enr:
                raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "enrollment not found")
            if enr["status"] != "ACTIVE":
                raise ApiError("ERR_ENROLLMENT_INACTIVE", 409, "enrollment is not ACTIVE")
            if rec["correlation_r_squared"] < 0.95 or rec["precision_cv_pct"] > 10.0:
                raise ApiError(
                    "ERR_VALIDATION_STUDY_INADEQUATE",
                    409,
                    "validation study thresholds not met",
                )
            rec["status"] = "APPROVED"
            services.touch(rec)
            services.refresh_postures_for_laboratory(enr["laboratory_id"])
        return success(public(rec), status=200)

    @app.route("/method-validations/<mvId>/reject", methods=["POST"])
    def reject_method_validation(mvId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            rec = get_or_404("method_validations", mvId, "ERR_METHOD_VALIDATION_NOT_FOUND")
            if rec["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE", 409, "method validation is not SUBMITTED")
            rec["status"] = "REJECTED"
            services.touch(rec)
        return success(public(rec), status=200)
