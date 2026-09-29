"""Donor enrolment, health history, clinical clearance and deferrals.

Endpoints (13): POST/GET /donors, GET /donors/{id},
POST/GET /donors/{id}/health-history, POST/GET /donors/{id}/serology-panels,
POST/GET /donors/{id}/physician-approvals, POST /donors/{id}/qualify,
POST /donors/{id}/requalify, POST/GET /donors/{id}/deferrals.
"""

from flask import Blueprint

import domain_donor
import serializers
from auth import (ADMIN, DONOR, INTAKE_COORDINATOR, MEDICAL_DIRECTOR, actor_id,
                  guard, require_own)
from envelope import ok, page, pagination
from errors import fail, not_found, out_of_range
from listing import apply_filters, sort_by
from store import db, find, insert, set_field
from util import add_days, fmt_date, parse_date
from validate import field, json_body, validate

bp = Blueprint("donors", __name__)

ZONE_CODES = ("Z1", "Z2", "Z3")
MARKER_RESULTS = ("NON_REACTIVE", "REACTIVE", "INDETERMINATE")
REASON_CODES = ("MEDICATION", "ILLNESS", "TRAVEL", "DONOR_REQUEST",
                "PHYSICIAN_WITHDRAWAL", "REACTIVE_SEROLOGY", "AUTO_HIGH_RISK")
DEFERRAL_TYPES = ("TEMPORARY", "PERMANENT")
RECALL_SCOPES = ("NONE", "DONATIONS_ONLY", "FULL_CHAIN")

HISTORY_STATES = ("APPLICANT", "SCREENING", "INFO_REQUESTED")
CLEARANCE_STATES = ("APPLICANT", "SCREENING", "INFO_REQUESTED", "QUALIFIED")
DEFERRABLE_STATES = ("SCREENING", "INFO_REQUESTED", "QUALIFIED",
                     "TEMPORARILY_DEFERRED")

DONOR_READERS = (DONOR, INTAKE_COORDINATOR, MEDICAL_DIRECTOR, ADMIN)


def donor_or_404(donor_id):
    donor = find("donors", donor_id)
    if donor is None:
        not_found("Donor '%s' does not exist." % donor_id)
    return donor


def donor_state_gate(donor, admitted):
    if donor["status"] not in admitted:
        fail("ERR_DONOR_STATE_INVALID",
             "A donor in %s may not undergo this operation." % donor["status"])


# --- POST /donors ----------------------------------------------------------
@bp.route("/donors", methods=["POST"])
@guard(INTAKE_COORDINATOR, ADMIN)
def create_donor():
    body = json_body()
    values = validate(body, [
        field("donor_code", "string", regex=r"^DNR-[0-9]{4}$"),
        field("full_name", "string", minlen=1, maxlen=120),
        field("email", "string", contains="@"),
        field("zone_code", "enum", enum=ZONE_CODES),
    ])
    for existing in db.rows("donors"):
        if existing["donor_code"] == values["donor_code"]:
            fail("ERR_DUPLICATE_CODE",
                 "donor_code '%s' is already enrolled." % values["donor_code"])
    donor = insert("donors", {
        "donor_code": values["donor_code"],
        "full_name": values["full_name"],
        "email": values["email"],
        "zone_code": values["zone_code"],
        "status": "APPLICANT",
        "screening_risk_score": 0,
        "surveillance_risk_score": 0,
        "qualified_at": None,
        "qualified_by_user_id": None,
        "reimbursement_balance_cents": 0,
        "lifetime_accepted_volume_ml": 0,
        "temporary_deferral_count": 0,
        "active_deferral_until_date": None,
    })
    return ok(serializers.donor_out(donor), 201)


# --- GET /donors -----------------------------------------------------------
@bp.route("/donors", methods=["GET"])
@guard(INTAKE_COORDINATOR, MEDICAL_DIRECTOR, ADMIN)
def list_donors():
    limit, offset = pagination()
    rows = apply_filters(db.rows("donors"),
                         [("status", "status", "str"),
                          ("zone_code", "zone_code", "str")])
    sort_by(rows, [(lambda r: r["created_at"], True),
                   (lambda r: r["donor_code"], False)])
    return page(rows, limit, offset, serializers.donor_out)


