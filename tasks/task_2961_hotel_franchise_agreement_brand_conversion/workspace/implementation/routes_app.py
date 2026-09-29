"""Application intake, the two independent review studies, the encroachment
claim docket and the approval gate (PRD 3.3, 3.4 and 3.5)."""

from flask import Blueprint

import calc
import domain
import envelope
import store
import validation
from auth import ROLE_BSD, ROLE_FDM, ROLE_OWNER, authenticate
from common import (
    ZERO,
    add_days,
    add_years_date,
    clock_now,
    fmt_date,
    fmt_instant,
    parse_date,
    parse_instant,
)
from errors import ApiError
from serialize import dump, dump_all
from store import touch

bp = Blueprint("applications", __name__)

AFFILIATIONS = ("INDEPENDENT", "COMPETITOR", "OUR_BRAND")
APPLICATION_SPECS = [
    {"name": "owner_id", "type": "string", "required": True, "min_len": 1},
    {"name": "brand_id", "type": "string", "required": True, "min_len": 1},
    {"name": "property_name", "type": "string", "required": True, "min_len": 1,
     "max_len": 120},
    {"name": "market_code", "type": "string", "required": True, "min_len": 3,
     "max_len": 8, "upper_alnum": True},
    {"name": "property_x_miles", "type": "number", "required": True,
     "minimum": "-500.00", "maximum": "500.00"},
    {"name": "property_y_miles", "type": "number", "required": True,
     "minimum": "-500.00", "maximum": "500.00"},
    {"name": "room_count", "type": "integer", "required": True, "minimum": 1},
    {"name": "current_affiliation", "type": "enum", "required": True,
     "values": AFFILIATIONS},
    {"name": "building_age_years", "type": "integer", "required": True, "minimum": 0,
     "maximum": 150},
    {"name": "requested_term_years", "type": "integer", "required": True, "minimum": 5,
     "maximum": 30},
    {"name": "requested_conversion_date", "type": "date", "required": True},
]

NOTES = {"name": "analyst_notes", "type": "string", "required": False, "nullable": True}


def _stage(application, allowed):
    if application["status"] not in allowed:
        raise ApiError("ERR_APPLICATION_STAGE_INVALID")


def _impact_units(application, brand, statuses):
    return store.ordered(
        store.existing_units,
        lambda u: u["brand_id"] == brand["id"] and u["status"] in statuses,
    )


# ---------------------------------------------------------------------------
# Intake and reads
# ---------------------------------------------------------------------------


@bp.post("/applications")
def create_application():
    authenticate((ROLE_FDM,))
    payload = validation.body()
    owner_id = validation.fk_string(payload, "owner_id")
    owner = store.get_owner(owner_id) if owner_id is not None else None
    brand_id = validation.fk_string(payload, "brand_id")
    brand = store.get_brand(brand_id) if brand_id is not None else None
    fields = validation.take(payload, APPLICATION_SPECS)
    if owner is None:
        owner = store.get_owner(fields["owner_id"])
    if brand is None:
        brand = store.get_brand(fields["brand_id"])
    row = domain.new_application_row()
    for spec in APPLICATION_SPECS:
        row[spec["name"]] = fields[spec["name"]]
    row["requested_conversion_date"] = fmt_date(fields["requested_conversion_date"])
    store.applications[row["id"]] = row
    domain.brand_recount(brand)
    return envelope.created(dump(row))


@bp.get("/applications/<application_id>")
def read_application(application_id):
    principal = authenticate((ROLE_FDM, ROLE_BSD, ROLE_OWNER))
    application = store.get_application(application_id)
    domain.require_application_owner(principal, application)
    return envelope.ok(dump(application))


@bp.get("/applications")
def list_applications():
    authenticate((ROLE_FDM, ROLE_BSD))
    limit, offset = envelope.pagination()
    owner_id = validation.query_filter("owner_id")
    brand_id = validation.query_filter("brand_id")
    status = validation.query_filter("status")

    def keep(row):
        if owner_id is not None and row["owner_id"] != owner_id:
            return False
        if brand_id is not None and row["brand_id"] != brand_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = store.ordered(store.applications, keep)
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


