"""ModalityUnit and EquipmentItem endpoints (PRD §3.1, §4)."""

import flask

import db
import response
from errors import fail
from middleware import require
from services import common


def _settle_testing_window(unit):
    """Re-derive the unit's testing threshold on a re-read.

    Once the current logical clock passes `testing_deadline_at`, an acquisition
    still sitting in `ACQUIRED` is past its window and must be retired on its
    own — a re-read is what makes that observable. The deadline itself is left
    alone, since the workflow only ever moves it.
    """
    deadline = unit.get("testing_deadline_at")
    if deadline is None:
        return
    if db.parse_ts(deadline) >= db.now():
        return
    stale = [t for t in common.unit_phantom_tests(unit["id"]) if t["result_status"] == "ACQUIRED"]
    if not stale:
        return
    stamp = db.now()
    for test in stale:
        common.set_field(test, "result_status", "VOIDED", stamp)
    common.recompute_phantom_counts(unit)
    common.touch(unit, stamp)


def register_routes(app):

    # ---------------------------------------------------------------- units

    @app.route("/accreditation/modality-units", methods=["POST"])
    @require(["FacilityAdmin"])
    def enroll_unit(principal):
        payload = common.body()
        common.require_fields(
            payload, ["facility_id", "modality_code", "unit_label", "expected_facility_version"]
        )
        common.check_required_enum(payload, "modality_code", "modality_code")
        facility = common.get_facility(payload["facility_id"])
        if facility["facility_status"] in ("SUSPENDED", "DEFERRED"):
            fail("ERR_UNIT_DEFERRED", "the facility is not on the enrollment path")

        label = payload["unit_label"]
        if any(u["unit_label"] == label for u in common.facility_units(facility["id"])):
            fail("ERR_UNIT_LABEL_DUPLICATE", "unit_label already exists for this facility")

        common.enforce_version(facility, payload, "expected_facility_version")

        unit = common.make_record(
            id=db.new_id(),
            facility_id=facility["id"],
            modality_code=payload["modality_code"],
            unit_label=label,
            unit_status="ENROLLED",
            clinical_deadline_at=None,
            testing_deadline_at=None,
            phantom_attempt_count=0,
            phantom_failure_count=0,
            deficiency_open_count=0,
            last_phantom_score=None,
            last_survey_at=None,
            _benchmark_reporting_started=False,
        )
        db.MODALITY_UNITS[unit["id"]] = unit
        return response.ok(common.serialize(unit), 201)

    @app.route("/accreditation/modality-units", methods=["GET"])
    @require(["Any"])
    def list_units(principal):
        rows = list(db.MODALITY_UNITS.values())
        for field in ("facility_id", "modality_code", "unit_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/modality-units/<unit_id>", methods=["GET"])
    @require(["Any"])
    def read_unit(principal, unit_id):
        unit = common.get_unit(unit_id)
        _settle_testing_window(unit)
        common.recompute_deficiency_open_count(unit)
        common.recompute_phantom_counts(unit)
        return response.ok(common.serialize(unit))

    @app.route("/accreditation/modality-units/<unit_id>/withdraw", methods=["POST"])
    @require(["FacilityAdmin"])
    def withdraw_unit(principal, unit_id):
        unit = common.get_unit(unit_id)
        payload = common.body()

        if unit["unit_status"] == "WITHDRAWN":
            fail("ERR_ALREADY_TERMINAL", "the modality unit is already withdrawn")
        if unit["unit_status"] != "ENROLLED":
            fail("ERR_INVALID_STATE", "the modality unit is not ENROLLED")

        if any(s["review_status"] == "PENDING_REVIEW" for s in common.unit_submissions(unit["id"])):
            fail("ERR_INVALID_STATE", "the unit holds a submission pending review")
        if any(t["result_status"] == "ACQUIRED" for t in common.unit_phantom_tests(unit["id"])):
            fail("ERR_INVALID_STATE", "the unit holds an unscored phantom acquisition")
        facility = common.facility_of_unit(unit)
        if facility is not None:
            for plan in common.facility_plans(facility["id"]):
                if plan["plan_status"] not in ("OPEN", "SUBMITTED"):
                    continue
                source = db.SUBMISSIONS.get(plan["source_submission_id"])
                if source is not None and source["unit_id"] == unit["id"]:
                    fail("ERR_INVALID_STATE", "an unresolved corrective action plan depends on this unit")

        common.enforce_version(unit, payload, "expected_unit_version")
        common.set_field(unit, "unit_status", "WITHDRAWN")
        for item in common.unit_equipment(unit["id"]):
            common.set_field(item, "equipment_status", "RETIRED")
        if facility is not None:
            common.recompute_enrolled_unit_count(facility)
        return response.ok(common.serialize(unit))

    # ------------------------------------------------------------ equipment

    @app.route("/accreditation/equipment", methods=["POST"])
    @require(["FacilityAdmin"])
    def commission_equipment(principal):
        payload = common.body()
        common.require_fields(
            payload,
            ["unit_id", "manufacturer", "model_number", "serial_number", "modality_code", "installed_on"],
        )
        common.check_required_enum(payload, "modality_code", "modality_code")
        unit = common.get_unit(payload["unit_id"])
        if unit["unit_status"] != "ENROLLED":
            fail("ERR_UNIT_DEFERRED", "the owning modality unit is not ENROLLED")

        facility = common.facility_of_unit(unit)
        serial = payload["serial_number"]
        if facility is not None:
            if any(e["serial_number"] == serial for e in common.facility_equipment(facility["id"])):
                fail("ERR_SERIAL_DUPLICATE", "serial_number already exists for this facility")

        # equipment_status and performance_verdict are accepted but ignored.
        item = common.make_record(
            id=db.new_id(),
            unit_id=unit["id"],
            manufacturer=payload["manufacturer"],
            model_number=payload["model_number"],
            serial_number=serial,
            modality_code=payload["modality_code"],
            installed_on=db.parse_ts(payload["installed_on"]),
            equipment_status="ACTIVE",
            performance_verdict="PENDING",
        )
        db.EQUIPMENT[item["id"]] = item
        common.touch(unit)
        return response.ok(common.serialize(item), 201)

    @app.route("/accreditation/equipment", methods=["GET"])
    @require(["Any"])
    def list_equipment(principal):
        rows = list(db.EQUIPMENT.values())
        for field in ("unit_id", "serial_number", "equipment_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/equipment/<equipment_id>", methods=["GET"])
    @require(["Any"])
    def read_equipment(principal, equipment_id):
        return response.ok(common.serialize(common.get_equipment(equipment_id)))

    @app.route("/accreditation/equipment/<equipment_id>/take-out-of-service", methods=["POST"])
    @require(["FacilityAdmin"])
    def take_out_of_service(principal, equipment_id):
        item = common.get_equipment(equipment_id)
        unit = common.get_unit(item["unit_id"])
        payload = common.body()
        common.enforce_version(unit, payload, "expected_unit_version")

        if item["equipment_status"] == "RETIRED":
            fail("ERR_ALREADY_TERMINAL", "the equipment item is retired")
        if item["equipment_status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "the equipment item is not ACTIVE")
        if any(t["result_status"] == "ACQUIRED" for t in common.unit_phantom_tests(unit["id"])):
            fail("ERR_INVALID_STATE", "the unit holds an unscored phantom acquisition")

        common.set_field(item, "equipment_status", "OUT_OF_SERVICE")
        # clinical_deadline_at and testing_deadline_at are deliberately untouched.
        common.touch(unit)
        return response.ok(common.serialize(item))

    @app.route("/accreditation/equipment/<equipment_id>/return-to-service", methods=["POST"])
    @require(["FacilityAdmin"])
    def return_to_service(principal, equipment_id):
        item = common.get_equipment(equipment_id)
        unit = common.get_unit(item["unit_id"])
        payload = common.body()
        common.enforce_version(unit, payload, "expected_unit_version")

        if item["equipment_status"] == "RETIRED":
            fail("ERR_ALREADY_TERMINAL", "the equipment item is retired")
        if item["equipment_status"] != "OUT_OF_SERVICE":
            fail("ERR_INVALID_STATE", "the equipment item is not OUT_OF_SERVICE")

        accepted = any(
            s["unit_id"] == unit["id"] and s["survey_status"] == "ACCEPTED"
            for s in db.SURVEYS.values()
        )
        if not accepted:
            fail("ERR_INVALID_STATE", "no accepted physicist survey covers this unit")

        common.set_field(item, "equipment_status", "ACTIVE")
        item["performance_verdict"] = "PENDING"
        common.touch(unit)
        return response.ok(common.serialize(item))

    @app.route("/accreditation/equipment/<equipment_id>/retire", methods=["POST"])
    @require(["FacilityAdmin"])
    def retire_equipment(principal, equipment_id):
        item = common.get_equipment(equipment_id)
        unit = common.get_unit(item["unit_id"])
        payload = common.body()
        common.enforce_version(unit, payload, "expected_unit_version")

        if item["equipment_status"] == "RETIRED":
            fail("ERR_ALREADY_TERMINAL", "the equipment item is retired")
        if item["equipment_status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "the equipment item is not ACTIVE")

        others = [
            e for e in common.unit_equipment(unit["id"])
            if e["id"] != item["id"] and e["equipment_status"] == "ACTIVE"
        ]
        if not others:
            fail("ERR_INVALID_STATE", "the unit would be left with no serviceable equipment")

        facility = common.facility_of_unit(unit)
        if facility is not None:
            common.recompute_all_deadline_statuses(facility["id"])
            if common.has_pending_plan(facility["id"]):
                fail("ERR_DEFICIENCY_PENDING", "the facility holds an open corrective action plan")

        # performance_verdict is frozen at its current value.
        common.set_field(item, "equipment_status", "RETIRED")
        common.touch(unit)
        return response.ok(common.serialize(item))