# --- GET /donors/{id} ------------------------------------------------------
@bp.route("/donors/<donor_id>", methods=["GET"])
@guard(*DONOR_READERS)
def get_donor(donor_id):
    require_own(donor_id)
    return ok(serializers.donor_out(donor_or_404(donor_id)))


# --- POST /donors/{id}/health-history --------------------------------------
@bp.route("/donors/<donor_id>/health-history", methods=["POST"])
@guard(INTAKE_COORDINATOR)
def create_questionnaire(donor_id):
    donor = donor_or_404(donor_id)
    body = json_body()
    values = validate(body, [
        field("medication_flag_count", "integer", min=0, max=10),
        field("travel_risk_flag", "boolean"),
        field("tobacco_use", "boolean"),
        field("alcohol_units_per_week", "integer", min=0, max=40),
        field("months_postpartum", "integer", min=0, max=48),
    ])
    donor_state_gate(donor, HISTORY_STATES)

    previous = domain_donor.newest_questionnaire(donor["id"])
    if previous is not None:
        set_field(previous, "status", "SUPERSEDED")

    questionnaire = insert("questionnaires", {
        "donor_id": donor["id"],
        "medication_flag_count": values["medication_flag_count"],
        "travel_risk_flag": values["travel_risk_flag"],
        "tobacco_use": values["tobacco_use"],
        "alcohol_units_per_week": values["alcohol_units_per_week"],
        "months_postpartum": values["months_postpartum"],
        "base_risk_points": 0,
        "screening_risk_score": 0,
        "status": "ACCEPTED",
        "submitted_at": db.clock_instant(),
    })

    base = domain_donor.base_points(questionnaire)
    screening = domain_donor.screening_score(donor, base)
    questionnaire["base_risk_points"] = base
    questionnaire["screening_risk_score"] = screening
    if screening <= domain_donor.RISK_ACCEPT_MAX:
        questionnaire["status"] = "ACCEPTED"
    elif screening <= domain_donor.RISK_DEFER_MAX:
        questionnaire["status"] = "INFO_REQUESTED"
    else:
        questionnaire["status"] = "AUTO_DEFERRED"

    domain_donor.refresh_scores(donor)
    if questionnaire["status"] == "ACCEPTED":
        set_field(donor, "status", "SCREENING")
    elif questionnaire["status"] == "INFO_REQUESTED":
        set_field(donor, "status", "INFO_REQUESTED")
    else:
        event = domain_donor.create_deferral(
            donor, "AUTO_HIGH_RISK", "TEMPORARY", db.clock_date(),
            domain_donor.AUTO_DEFERRAL_DAYS, 0, "NONE", "system")
        domain_donor.apply_deferral(donor, event)
    return ok(serializers.questionnaire_out(questionnaire), 201)


# --- GET /donors/{id}/health-history ---------------------------------------
@bp.route("/donors/<donor_id>/health-history", methods=["GET"])
@guard(*DONOR_READERS)
def list_questionnaires(donor_id):
    require_own(donor_id)
    donor = donor_or_404(donor_id)
    limit, offset = pagination()
    rows = apply_filters(domain_donor.questionnaires_of(donor["id"]),
                         [("status", "status", "str")])
    sort_by(rows, [(lambda r: r["created_at"], True),
                   (lambda r: r["submitted_at"], True)])
    return page(rows, limit, offset, serializers.questionnaire_out)