# ---------------------------------------------------------------------------
# The primary review axis
# ---------------------------------------------------------------------------


@bp.post("/applications/<application_id>/start-review")
def start_review(application_id):
    authenticate((ROLE_FDM,))
    application = store.get_application(application_id)
    validation.body()
    _stage(application, ("SUBMITTED",))
    application["status"] = "UNDER_REVIEW"
    touch(application)
    domain.brand_recount(domain.brand_of_application(application))
    return envelope.ok(dump(application))


@bp.post("/applications/<application_id>/request-revision")
def request_revision(application_id):
    authenticate((ROLE_FDM,))
    application = store.get_application(application_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [{"name": "revision_notes", "type": "string", "required": True, "min_len": 1}],
    )
    _stage(application, ("UNDER_REVIEW",))
    application["status"] = "REVISION_REQUESTED"
    application["revision_notes"] = fields["revision_notes"]
    touch(application)
    domain.brand_recount(domain.brand_of_application(application))
    return envelope.ok(dump(application))


@bp.post("/applications/<application_id>/resubmit")
def resubmit(application_id):
    principal = authenticate((ROLE_OWNER,))
    application = store.get_application(application_id)
    domain.require_application_owner(principal, application)
    payload = validation.body()
    fields = validation.take(
        payload,
        [{"name": "revision_response", "type": "string", "required": True,
          "min_len": 1}],
    )
    _stage(application, ("REVISION_REQUESTED",))
    application["status"] = "UNDER_REVIEW"
    application["revision_round"] = application["revision_round"] + 1
    application["revision_response"] = fields["revision_response"]
    application["financial_review_status"] = "NOT_STARTED"
    application["capacity_basis"] = None
    application["capacity_score_at_review"] = None
    application["capacity_band_at_review"] = None
    application["financial_reviewer_user_id"] = None
    application["impact_study_status"] = "NOT_STARTED"
    application["preliminary_impact_score"] = None
    application["impact_unit_count_preliminary"] = None
    application["base_impact_score"] = None
    application["final_impact_score"] = None
    application["impact_unit_count_final"] = None
    application["encroachment_verdict"] = None
    application["claim_window_closes_at"] = None
    touch(application)
    domain.brand_recount(domain.brand_of_application(application))
    return envelope.ok(dump(application))


# ---------------------------------------------------------------------------
# The financial capacity review
# ---------------------------------------------------------------------------


@bp.post("/applications/<application_id>/financial-review")
def financial_review(application_id):
    principal = authenticate((ROLE_FDM,))
    application = store.get_application(application_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "capacity_basis", "type": "enum", "required": True,
             "values": ("STANDALONE", "PORTFOLIO_ADJUSTED")},
            {"name": "reviewer_notes", "type": "string", "required": False,
             "nullable": True},
        ],
    )
    _stage(application, ("UNDER_REVIEW",))
    owner = domain.owner_of_application(application)
    score, band = calc.owner_score_for_basis(owner, fields["capacity_basis"])
    application["capacity_basis"] = fields["capacity_basis"]
    application["capacity_score_at_review"] = score
    application["capacity_band_at_review"] = band
    application["financial_review_status"] = (
        "FAILED" if band == "INSUFFICIENT" else "PASSED"
    )
    application["financial_reviewer_user_id"] = principal.user_id
    touch(application)
    return envelope.ok(dump(application))


# ---------------------------------------------------------------------------
# The market impact study
# ---------------------------------------------------------------------------


@bp.post("/applications/<application_id>/impact-analysis")
def impact_analysis(application_id):
    authenticate((ROLE_BSD,))
    application = store.get_application(application_id)
    payload = validation.body()
    validation.take(payload, [NOTES])
    _stage(application, ("UNDER_REVIEW",))
    brand = domain.brand_of_application(application)
    units = _impact_units(application, brand, ("OPERATING",))
    score, admitted = calc.market_impact_score(application, brand, units)
    application["preliminary_impact_score"] = score
    application["impact_unit_count_preliminary"] = admitted
    application["impact_study_status"] = "PRELIMINARY"
    application["claim_window_closes_at"] = fmt_instant(
        add_days(clock_now(), calc.CLAIM_WINDOW_DAYS)
    )
    touch(application)
    return envelope.ok(dump(application))


