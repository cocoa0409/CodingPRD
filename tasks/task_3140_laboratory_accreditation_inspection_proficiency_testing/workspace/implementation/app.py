import os
from datetime import timedelta

from flask import Flask

import store
import services
from auth import require_auth
from errors import ApiError
from helpers import (
    ALL_READERS,
    DISCIPLINES,
    body,
    get_or_404,
    new_record,
    public,
    require_fields,
)
from util import (
    error_response,
    fmt_instant,
    fmt_ts,
    is_int,
    list_response,
    parse_ts,
    success,
)
from routes_pt import register_pt_routes
from routes_inspection import register_inspection_routes
from routes_personnel import register_personnel_routes


def create_app():
    app = Flask(__name__)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))

    @app.errorhandler(Exception)
    def handle_exception(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError("ERR_INVALID_REQUEST", 400, str(err)))

    # ------------------------------------------------------------------
    # helpers imported from helpers.py
    # ------------------------------------------------------------------

    # ==================================================================
    # Clock
    # ==================================================================

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        require_auth(["PlatformAdmin"])
        data = body()
        require_fields(data, ["current_utc"])
        new_now = parse_ts(data["current_utc"])
        with store.lock():
            store.CLOCK["now"] = new_now
            services.fire_clock_transitions()
        return success({"current_utc": fmt_instant(new_now)}, status=200)

    # ==================================================================
    # Laboratories
    # ==================================================================

    @app.route("/laboratories", methods=["POST"])
    def create_laboratory():
        require_auth(["AccreditationOfficer"])
        data = body()
        require_fields(data, ["name", "clia_number"])
        if not isinstance(data["name"], str) or not data["name"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "name must be a non-empty string")
        if not isinstance(data["clia_number"], str) or not data["clia_number"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "clia_number must be a non-empty string")
        with store.lock():
            for lab in store.STORES["laboratories"].values():
                if lab["clia_number"] == data["clia_number"]:
                    raise ApiError("ERR_DUPLICATE_CLIA", 409, "clia_number already registered")
            rec = new_record(
                {
                    "name": data["name"],
                    "clia_number": data["clia_number"],
                    "accreditation_status": "APPLIED",
                    "active_discipline_count": 0,
                }
            )
            store.STORES["laboratories"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/laboratories", methods=["GET"])
    def list_laboratories():
        require_auth(ALL_READERS)
        return list_response(list(store.STORES["laboratories"].values()))

    @app.route("/laboratories/<labId>", methods=["GET"])
    def get_laboratory(labId):
        require_auth(ALL_READERS)
        rec = get_or_404("laboratories", labId, "ERR_LABORATORY_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/laboratories/<labId>/reinstate", methods=["POST"])
    def reinstate_laboratory(labId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            lab = get_or_404("laboratories", labId, "ERR_LABORATORY_NOT_FOUND")
            if lab["accreditation_status"] != "PROBATION":
                raise ApiError("ERR_INVALID_STATE", 409, "laboratory is not in PROBATION")
            for inv in store.STORES["pt_investigations"].values():
                enr = store.STORES["enrollments"].get(inv["enrollment_id"])
                if (
                    enr
                    and enr["laboratory_id"] == lab["id"]
                    and inv["status"] in services.INVESTIGATION_NONTERMINAL
                ):
                    raise ApiError(
                        "ERR_OPEN_INVESTIGATION_EXISTS",
                        409,
                        "a non-terminal investigation exists for this laboratory",
                    )
            lab["accreditation_status"] = "ENROLLED"
            services.touch(lab)
            for enr in store.STORES["enrollments"].values():
                if enr["laboratory_id"] == lab["id"] and enr["status"] == "SUSPENDED":
                    services.set_enrollment_status(enr, "ACTIVE")
            for ins in store.STORES["inspector_profiles"].values():
                if ins["affiliated_laboratory_id"] == lab["id"] and ins["status"] == "SUSPENDED":
                    ins["status"] = "ACTIVE"
                    services.touch(ins)
            services.recompute_lab_count(lab["id"])
        return success(public(lab), status=200)

    @app.route("/laboratories/<labId>/revoke", methods=["POST"])
    def revoke_laboratory(labId):
        require_auth(["AccreditationOfficer"])
        with store.lock():
            lab = get_or_404("laboratories", labId, "ERR_LABORATORY_NOT_FOUND")
            if lab["accreditation_status"] != "PROBATION":
                raise ApiError("ERR_INVALID_STATE", 409, "laboratory is not in PROBATION")
            denied_cycles = [
                c
                for c in store.STORES["inspection_cycles"].values()
                if c["laboratory_id"] == lab["id"]
                and c.get("final_decision") == "DENIED"
                and c.get("_decided_dt") is not None
            ]
            if denied_cycles:
                latest = max(denied_cycles, key=lambda c: c["_decided_dt"])
                threshold = latest["_decided_dt"] + timedelta(days=180)
                if store.now() < threshold:
                    raise ApiError(
                        "ERR_REVOKE_TOO_EARLY",
                        409,
                        "fewer than 180 days since the most recent DENIED decision",
                    )
            else:
                raise ApiError(
                    "ERR_REVOKE_TOO_EARLY", 409, "no DENIED decision recorded for this laboratory"
                )
            lab["accreditation_status"] = "ACCREDITATION_REVOKED"
            services.touch(lab)
        return success(public(lab), status=200)

    @app.route("/laboratories/<labId>/enrollments", methods=["GET"])
    def list_laboratory_enrollments(labId):
        require_auth(ALL_READERS)
        get_or_404("laboratories", labId, "ERR_LABORATORY_NOT_FOUND")
        items = [
            public(e)
            for e in store.STORES["enrollments"].values()
            if e["laboratory_id"] == labId
        ]
        return list_response(items)

    # ==================================================================
    # Inspector profiles
    # ==================================================================

    @app.route("/inspector-profiles", methods=["POST"])
    def create_inspector_profile():
        require_auth(["AccreditationOfficer"])
        data = body()
        require_fields(data, ["full_name", "affiliated_laboratory_id", "specialties"])
        if not isinstance(data["full_name"], str) or not data["full_name"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "full_name must be a non-empty string")
        get_or_404("laboratories", data["affiliated_laboratory_id"], "ERR_LABORATORY_NOT_FOUND")
        specs = data["specialties"]
        if (
            not isinstance(specs, list)
            or not specs
            or any(s not in DISCIPLINES for s in specs)
        ):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "specialties must be a non-empty array of disciplines"
            )
        with store.lock():
            rec = new_record(
                {
                    "full_name": data["full_name"],
                    "affiliated_laboratory_id": data["affiliated_laboratory_id"],
                    "specialties": list(specs),
                    "status": "ACTIVE",
                }
            )
            store.STORES["inspector_profiles"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/inspector-profiles", methods=["GET"])
    def list_inspector_profiles():
        require_auth(ALL_READERS)
        items = list(store.STORES["inspector_profiles"].values())
        aff = request.args.get("affiliated_laboratory_id")
        if aff is not None:
            items = [i for i in items if i["affiliated_laboratory_id"] == aff]
        return list_response(items)

    @app.route("/inspector-profiles/<inspectorId>", methods=["GET"])
    def get_inspector_profile(inspectorId):
        require_auth(ALL_READERS)
        rec = get_or_404("inspector_profiles", inspectorId, "ERR_INSPECTOR_NOT_FOUND")
        return success(public(rec), status=200)

    # ==================================================================
    # Discipline enrollments
    # ==================================================================

    @app.route("/enrollments", methods=["POST"])
    def create_enrollment():
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(data, ["laboratory_id", "discipline"])
        if data["discipline"] not in DISCIPLINES:
            raise ApiError("ERR_INVALID_REQUEST", 400, "unknown discipline")
        with store.lock():
            lab = get_or_404("laboratories", data["laboratory_id"], "ERR_LABORATORY_NOT_FOUND")
            if data["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED", 403, "LaboratoryDirector may only act for their own laboratory"
                )
            for e in store.STORES["enrollments"].values():
                if e["laboratory_id"] == lab["id"] and e["discipline"] == data["discipline"]:
                    raise ApiError(
                        "ERR_DUPLICATE_ENROLLMENT", 409, "laboratory already enrolled in this discipline"
                    )
            rec = new_record(
                {
                    "laboratory_id": lab["id"],
                    "discipline": data["discipline"],
                    "status": "WAITING",
                    "standing_per_event": "SATISFACTORY",
                    "standing_rolling": "SATISFACTORY",
                    "unsuccessful_event_streak": 0,
                }
            )
            store.STORES["enrollments"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/enrollments", methods=["GET"])
    def list_enrollments():
        require_auth(ALL_READERS)
        items = list(store.STORES["enrollments"].values())
        lab = request.args.get("laboratory_id")
        if lab is not None:
            items = [e for e in items if e["laboratory_id"] == lab]
        return list_response(items)

    @app.route("/enrollments/<enrollmentId>", methods=["GET"])
    def get_enrollment(enrollmentId):
        require_auth(ALL_READERS)
        rec = get_or_404("enrollments", enrollmentId, "ERR_ENROLLMENT_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/enrollments/<enrollmentId>/sections", methods=["GET"])
    def list_enrollment_sections(enrollmentId):
        require_auth(ALL_READERS)
        get_or_404("enrollments", enrollmentId, "ERR_ENROLLMENT_NOT_FOUND")
        items = [
            public(s)
            for s in store.STORES["sections"].values()
            if s["enrollment_id"] == enrollmentId
        ]
        return list_response(items)

    # ==================================================================
    # Testing sections + checklist assignment
    # ==================================================================

    @app.route("/sections", methods=["POST"])
    def create_section():
        user_id, role = require_auth(["LaboratoryDirector"])
        data = body()
        require_fields(data, ["enrollment_id", "section_name"])
        if not isinstance(data["section_name"], str) or not data["section_name"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "section_name must be a non-empty string")
        critical = data.get("critical_testing", False)
        if not isinstance(critical, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "critical_testing must be boolean")
        with store.lock():
            enr = get_or_404("enrollments", data["enrollment_id"], "ERR_ENROLLMENT_NOT_FOUND")
            if enr["laboratory_id"] != user_id:
                raise ApiError(
                    "ERR_UNAUTHORIZED", 403, "LaboratoryDirector may only act for their own laboratory"
                )
            rec = new_record(
                {
                    "enrollment_id": enr["id"],
                    "section_name": data["section_name"],
                    "critical_testing": critical,
                    "checklist_code": None,
                    "checklist_version": None,
                    "checklist_status": "UNASSIGNED",
                }
            )
            store.STORES["sections"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/sections", methods=["GET"])
    def list_sections():
        require_auth(ALL_READERS)
        items = list(store.STORES["sections"].values())
        enr = request.args.get("enrollment_id")
        if enr is not None:
            items = [s for s in items if s["enrollment_id"] == enr]
        return list_response(items)

    @app.route("/sections/<sectionId>", methods=["GET"])
    def get_section(sectionId):
        require_auth(ALL_READERS)
        rec = get_or_404("sections", sectionId, "ERR_SECTION_NOT_FOUND")
        return success(public(rec), status=200)

    @app.route("/sections/<sectionId>/assign-checklist", methods=["POST"])
    def assign_checklist(sectionId):
        require_auth(["AccreditationOfficer"])
        data = body()
        require_fields(data, ["checklist_code", "checklist_version"])
        if not isinstance(data["checklist_code"], str) or not data["checklist_code"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "checklist_code must be a non-empty string")
        if not isinstance(data["checklist_version"], str) or not data["checklist_version"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "checklist_version must be a non-empty string")
        with store.lock():
            sec = get_or_404("sections", sectionId, "ERR_SECTION_NOT_FOUND")
            if sec["checklist_status"] == "ASSIGNED":
                raise ApiError("ERR_CHECKLIST_ALREADY_ASSIGNED", 409, "checklist already assigned")
            enr = store.STORES["enrollments"].get(sec["enrollment_id"])
            if enr is None:
                raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "enrollment not found")
            if sec["checklist_status"] == "UNASSIGNED":
                if enr["status"] not in ("ACTIVE", "WAITING"):
                    raise ApiError(
                        "ERR_ENROLLMENT_INACTIVE", 409, "parent enrollment is not ACTIVE or WAITING"
                    )
            else:  # CHECKLIST_INVALIDATED
                if enr["status"] == "CEASED":
                    raise ApiError("ERR_ENROLLMENT_INACTIVE", 409, "parent enrollment is CEASED")
            # edition must exist and not be retired
            edition = None
            for ed in store.STORES["checklist_editions"].values():
                if (
                    ed["checklist_code"] == data["checklist_code"]
                    and ed["checklist_version"] == data["checklist_version"]
                ):
                    edition = ed
                    break
            if edition is None:
                raise ApiError("ERR_CHECKLIST_UNKNOWN", 409, "checklist edition not registered")
            for ed in store.STORES["checklist_editions"].values():
                if (
                    ed["checklist_code"] == data["checklist_code"]
                    and ed.get("retires_checklist_version") == data["checklist_version"]
                ):
                    raise ApiError("ERR_CHECKLIST_UNKNOWN", 409, "checklist edition is retired")
            was_waiting = enr["status"] == "WAITING"
            if was_waiting:
                expected = data.get("expected_enrollment_version")
                if expected is None or not is_int(expected) or expected != enr["version"]:
                    raise ApiError(
                        "ERR_STALE_VERSION",
                        412,
                        "expected_enrollment_version does not match the enrollment's current version",
                    )
            first_assignment = False
            if was_waiting and sec["checklist_status"] == "UNASSIGNED":
                remaining = sum(
                    1
                    for s in store.STORES["sections"].values()
                    if s["enrollment_id"] == enr["id"]
                    and s["id"] != sec["id"]
                    and s["checklist_status"] == "UNASSIGNED"
                )
                if remaining == 0:
                    first_assignment = True
            sec["checklist_code"] = data["checklist_code"]
            sec["checklist_version"] = data["checklist_version"]
            sec["checklist_status"] = "ASSIGNED"
            services.touch(sec)
            services.touch(enr)  # parent enrollment version += 1
            if first_assignment:
                enr["status"] = "ACTIVE"
                services.recompute_lab_count(enr["laboratory_id"])
                lab = store.STORES["laboratories"].get(enr["laboratory_id"])
                if lab and lab["accreditation_status"] == "APPLIED":
                    lab["accreditation_status"] = "ENROLLED"
                    services.touch(lab)
            services.refresh_postures_for_laboratory(enr["laboratory_id"])
        return success(public(sec), status=200)

    # ==================================================================
    # Checklist editions
    # ==================================================================

    @app.route("/checklist-editions", methods=["POST"])
    def create_checklist_edition():
        require_auth(["AccreditationOfficer"])
        data = body()
        require_fields(data, ["checklist_code", "checklist_version"])
        if not isinstance(data["checklist_code"], str) or not data["checklist_code"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "checklist_code must be a non-empty string")
        if not isinstance(data["checklist_version"], str) or not data["checklist_version"].strip():
            raise ApiError("ERR_INVALID_REQUEST", 400, "checklist_version must be a non-empty string")
        retires = data.get("retires_checklist_version")
        if retires is not None and not isinstance(retires, str):
            raise ApiError("ERR_INVALID_REQUEST", 400, "retires_checklist_version must be a string")
        with store.lock():
            for ed in store.STORES["checklist_editions"].values():
                if (
                    ed["checklist_code"] == data["checklist_code"]
                    and ed["checklist_version"] == data["checklist_version"]
                ):
                    raise ApiError(
                        "ERR_INVALID_REQUEST", 400, "checklist edition already registered"
                    )
            retired_count = 0
            if retires is not None:
                for sec in store.STORES["sections"].values():
                    if (
                        sec["checklist_code"] == data["checklist_code"]
                        and sec["checklist_version"] == retires
                        and sec["checklist_status"] == "ASSIGNED"
                    ):
                        sec["checklist_status"] = "CHECKLIST_INVALIDATED"
                        services.touch(sec)
                        retired_count += 1
            rec = new_record(
                {
                    "checklist_code": data["checklist_code"],
                    "checklist_version": data["checklist_version"],
                    "retires_checklist_version": retires,
                    "retired_count": retired_count,
                }
            )
            store.STORES["checklist_editions"][rec["id"]] = rec
        return success(public(rec), status=201)

    @app.route("/checklist-editions", methods=["GET"])
    def list_checklist_editions():
        require_auth(ALL_READERS)
        return list_response(list(store.STORES["checklist_editions"].values()))

    register_pt_routes(app)
    register_inspection_routes(app)
    register_personnel_routes(app)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