# --- POST /donors/{id}/serology-panels -------------------------------------
@bp.route("/donors/<donor_id>/serology-panels", methods=["POST"])
@guard(MEDICAL_DIRECTOR)
def create_serology(donor_id):
    donor = donor_or_404(donor_id)
    body = json_body()
    values = validate(body, [
        field("collected_on", "date"),
        field("hiv_result", "enum", enum=MARKER_RESULTS),
        field("htlv_result", "enum", enum=MARKER_RESULTS),
        field("hbv_result", "enum", enum=MARKER_RESULTS),
        field("hcv_result", "enum", enum=MARKER_RESULTS),
        field("syphilis_result", "enum", enum=MARKER_RESULTS),
    ])
    donor_state_gate(donor, CLEARANCE_STATES)

    markers = [values["hiv_result"], values["htlv_result"], values["hbv_result"],
               values["hcv_result"], values["syphilis_result"]]
    if "REACTIVE" in markers:
        panel_status = "REACTIVE"
    elif "INDETERMINATE" in markers:
        panel_status = "INDETERMINATE"
    else:
        panel_status = "NON_REACTIVE"

    panel = insert("serology", {
        "donor_id": donor["id"],
        "collected_on": fmt_date(values["collected_on"]),
        "hiv_result": values["hiv_result"],
        "htlv_result": values["htlv_result"],
        "hbv_result": values["hbv_result"],
        "hcv_result": values["hcv_result"],
        "syphilis_result": values["syphilis_result"],
        "panel_status": panel_status,
        "expires_on": fmt_date(add_days(values["collected_on"],
                                        domain_donor.SEROLOGY_VALIDITY_DAYS)),
        "recorded_by_user_id": actor_id(),
    })

    if panel_status == "REACTIVE":
        event = domain_donor.create_deferral(
            donor, "REACTIVE_SEROLOGY", "PERMANENT", db.clock_date(), 0,
            domain_donor.REACTIVE_LOOKBACK_DAYS, "FULL_CHAIN", "system")
        domain_donor.apply_deferral(donor, event)
    return ok(serializers.serology_out(panel), 201)


# --- GET /donors/{id}/serology-panels --------------------------------------
@bp.route("/donors/<donor_id>/serology-panels", methods=["GET"])
@guard(*DONOR_READERS)
def list_serology(donor_id):
    require_own(donor_id)
    donor = donor_or_404(donor_id)
    limit, offset = pagination()
    rows = apply_filters(domain_donor.serology_of(donor["id"]),
                         [("panel_status", "panel_status", "str")])
    sort_by(rows, [(lambda r: r["collected_on"], True),
                   (lambda r: r["created_at"], True)])
    return page(rows, limit, offset, serializers.serology_out)


# --- POST /donors/{id}/physician-approvals ---------------------------------
@bp.route("/donors/<donor_id>/physician-approvals", methods=["POST"])
@guard(MEDICAL_DIRECTOR)
def create_approval(donor_id):
    donor = donor_or_404(donor_id)
    body = json_body()
    values = validate(body, [
        field("physician_npi", "string", regex=r"^[0-9]{10}$"),
        field("approved_on", "date"),
    ])
    donor_state_gate(donor, CLEARANCE_STATES)
    approval = insert("approvals", {
        "donor_id": donor["id"],
        "physician_npi": values["physician_npi"],
        "approved_on": fmt_date(values["approved_on"]),
        "valid_until": fmt_date(add_days(
            values["approved_on"], domain_donor.PHYSICIAN_APPROVAL_VALIDITY_DAYS)),
        "status": "ACTIVE",
        "recorded_by_user_id": actor_id(),
    })
    return ok(serializers.approval_out(approval), 201)


# --- GET /donors/{id}/physician-approvals ----------------------------------
@bp.route("/donors/<donor_id>/physician-approvals", methods=["GET"])
@guard(*DONOR_READERS)
def list_approvals(donor_id):
    require_own(donor_id)
    donor = donor_or_404(donor_id)
    limit, offset = pagination()
    rows = apply_filters(domain_donor.approvals_of(donor["id"]),
                         [("status", "status", "str")])
    sort_by(rows, [(lambda r: r["approved_on"], True),
                   (lambda r: r["created_at"], True)])
    return page(rows, limit, offset, serializers.approval_out)