@bp.post("/applications/<application_id>/finalize-impact")
def finalize_impact(application_id):
    authenticate((ROLE_BSD,))
    application = store.get_application(application_id)
    payload = validation.body()
    validation.take(payload, [NOTES])
    _stage(application, ("UNDER_REVIEW",))
    if application["impact_study_status"] != "PRELIMINARY":
        raise ApiError("ERR_IMPACT_STUDY_STAGE_INVALID")
    brand = domain.brand_of_application(application)
    units = _impact_units(application, brand, ("OPERATING", "SUSPENDED"))
    base, admitted = calc.market_impact_score(application, brand, units)
    final = calc.final_impact_score(base, application["sustained_claim_count"])
    application["base_impact_score"] = base
    application["impact_unit_count_final"] = admitted
    application["final_impact_score"] = final
    application["encroachment_verdict"] = calc.encroachment_verdict(final)
    application["impact_study_status"] = "FINAL"
    touch(application)
    return envelope.ok(dump(application))


# ---------------------------------------------------------------------------
# Encroachment claims
# ---------------------------------------------------------------------------


@bp.post("/applications/<application_id>/encroachment-claims")
def file_claim(application_id):
    principal = authenticate((ROLE_BSD,))
    application = store.get_application(application_id)
    payload = validation.body()
    unit_id = validation.fk_string(payload, "existing_unit_id")
    unit = store.get_unit(unit_id) if unit_id is not None else None
    fields = validation.take(
        payload,
        [
            {"name": "existing_unit_id", "type": "string", "required": True,
             "min_len": 1},
            {"name": "claimed_revenue_loss_pct", "type": "number", "required": True,
             "minimum": "0.00", "maximum": "100.00"},
            {"name": "narrative", "type": "string", "required": True, "min_len": 1,
             "max_len": 2000},
        ],
    )
    if unit is None:
        unit = store.get_unit(fields["existing_unit_id"])
    _stage(application, ("UNDER_REVIEW", "APPROVED"))
    if unit["status"] != "OPERATING" or unit["brand_id"] != application["brand_id"]:
        raise ApiError("ERR_UNIT_NOT_OPERATING")
    closes_at = application["claim_window_closes_at"]
    if closes_at is None or fmt_instant(clock_now()) > closes_at:
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED")
    row = store.new_row("claim")
    row["application_id"] = application["id"]
    row["existing_unit_id"] = unit["id"]
    row["claimed_revenue_loss_pct"] = fields["claimed_revenue_loss_pct"]
    row["narrative"] = fields["narrative"]
    row["distance_miles"] = calc.unit_distance(unit, application)
    row["status"] = "FILED"
    row["penalty_points_applied"] = ZERO
    row["resolution_notes"] = None
    row["resolved_at"] = None
    row["filed_by_user_id"] = principal.user_id
    store.claims[row["id"]] = row
    return envelope.created(dump(row))


@bp.get("/encroachment-claims/<claim_id>")
def read_claim(claim_id):
    authenticate((ROLE_FDM, ROLE_BSD))
    return envelope.ok(dump(store.get_claim(claim_id)))


