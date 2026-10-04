"""AccreditationCycle endpoints (PRD §3.2, §3.6, §4)."""

import flask

import db
import response
from errors import fail
from middleware import require
from services import calculations, cascades, common

CYCLE_LENGTH_DAYS = 1095
RENEWAL_FEE_CENTS = 75000
RENEWAL_EXTENSION_DAYS = 90
TERMINAL_CYCLE_STATES = ("RENEWED", "LAPSED")


def _renewal_gates(facility):
    """The refusals shared by start-renewal and renew."""
    if facility["facility_status"] != "ENROLLED":
        fail("ERR_INVALID_STATE", "the facility is not ENROLLED")
    for survey in common.facility_surveys(facility["id"]):
        if survey["survey_status"] not in ("ACCEPTED", "RESUBMITTED"):
            fail("ERR_INVALID_STATE", "a physicist survey of this facility is unresolved")
    for item in common.facility_equipment(facility["id"]):
        if item["equipment_status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "an equipment item of this facility is not ACTIVE")

    common.recompute_all_deadline_statuses(facility["id"])
    if common.has_overdue_plan(facility["id"]):
        fail("ERR_DEADLINE_OVERDUE", "the facility holds an overdue corrective action plan")
    if common.has_pending_plan(facility["id"]):
        fail("ERR_DEFICIENCY_PENDING", "the facility holds an open corrective action plan")
    common.recompute_roster_disposition(facility)
    if facility["roster_disposition"] == "HALT" or common.has_revoked_qualification(facility["id"]):
        fail("ERR_SURVEY_SHORTFALL", "the facility's roster is ineligible")
    if common.clinical_role_qualifications_unverified(facility["id"]):
        fail("ERR_QUALIFICATION_UNVERIFIED", "a clinical-role qualification is not VERIFIED")


def register_routes(app):

    @app.route("/accreditation/cycles", methods=["POST"])
    @require(["AccreditationBody"])
    def create_cycle(principal):
        payload = common.body()
        common.require_fields(payload, ["facility_id", "cycle_index", "cycle_started_at"])
        facility = common.get_facility(payload["facility_id"])

        prior_id = payload.get("prior_cycle_id")
        if prior_id is not None:
            prior = db.CYCLES.get(prior_id)
            if prior is None or prior["facility_id"] != facility["id"]:
                fail("ERR_CYCLE_NOT_FOUND", "the named prior cycle does not resolve")

        cycle_index = common.as_int(payload, "cycle_index")
        if any(c["cycle_index"] == cycle_index for c in common.facility_cycles(facility["id"])):
            fail("ERR_CYCLE_INDEX_DUPLICATE", "cycle_index already exists for this facility")

        started_at_value = db.as_ts(payload["cycle_started_at"])
        cycle = common.make_record(
            id=db.new_id(),
            facility_id=facility["id"],
            cycle_index=cycle_index,
            cycle_started_at=started_at_value,
            cycle_status="PENDING",
            cycle_expires_at=db.shift_days(started_at_value, CYCLE_LENGTH_DAYS),
            prior_cycle_id=prior_id,
            benchmark_submission_status="NOT_STARTED",
            audit_selection_status="NOT_APPLICABLE",
            audit_outcome="PENDING",
            unit_count_at_start=0,
        )
        db.CYCLES[cycle["id"]] = cycle
        facility["current_cycle_index"] = cycle_index
        return response.ok(common.serialize(cycle), 201)

    @app.route("/accreditation/cycles", methods=["GET"])
    @require(["Any"])
    def list_cycles(principal):
        rows = list(db.CYCLES.values())
        for field in ("facility_id", "prior_cycle_id", "cycle_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/cycles/<cycle_id>", methods=["GET"])
    @require(["Any"])
    def read_cycle(principal, cycle_id):
        return response.ok(common.serialize(common.get_cycle(cycle_id)))

    @app.route("/accreditation/cycles/<cycle_id>/activate", methods=["POST"])
    @require(["AccreditationBody"])
    def activate_cycle(principal, cycle_id):
        cycle = common.get_cycle(cycle_id)
        if cycle["cycle_status"] in TERMINAL_CYCLE_STATES:
            fail("ERR_ALREADY_TERMINAL", "the cycle has already reached a terminal state")
        if cycle["cycle_status"] != "PENDING":
            fail("ERR_INVALID_STATE", "the cycle is not PENDING")

        facility = common.get_facility(cycle["facility_id"])
        if facility["facility_status"] != "ENROLLED":
            fail("ERR_INVALID_STATE", "the facility is not ENROLLED")

        stamp = db.now()
        cycle["unit_count_at_start"] = sum(
            1 for u in common.facility_units(facility["id"]) if u["unit_status"] == "ENROLLED"
        )
        cycle["cycle_expires_at"] = db.shift_days(cycle["cycle_started_at"], CYCLE_LENGTH_DAYS)
        common.set_field(cycle, "cycle_status", "ACTIVE", stamp)

        facility["current_cycle_index"] = cycle["cycle_index"]
        facility["accreditation_currency"] = "PROVISIONAL"
        common.touch(facility, stamp)

        # A successor cycle closes the cycles it follows.
        for other in common.facility_cycles(facility["id"]):
            if other["cycle_index"] < cycle["cycle_index"] and other["cycle_status"] not in TERMINAL_CYCLE_STATES:
                common.set_field(other, "cycle_status", "RENEWED", stamp)
        return response.ok(common.serialize(cycle))

    @app.route("/accreditation/cycles/<cycle_id>/start-renewal", methods=["POST"])
    @require(["AccreditationBody"])
    def start_renewal(principal, cycle_id):
        cycle = common.get_cycle(cycle_id)
        if cycle["cycle_status"] in TERMINAL_CYCLE_STATES:
            fail("ERR_ALREADY_TERMINAL", "the cycle has already reached a terminal state")
        if cycle["cycle_status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "the cycle is not ACTIVE")

        facility = common.get_facility(cycle["facility_id"])
        _renewal_gates(facility)
        if facility["registry_credit_cents"] < RENEWAL_FEE_CENTS:
            fail("ERR_INSUFFICIENT_REGISTRY_CREDIT", "registry credit does not cover the renewal fee")

        stamp = db.now()
        facility["registry_credit_cents"] = facility["registry_credit_cents"] - RENEWAL_FEE_CENTS
        common.set_field(cycle, "cycle_status", "RENEWAL_DUE", stamp)

        selection = calculations.random_site_audit_selection(cycle, facility)
        cycle["audit_selection_status"] = selection
        if selection == "SELECTED":
            cycle["audit_outcome"] = "PENDING"

        cascades.extend_all_deadlines(facility, RENEWAL_EXTENSION_DAYS, stamp)
        common.touch(facility, stamp)
        return response.ok(common.serialize(cycle))

    @app.route("/accreditation/cycles/<cycle_id>/renew", methods=["POST"])
    @require(["AccreditationBody"])
    def renew_cycle(principal, cycle_id):
        cycle = common.get_cycle(cycle_id)
        if cycle["cycle_status"] in TERMINAL_CYCLE_STATES:
            fail("ERR_ALREADY_TERMINAL", "the cycle has already reached a terminal state")
        if cycle["cycle_status"] != "RENEWAL_DUE":
            fail("ERR_INVALID_STATE", "the cycle is not RENEWAL_DUE")
        if cycle["audit_outcome"] not in ("PASS", "PENDING"):
            fail("ERR_INVALID_STATE", "the cycle's audit outcome does not permit renewal")

        facility = common.get_facility(cycle["facility_id"])
        _renewal_gates(facility)

        stamp = db.now()
        cycle["audit_outcome"] = "PASS"
        common.set_field(cycle, "cycle_status", "RENEWED", stamp)
        for other in common.facility_cycles(facility["id"]):
            if other["cycle_index"] < cycle["cycle_index"] and other["cycle_status"] != "RENEWED":
                common.set_field(other, "cycle_status", "RENEWED", stamp)
        common.touch(facility, stamp)
        return response.ok(common.serialize(cycle))

    @app.route("/accreditation/cycles/<cycle_id>/reject-renewal", methods=["POST"])
    @require(["AccreditationBody"])
    def reject_renewal(principal, cycle_id):
        cycle = common.get_cycle(cycle_id)
        payload = common.body()
        reported = payload.get("audit_outcome")
        if reported is not None and reported not in ("PENDING", "PASS", "FAIL"):
            fail("ERR_INVALID_REQUEST", "invalid value for audit_outcome")

        if cycle["cycle_status"] in TERMINAL_CYCLE_STATES:
            fail("ERR_ALREADY_TERMINAL", "the cycle has already reached a terminal state")
        if cycle["cycle_status"] != "RENEWAL_DUE":
            fail("ERR_INVALID_STATE", "the cycle is not RENEWAL_DUE")
        if not (cycle["audit_outcome"] == "PENDING" or reported == "FAIL"):
            fail("ERR_INVALID_STATE", "the cycle's audit outcome does not permit rejection")

        facility = common.get_facility(cycle["facility_id"])
        stamp = db.now()
        cycle["audit_outcome"] = "FAIL"
        common.set_field(cycle, "cycle_status", "LAPSED", stamp)
        facility["registry_credit_cents"] = facility["registry_credit_cents"] + RENEWAL_FEE_CENTS
        cascades.lapse_facility(facility, stamp)
        common.touch(facility, stamp)
        return response.ok(common.serialize(cycle))