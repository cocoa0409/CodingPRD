"""Policy enrollments: intake, the queue, approval snapshots and binding
(PRD §3.5, §3.7, §3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import db
import reqs
from clock import fmt_dt
from errors import err
from middleware import authorize, require_agency_of_record
from response import array, ok, paginate
from serialize import render, render_list
from services import core

bp = Blueprint("enrollments", __name__)

READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "PlatformAdmin",
           "ComplianceReporter", "RiskConsultant")
ENROLLMENT_READERS = ("Underwriter", "AgencyProducer", "ClaimsAdjuster", "PlatformAdmin",
                      "ComplianceReporter")
SUMMARY_READERS = ("Underwriter", "AgencyProducer", "ComplianceReporter", "PlatformAdmin")

PROVISIONS = ("GUARANTEED", "EXTENDED", "NONE")


def common_fields():
    now = fmt_dt(db.now())
    return {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}


def _require_state(enrollment, states):
    if enrollment["status"] not in states:
        raise err("ERR_INVALID_STATE",
                  "Enrollment is not in a state from which this transition is declared.")


def _property(enrollment):
    return core.get(db.PROPERTIES, enrollment["property_id"], "Property")


# --------------------------------------------------------------------------
# intake and reads
# --------------------------------------------------------------------------
@bp.route("/hnw/properties/<property_id>/enrollments", methods=["POST"])
def create_enrollment(property_id):
    authorize(("AgencyProducer",))
    prop = core.get(db.PROPERTIES, property_id, "Property")
    data = reqs.body()
    agency = core.get(db.AGENCIES, reqs.string(data, "agency_id", required=True), "Agency")
    record = common_fields()
    record.update({
        "property_id": prop["id"],
        "agency_id": agency["id"],
        "risk_zone_id": prop["risk_zone_id"],
        "dwelling_coverage_cents": reqs.integer(data, "dwelling_coverage_cents",
                                                required=True, minimum=0, strict_min=True),
        "contents_coverage_cents": reqs.integer(data, "contents_coverage_cents",
                                                default=0, minimum=0),
        "scheduled_coverage_cents": reqs.integer(data, "scheduled_coverage_cents",
                                                 default=0, minimum=0),
        "loss_of_use_coverage_cents": reqs.integer(data, "loss_of_use_coverage_cents",
                                                   default=0, minimum=0),
        "risk_score": 0,
        "risk_tier": "MANAGED",
        "required_dwelling_coverage_cents": 0,
        "gross_premium_cents": 0,
        "extended_replacement_premium_cents": 0,
        "extended_replacement_limit_cents": 0,
        "guaranteed_replacement_limit_cents": 0,
        "replacement_provision": "NONE",
        "stress_reserve_cents": 0,
        "committed_reserve_cents": 0,
        "status": "DRAFT",
        "bound_at": None,
        "valuation_fingerprint": "",
        "expected_property_version": None,
    })
    db.ENROLLMENTS[record["id"]] = record
    core.recompute_enrollment_reserves(record)
    return ok(render(record), status=201)


@bp.route("/hnw/enrollments", methods=["GET"])
def list_enrollments():
    authorize(READERS)
    limit, offset = reqs.pagination()
    rows = list(db.ENROLLMENTS.values())
    for field in ("property_id", "agency_id", "risk_zone_id", "status"):
        value = reqs.query(field)
        if value:
            rows = [e for e in rows if e.get(field) == value]
    rows = reqs.sorted_by_created(rows)
    page, meta = paginate(rows, limit, offset)
    return array(render_list(page), meta)


@bp.route("/hnw/enrollments/<enrollment_id>", methods=["GET"])
def read_enrollment(enrollment_id):
    authorize(ENROLLMENT_READERS)
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/underwriting-summary", methods=["GET"])
def underwriting_summary(enrollment_id):
    authorize(SUMMARY_READERS)
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    raw_view = reqs.query("view")
    gross = False
    if raw_view is not None:
        view = str(raw_view).strip().upper()
        if view not in ("NET", "GROSS"):
            raise err("ERR_INVALID_REQUEST", "view must be NET or GROSS.")
        gross = view == "GROSS"
    parts = calc.risk_score_parts(enrollment["property_id"], gross=gross)
    return ok({
        "risk_score": parts["risk_score"],
        "risk_tier": parts["risk_tier"],
        "base_score": parts["base_score"],
        "band_points": parts["band_points"],
        "mitigation_credit": parts["mitigation_credit"],
        "agency_points": parts["agency_points"],
    })


# --------------------------------------------------------------------------
# endorsements
# --------------------------------------------------------------------------
@bp.route("/hnw/enrollments/<enrollment_id>/endorsements", methods=["POST"])
def add_endorsement(enrollment_id):
    authorize(("Underwriter", "AgencyProducer"))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    data = reqs.body()
    endorsement_code = reqs.string(data, "endorsement_code", required=True)
    required_provision = reqs.enum(data, "required_provision", PROVISIONS)
    if (required_provision != "NONE"
            and enrollment["status"] in ("APPROVED", "ATTACHED")
            and enrollment["replacement_provision"] != required_provision):
        raise err("ERR_INCOMPATIBLE_ENDORSEMENT",
                  "The endorsement's required provision conflicts with the enrollment's "
                  "snapshotted replacement provision.")
    record = {
        "id": db.new_id(),
        "created_at": fmt_dt(db.now()),
        "enrollment_id": enrollment["id"],
        "endorsement_code": endorsement_code,
        "required_provision": required_provision,
        "void_on_recall": enrollment["status"] != "ATTACHED",
    }
    db.ENDORSEMENTS[record["id"]] = record
    return ok({
        "endorsement_id": record["id"],
        "enrollment_id": enrollment["id"],
        "void_on_recall": record["void_on_recall"],
    }, status=201)


# --------------------------------------------------------------------------
# queue transitions
# --------------------------------------------------------------------------
@bp.route("/hnw/enrollments/<enrollment_id>/submit", methods=["POST"])
def submit(enrollment_id):
    user_id, role = authorize(("AgencyProducer",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    prop = _property(enrollment)
    if prop["posture"] == "WRITE_FROZEN":
        raise err("ERR_WRITE_FROZEN",
                  "The property's posture is WRITE_FROZEN.")
    if prop["posture"] == "REFERRAL_REQUIRED":
        raise err("ERR_POSTURE_REFERRAL_REQUIRED",
                  "The property's posture is REFERRAL_REQUIRED.")
    require_agency_of_record(user_id, role, enrollment["agency_id"])
    _require_state(enrollment, ("DRAFT",))
    agency = core.get(db.AGENCIES, enrollment["agency_id"], "Agency")
    if not agency["active"]:
        raise err("ERR_AGENCY_INACTIVE", "The producing agency is inactive.")
    if prop["posture"] == "WRITE_FROZEN":
        raise err("ERR_WRITE_FROZEN",
                  "The property's posture is WRITE_FROZEN.")
    if prop["posture"] == "REFERRAL_REQUIRED":
        raise err("ERR_POSTURE_REFERRAL_REQUIRED",
                  "The property's posture is REFERRAL_REQUIRED.")
    enrollment["status"] = "SUBMITTED"
    core.touch(enrollment)
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/refer", methods=["POST"])
def refer(enrollment_id):
    authorize(("Underwriter",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    _require_state(enrollment, ("SUBMITTED",))
    prop = _property(enrollment)
    if prop["posture"] not in ("REFERRAL_REQUIRED", "WRITE_ELIGIBLE"):
        raise err("ERR_INVALID_STATE",
                  "The property's posture is not REFERRAL_REQUIRED or WRITE_ELIGIBLE.")
    enrollment["status"] = "REFERRED"
    core.touch(enrollment)
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/approve", methods=["POST"])
def approve(enrollment_id):
    authorize(("Underwriter",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    prop = _property(enrollment)
    status = enrollment["status"]
    # The order of the queue hops is fixed by PRD 3.5/3.7: the state gate is
    # priority 8, ahead of any posture-derived business gate, so an enrollment
    # whose status admits no approval path is refused on the state alone.
    if status not in ("SUBMITTED", "REFERRED"):
        raise err("ERR_INVALID_STATE",
                  "Enrollment is not in a state from which approval is declared.")
    if status == "SUBMITTED":
        if prop["posture"] not in ("WRITE_ELIGIBLE", "REFERRAL_REQUIRED"):
            raise err("ERR_INVALID_STATE",
                      "The property's posture is neither WRITE_ELIGIBLE nor REFERRAL_REQUIRED.")
    else:
        if prop["posture"] != "REFERRAL_REQUIRED":
            raise err("ERR_INVALID_STATE",
                      "A parked referral requires posture REFERRAL_REQUIRED to be approved.")
        if prop["base_posture"] != "UNDERWRITABLE":
            raise err("ERR_INVALID_STATE",
                      "A parked referral requires base_posture UNDERWRITABLE to be approved.")
    core.snapshot_enrollment(enrollment)
    enrollment["status"] = "APPROVED"
    core.touch(enrollment)
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/return-to-draft", methods=["POST"])
def return_to_draft(enrollment_id):
    authorize(("Underwriter",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    _require_state(enrollment, ("REFERRED",))
    enrollment["status"] = "DRAFT"
    enrollment["risk_score"] = 0
    enrollment["risk_tier"] = "MANAGED"
    core.touch(enrollment)
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/recall", methods=["POST"])
def recall(enrollment_id):
    user_id, role = authorize(("AgencyProducer",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    require_agency_of_record(user_id, role, enrollment["agency_id"])
    _require_state(enrollment, ("APPROVED",))
    agency = core.get(db.AGENCIES, enrollment["agency_id"], "Agency")
    if not agency["active"]:
        raise err("ERR_AGENCY_INACTIVE", "The producing agency is inactive.")
    if agency["concentration_band"] != "CRITICAL":
        raise err("ERR_INVALID_STATE",
                  "The agency's own concentration band is not CRITICAL.")
    enrollment["status"] = "SUBMITTED"
    enrollment["risk_score"] = 0
    enrollment["risk_tier"] = "MANAGED"
    enrollment["replacement_provision"] = "NONE"
    enrollment["valuation_fingerprint"] = ""
    core.touch(enrollment)
    core.recompute_enrollment_reserves(enrollment)
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/withdraw", methods=["POST"])
def withdraw(enrollment_id):
    user_id, role = authorize(("AgencyProducer",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    require_agency_of_record(user_id, role, enrollment["agency_id"])
    _require_state(enrollment, ("DRAFT", "SUBMITTED"))
    enrollment["status"] = "WITHDRAWN"
    core.touch(enrollment)
    core.recompute_enrollment_reserves(enrollment)
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/decline", methods=["POST"])
def decline(enrollment_id):
    authorize(("Underwriter",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    _require_state(enrollment, ("DRAFT", "SUBMITTED", "REFERRED"))
    reqs.body()
    core.decline_enrollment(enrollment)
    return ok(render(enrollment))


@bp.route("/hnw/enrollments/<enrollment_id>/attach", methods=["POST"])
def attach(enrollment_id):
    authorize(("Underwriter",))
    enrollment = core.get(db.ENROLLMENTS, enrollment_id, "Enrollment")
    data = reqs.body()
    expected = reqs.integer(data, "expected_property_version", required=True)
    prop = _property(enrollment)
    if prop["posture"] == "WRITE_FROZEN":
        raise err("ERR_WRITE_FROZEN", "The property's posture is WRITE_FROZEN.")
    zone = db.ZONES.get(prop["risk_zone_id"])
    if zone is not None and zone["freeze_active"]:
        raise err("ERR_RISK_ZONE_FROZEN",
                  "The bound risk zone is frozen.")
    _require_state(enrollment, ("APPROVED",))
    if expected != prop["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_property_version does not match the current Property.version.")
    if enrollment["dwelling_coverage_cents"] < enrollment["required_dwelling_coverage_cents"]:
        raise err("ERR_COVERAGE_BELOW_REQUIRED",
                  "Coverage A is below the required dwelling coverage.")
    if enrollment["valuation_fingerprint"] != calc.valuation_fingerprint(prop["id"]):
        raise err("ERR_VALUATION_STALE",
                  "The enrollment's valuation fingerprint no longer matches the property.")

    # Re-read the valuation, re-evaluate the provision and re-snapshot.
    core.recompute_property(prop["id"])
    dwelling_rc = prop["dwelling_replacement_cost_cents"]
    enrollment["required_dwelling_coverage_cents"] = calc.required_dwelling_coverage(dwelling_rc)
    provision, guaranteed_limit, extended_limit = calc.provision_block(
        dwelling_rc, prop["mitigation_band"], calc.dispatch_in_progress(prop["id"]))
    enrollment["replacement_provision"] = provision
    enrollment["guaranteed_replacement_limit_cents"] = guaranteed_limit
    enrollment["extended_replacement_limit_cents"] = extended_limit
    enrollment["status"] = "ATTACHED"
    enrollment["bound_at"] = fmt_dt(db.now())
    core.touch(enrollment)
    core.recompute_enrollment_reserves(enrollment)

    for item in db.SCHEDULED_ITEMS.values():
        if item["property_id"] == prop["id"] and item["status"] == "APPROVED":
            item["status"] = "ATTACHED"
            item["attached_value_cents"] = item["declared_value_cents"]
            core.touch(item)
    core.recompute_property(prop["id"])
    # The attach writes the property's exposure ledger, so its version advances.
    core.touch(prop)
    return ok(render(enrollment))