@bp.get("/encroachment-claims")
def list_claims():
    authenticate((ROLE_FDM, ROLE_BSD))
    limit, offset = envelope.pagination()
    application_id = validation.query_filter("application_id")
    unit_id = validation.query_filter("existing_unit_id")
    status = validation.query_filter("status")

    def keep(row):
        if application_id is not None and row["application_id"] != application_id:
            return False
        if unit_id is not None and row["existing_unit_id"] != unit_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = store.ordered(store.claims, keep)
    return envelope.listing(
        dump_all(envelope.window(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.post("/encroachment-claims/<claim_id>/resolve")
def resolve_claim(claim_id):
    authenticate((ROLE_BSD,))
    claim = store.get_claim(claim_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "outcome", "type": "enum", "required": True,
             "values": ("SUSTAIN", "OVERRULE")},
            {"name": "resolution_notes", "type": "string", "required": True,
             "min_len": 1},
        ],
    )
    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_FILED")
    claim["resolution_notes"] = fields["resolution_notes"]
    claim["resolved_at"] = domain.now()
    if fields["outcome"] == "OVERRULE":
        claim["status"] = "OVERRULED"
        touch(claim)
        return envelope.ok(dump(claim))

    claim["status"] = "SUSTAINED"
    claim["penalty_points_applied"] = calc.CLAIM_PENALTY_POINTS
    touch(claim)
    application = store.applications.get(claim["application_id"])
    if application is not None:
        application["sustained_claim_count"] = application["sustained_claim_count"] + 1
        if application["impact_study_status"] == "FINAL":
            application["impact_study_status"] = "PRELIMINARY"
            application["base_impact_score"] = None
            application["final_impact_score"] = None
            application["impact_unit_count_final"] = None
            application["encroachment_verdict"] = None
        touch(application)
        for agreement in store.ordered(
            store.agreements,
            lambda a: a["application_id"] == application["id"] and a["status"] == "DRAFT",
        ):
            agreement["status"] = "VOIDED"
            touch(agreement)
    return envelope.ok(dump(claim))


# ---------------------------------------------------------------------------
# The approval gate
# ---------------------------------------------------------------------------


@bp.post("/applications/<application_id>/decision")
def decide_application(application_id):
    principal = authenticate((ROLE_FDM,))
    application = store.get_application(application_id)
    payload = validation.body()
    fields = validation.take(
        payload,
        [
            {"name": "outcome", "type": "enum", "required": True,
             "values": ("APPROVE", "DECLINE")},
            {"name": "decision_notes", "type": "string", "required": True,
             "min_len": 1},
            {"name": "encroachment_waiver_granted", "type": "boolean",
             "required": False, "default": False},
        ],
    )
    _stage(application, ("UNDER_REVIEW",))
    if (
        application["financial_reviewer_user_id"] is not None
        and principal.user_id == application["financial_reviewer_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    waiver = bool(fields["encroachment_waiver_granted"])
    brand = domain.brand_of_application(application)
    if fields["outcome"] == "APPROVE":
        _guard_territory_term(application, brand)
        if any(
            c["status"] == "FILED"
            for c in store.claims.values()
            if c["application_id"] == application["id"]
        ):
            raise ApiError("ERR_OPEN_ENCROACHMENT_CLAIMS")
        if int(application["room_count"]) < int(brand["min_room_count"]):
            raise ApiError("ERR_ROOM_COUNT_BELOW_BRAND_MINIMUM")
        if application["financial_review_status"] != "PASSED":
            raise ApiError("ERR_FINANCIAL_REVIEW_NOT_PASSED")
        if application["impact_study_status"] != "FINAL":
            raise ApiError("ERR_IMPACT_STUDY_NOT_FINAL")
        if application["encroachment_verdict"] == "ENCROACHMENT_CONFIRMED" and not waiver:
            raise ApiError("ERR_ENCROACHMENT_CONFIRMED")

    application["status"] = "APPROVED" if fields["outcome"] == "APPROVE" else "DECLINED"
    application["decision_outcome"] = fields["outcome"]
    application["decision_notes"] = fields["decision_notes"]
    application["encroachment_waiver_granted"] = waiver
    application["decision_user_id"] = principal.user_id
    application["decided_at"] = domain.now()
    touch(application)
    domain.brand_recount(brand)
    return envelope.ok(dump(application))


def _guard_territory_term(application, brand):
    """Closed-interval overlap between a candidate unit's area of protection and
    the term the applicant asked for."""
    requested_start = parse_date(application["requested_conversion_date"])
    requested_end = add_years_date(
        requested_start, int(application["requested_term_years"])
    )
    radius = calc.D(brand["protected_radius_miles"])
    for unit in store.ordered(
        store.existing_units, lambda u: u["brand_id"] == brand["id"]
    ):
        if calc.unit_distance(unit, application) > radius:
            continue
        unit_start = parse_date(unit["territory_start_date"])
        unit_end = parse_date(unit["territory_end_date"])
        if unit_start <= requested_end and requested_start <= unit_end:
            raise ApiError("ERR_TERRITORY_TERM_CONFLICT")