# --- POST /donors/{id}/qualify ---------------------------------------------
@bp.route("/donors/<donor_id>/qualify", methods=["POST"])
@guard(MEDICAL_DIRECTOR)
def qualify_donor(donor_id):
    donor = donor_or_404(donor_id)
    donor_state_gate(donor, ("SCREENING",))

    newest = domain_donor.newest_questionnaire(donor["id"])
    if newest is None or newest["status"] != "ACCEPTED":
        fail("ERR_HEALTH_HISTORY_INCOMPLETE",
             "The donor's newest questionnaire is not ACCEPTED.")
    if not domain_donor.has_valid_serology(donor["id"]):
        fail("ERR_SEROLOGY_MISSING_OR_EXPIRED",
             "No unexpired non-reactive serology panel is on file.")
    if not domain_donor.has_active_approval(donor["id"]):
        fail("ERR_PHYSICIAN_APPROVAL_MISSING",
             "No active physician approval is on file.")
    score = domain_donor.surveillance_score(donor)
    if score > domain_donor.RISK_ACCEPT_MAX:
        fail("ERR_RISK_SCORE_TOO_HIGH",
             "The recomputed surveillance risk score is %d." % score)

    set_field(donor, "surveillance_risk_score", score)
    set_field(donor, "qualified_at", db.clock_instant())
    set_field(donor, "qualified_by_user_id", actor_id())
    set_field(donor, "status", "QUALIFIED")
    return ok(serializers.donor_out(donor))


# --- POST /donors/{id}/requalify -------------------------------------------
@bp.route("/donors/<donor_id>/requalify", methods=["POST"])
@guard(MEDICAL_DIRECTOR)
def requalify_donor(donor_id):
    donor = donor_or_404(donor_id)
    donor_state_gate(donor, ("TEMPORARILY_DEFERRED",))

    today = db.clock_date()
    until = parse_date(donor["active_deferral_until_date"])
    if until is not None and not today > until:
        fail("ERR_DEFERRAL_STILL_ACTIVE",
             "The donor's deferral runs through %s." % donor["active_deferral_until_date"])

    for event in domain_donor.deferrals_of(donor["id"]):
        if event["status"] != "ACTIVE" or event["deferral_type"] != "TEMPORARY":
            continue
        effective_from = parse_date(event["effective_from"])
        if effective_from is None:
            continue
        if add_days(effective_from, event["deferral_days"]) < today:
            set_field(event, "status", "EXPIRED")
    domain_donor.refresh_active_deferral_until(donor)
    domain_donor.refresh_surveillance(donor)
    set_field(donor, "status", "SCREENING")
    return ok(serializers.donor_out(donor))


# --- POST /donors/{id}/deferrals -------------------------------------------
@bp.route("/donors/<donor_id>/deferrals", methods=["POST"])
@guard(MEDICAL_DIRECTOR)
def create_donor_deferral(donor_id):
    donor = donor_or_404(donor_id)
    body = json_body()
    values = validate(body, [
        field("reason_code", "enum", enum=REASON_CODES),
        field("deferral_type", "enum", enum=DEFERRAL_TYPES),
        field("effective_from", "date"),
        field("deferral_days", "integer", min=0, max=3650),
        field("lookback_days", "integer", min=0, max=1095),
        field("recall_scope", "enum", enum=RECALL_SCOPES),
    ])
    # The type / duration consistency rule is part of range validation and so
    # runs before the donor's state gate (PRD 2.10).
    if values["deferral_type"] == "PERMANENT" and values["deferral_days"] != 0:
        out_of_range("deferral_days must be exactly 0 for a PERMANENT deferral.")
    if values["deferral_type"] == "TEMPORARY" and values["deferral_days"] < 1:
        out_of_range("deferral_days must be at least 1 for a TEMPORARY deferral.")

    donor_state_gate(donor, DEFERRABLE_STATES)

    event = domain_donor.create_deferral(
        donor, values["reason_code"], values["deferral_type"],
        values["effective_from"], values["deferral_days"],
        values["lookback_days"], values["recall_scope"], actor_id())
    domain_donor.apply_deferral(donor, event)
    return ok(serializers.deferral_out(event), 201)


# --- GET /donors/{id}/deferrals --------------------------------------------
@bp.route("/donors/<donor_id>/deferrals", methods=["GET"])
@guard(*DONOR_READERS)
def list_donor_deferrals(donor_id):
    require_own(donor_id)
    donor = donor_or_404(donor_id)
    limit, offset = pagination()
    rows = apply_filters(domain_donor.deferrals_of(donor["id"]),
                         [("status", "status", "str"),
                          ("deferral_type", "deferral_type", "str")])
    sort_by(rows, [(lambda r: r["effective_from"], True),
                   (lambda r: r["created_at"], True)])
    return page(rows, limit, offset, serializers.deferral_out)
