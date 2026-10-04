"""Facility endpoints (PRD §3.1, §3.6, §4)."""

import flask

import db
import response
from errors import fail
from middleware import require
from services import cascades, common


def register_routes(app):

    @app.route("/accreditation/facilities", methods=["POST"])
    @require(["FacilityAdmin", "Any"])
    def create_facility(principal):
        # Opening a facility record is reachable by both the facility itself and
        # any authenticated caller, so a program can bootstrap the resource graph
        # before a facility principal exists to act as.
        payload = common.body()
        common.require_fields(payload, ["name", "state_code", "facility_type"])
        common.check_required_enum(payload, "facility_type", "facility_type")
        facility = common.make_record(
            id=db.new_id(),
            name=payload["name"],
            state_code=payload["state_code"],
            facility_type=payload["facility_type"],
            facility_status="PENDING",
            accreditation_currency="PROVISIONAL",
            payer_participation_status="AT_RISK",
            registry_credit_cents=0,
            enrolled_unit_count=0,
            deferred_unit_count=0,
            current_cycle_index=0,
            rejected_survey_count=0,
            roster_disposition="CLEAR",
        )
        db.FACILITIES[facility["id"]] = facility
        return response.ok(common.serialize(facility), 201)

    @app.route("/accreditation/facilities", methods=["GET"])
    @require(["Any"])
    def list_facilities(principal):
        rows = list(db.FACILITIES.values())
        for field in ("state_code", "facility_type", "facility_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/facilities/<facility_id>", methods=["GET"])
    @require(["Any"])
    def read_facility(principal, facility_id):
        facility = common.get_facility(facility_id)
        common.settle_facility_time(facility)
        common.recompute_roster_disposition(facility)
        common.recompute_all_deadline_statuses(facility["id"])
        return response.ok(common.serialize(facility))

    @app.route("/accreditation/facilities/<facility_id>/summary", methods=["GET"])
    @require(["Any"])
    def facility_summary(principal, facility_id):
        facility = common.get_facility(facility_id)
        common.settle_facility_time(facility)
        common.recompute_enrolled_unit_count(facility)
        common.recompute_rejected_survey_count(facility)
        common.recompute_roster_disposition(facility)
        for unit in common.facility_units(facility["id"]):
            common.recompute_deficiency_open_count(unit)
        common.recompute_all_deadline_statuses(facility["id"])
        return response.ok(common.serialize(facility))

    @app.route("/accreditation/facilities/<facility_id>/register", methods=["POST"])
    @require(["FacilityAdmin"])
    def register_facility(principal, facility_id):
        facility = common.get_facility(facility_id)
        payload = common.body()

        # State rung first: only a PENDING facility is on the enrollment path.
        if facility["facility_status"] == "ENROLLED":
            fail("ERR_INVALID_STATE", "the facility is already ENROLLED")
        if facility["facility_status"] in ("SUSPENDED", "DEFERRED"):
            fail("ERR_INVALID_STATE", "the facility is not on the enrollment path")

        units = common.facility_units(facility["id"])
        if not units:
            fail("ERR_INVALID_STATE", "the facility has no modality unit")
        if any(u["unit_status"] != "ENROLLED" for u in units):
            fail("ERR_INVALID_STATE", "a modality unit of this facility is not ENROLLED")
        if any(e["equipment_status"] != "ACTIVE" for e in common.facility_equipment(facility["id"])):
            fail("ERR_INVALID_STATE", "an equipment item of this facility is not ACTIVE")

        common.enforce_version(facility, payload, "expected_facility_version")
        common.recompute_all_deadline_statuses(facility["id"])
        if common.has_pending_plan(facility["id"]):
            fail("ERR_DEFICIENCY_PENDING", "the facility holds an open corrective action plan")
        common.recompute_roster_disposition(facility)
        if facility["roster_disposition"] == "HALT" or common.has_revoked_qualification(facility["id"]):
            fail("ERR_SURVEY_SHORTFALL", "the facility's roster is ineligible")

        common.set_field(facility, "facility_status", "ENROLLED")
        facility["accreditation_currency"] = "PROVISIONAL"
        facility["payer_participation_status"] = "ACTIVE"
        common.recompute_enrolled_unit_count(facility)
        facility["rejected_survey_count"] = 0
        return response.ok(common.serialize(facility))

    @app.route("/accreditation/facilities/<facility_id>/suspend", methods=["POST"])
    @require(["AccreditationBody"])
    def suspend_facility(principal, facility_id):
        facility = common.get_facility(facility_id)
        payload = common.body()

        if facility["facility_status"] != "ENROLLED":
            fail("ERR_INVALID_STATE", "the facility is not ENROLLED")

        units = common.facility_units(facility["id"])
        if not any(u["unit_status"] in ("ENROLLED", "DEFERRED") for u in units):
            fail("ERR_INVALID_STATE", "the facility has no enrolled or deferred unit")

        common.enforce_version(facility, payload, "expected_facility_version")
        cascades.suspend_facility(facility)
        common.touch(facility)
        return response.ok(common.serialize(facility))

    @app.route("/accreditation/facilities/<facility_id>/reinstate", methods=["POST"])
    @require(["AccreditationBody"])
    def reinstate_facility(principal, facility_id):
        facility = common.get_facility(facility_id)
        payload = common.body()

        if facility["facility_status"] not in ("DEFERRED", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "the facility is not suspended or deferred")

        for plan in common.facility_plans(facility["id"]):
            if plan["plan_status"] not in ("ACCEPTED", "EXPIRED"):
                fail("ERR_INVALID_STATE", "a corrective action plan of this facility is unresolved")

        common.enforce_version(facility, payload, "expected_facility_version")
        common.set_field(facility, "facility_status", "PENDING")
        facility["payer_participation_status"] = "AT_RISK"
        facility["rejected_survey_count"] = 0
        return response.ok(common.serialize(facility))

    @app.route("/accreditation/facilities/<facility_id>/registry-credit", methods=["POST"])
    @require(["FacilityAdmin"])
    def purchase_registry_credit(principal, facility_id):
        facility = common.get_facility(facility_id)
        payload = common.body()
        common.require_fields(payload, ["amount_cents"])
        amount = common.as_int(payload, "amount_cents")
        common.enforce_version(facility, payload, "expected_facility_version")
        facility["registry_credit_cents"] = facility["registry_credit_cents"] + amount
        common.touch(facility)
        return response.ok(common.serialize(facility))