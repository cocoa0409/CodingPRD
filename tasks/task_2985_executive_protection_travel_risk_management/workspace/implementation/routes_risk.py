"""Destination advisories, insurance and the risk-assessment cycle.

PRD 3.2 (assessments), 3.3 (ratings, coverage floors, verification).
"""

from flask import Blueprint

import payload
import serializers
from auth import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROTECTION_MANAGER,
    ROLE_SECURITY_ANALYST,
    ROLE_SECURITY_DIRECTOR,
    acting_id,
    endpoint,
)
from calc import (
    ASSESSMENT_REVIEW_OUTCOMES,
    MAX_REVISION_ROUNDS,
    POLICY_TYPES,
    POLICY_VERIFY_OUTCOMES,
    composite_risk_score,
    exposure_score,
    has_protest_floor_signal,
)
from derive import (
    cascade_assessment_approval,
    cascade_destination_revision,
    get_assessment,
    get_executive,
    get_policy,
    get_rating,
    recompute_rating_derived,
)
from envelope import list_response, object_response
from errors import ApiError
from store import audit_row, rating_for_country, signals_of_executive, store, touch
from util import ZERO_SCORE

bp = Blueprint("risk", __name__)


# ---------------------------------------------------------------------------
# Destination ratings -- PRD 3.3
# ---------------------------------------------------------------------------

_INDEX_FIELDS = (
    "crime_index",
    "political_instability_index",
    "medical_infrastructure_index",
    "natural_hazard_index",
)


@bp.post("/exec-protection/destination-ratings")
@endpoint(ROLE_SECURITY_ANALYST)
def publish_destination_rating():
    data = payload.body()
    country_code = payload.country_field(data, "country_code")
    indices = {name: payload.score_field(data, name) for name in _INDEX_FIELDS}
    advisory_effective_at = payload.instant_field(data, "advisory_effective_at")
    advisory_note = payload.string_field(data, "advisory_note", required=False,
                                         max_len=500, default=None, nullable=True)

    # PRD 2.11 band (b): ERR_DESTINATION_RATING_EXISTS.
    if rating_for_country(country_code) is not None:
        raise ApiError("ERR_DESTINATION_RATING_EXISTS")

    row = audit_row({
        "country_code": country_code,
        "advisory_effective_at": advisory_effective_at,
        "advisory_note": advisory_note,
    })
    row.update(indices)
    recompute_rating_derived(row)
    store.ratings[row["id"]] = row
    return object_response(serializers.destination_rating(row), 201)


@bp.patch("/exec-protection/destination-ratings/<country_code>")
@endpoint(ROLE_SECURITY_ANALYST)
def revise_destination_rating(country_code):
    data = payload.body()
    # PRD 3.3: any subset may be sent; fields not sent are left alone.
    revised = {}
    for name in _INDEX_FIELDS:
        if name in data:
            revised[name] = payload.score_field(data, name)
    if "advisory_effective_at" in data:
        revised["advisory_effective_at"] = payload.instant_field(
            data, "advisory_effective_at")
    if "advisory_note" in data:
        revised["advisory_note"] = payload.string_field(
            data, "advisory_note", required=False, max_len=500, nullable=True)

    rating = get_rating(country_code)
    rating.update(revised)
    cascade_destination_revision(rating)
    return object_response(serializers.destination_rating(rating))


# ---------------------------------------------------------------------------
# Insurance policies -- PRD 3.3
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/insurance-policies")
@endpoint(ROLE_COMPLIANCE_OFFICER, ROLE_PROTECTION_MANAGER)
def create_insurance_policy():
    data = payload.body()
    executive_id = payload.id_field(data, "executive_id")
    policy_type = payload.enum_field(data, "policy_type", POLICY_TYPES)
    coverage_cents = payload.int_field(data, "coverage_cents", minimum=1)
    effective_from = payload.instant_field(data, "effective_from")
    effective_to = payload.instant_field(data, "effective_to")
    excluded_country_codes = payload.country_list_field(data,
                                                        "excluded_country_codes",
                                                        default=[])
    payload.require_interval(effective_from, effective_to)

    get_executive(executive_id)
    row = audit_row({
        "executive_id": executive_id,
        "policy_type": policy_type,
        "coverage_cents": coverage_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "excluded_country_codes": excluded_country_codes,
        "status": "UNVERIFIED",
        "verified_at": None,
        "verification_note": None,
    })
    store.policies[row["id"]] = row
    return object_response(serializers.insurance_policy(row), 201)


@bp.post("/exec-protection/insurance-policies/<policy_id>/verify")
@endpoint(ROLE_COMPLIANCE_OFFICER)
def verify_insurance_policy(policy_id):
    data = payload.body()
    outcome = payload.enum_field(data, "outcome", POLICY_VERIFY_OUTCOMES)
    verification_note = payload.string_field(data, "verification_note",
                                             required=False, max_len=500,
                                             default=None, nullable=True)
    # PRD 3.3: a REJECT outcome requires the note to be present and 1 to 500
    # characters long.
    if outcome == "REJECT":
        if verification_note is None or len(verification_note) < 1:
            raise ApiError("ERR_INVALID_REQUEST")

    policy = get_policy(policy_id)
    # PRD 2.11 item 9: state preconditions.
    if policy["status"] != "UNVERIFIED":
        raise ApiError("ERR_POLICY_INVALID_STATE")
    if outcome == "VERIFY":
        # PRD 3.3: effective_to must be strictly later than the clock reading.
        if not policy["effective_to"] > store.now():
            raise ApiError("ERR_POLICY_INVALID_STATE")
        policy["status"] = "VERIFIED"
        policy["verified_at"] = store.now()
    else:
        policy["status"] = "REJECTED"
    if verification_note is not None:
        policy["verification_note"] = verification_note
    touch(policy)
    return object_response(serializers.insurance_policy(policy))


# ---------------------------------------------------------------------------
# Risk assessments -- PRD 3.2
# ---------------------------------------------------------------------------


@bp.post("/exec-protection/risk-assessments")
@endpoint(ROLE_SECURITY_ANALYST)
def draft_risk_assessment():
    data = payload.body()
    executive_id = payload.id_field(data, "executive_id")
    authored_by_staff_id = payload.id_field(data, "authored_by_staff_id")
    threat_monitoring_score = payload.score_field(data, "threat_monitoring_score")

    get_executive(executive_id)
    # PRD 2.6: a staff identifier that resolves to nothing yields
    # ERR_STAFF_NOT_FOUND however it arrived.
    from derive import get_staff
    get_staff(authored_by_staff_id)
    # PRD 3.2: authored_by_staff_id must equal the creating request's X-User-ID.
    if authored_by_staff_id != acting_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    row = audit_row({
        "executive_id": executive_id,
        "authored_by_staff_id": authored_by_staff_id,
        "approved_by_staff_id": None,
        "supersedes_assessment_id": None,
        "status": "DRAFT",
        "threat_monitoring_score": threat_monitoring_score,
        "public_exposure_component": ZERO_SCORE,
        "residential_component_snapshot": ZERO_SCORE,
        "composite_risk_score": ZERO_SCORE,
        "revision_round": 0,
        "review_notes": None,
        "submitted_at": None,
        "approved_at": None,
    })
    store.assessments[row["id"]] = row
    return object_response(serializers.risk_assessment(row), 201)


@bp.get("/exec-protection/risk-assessments")
@endpoint(ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR,
          ROLE_COMPLIANCE_OFFICER)
def list_risk_assessments():
    limit, offset = payload.pagination()
    rows = list(store.assessments.values())
    for name in ("executive_id", "authored_by_staff_id", "approved_by_staff_id",
                 "supersedes_assessment_id", "status"):
        wanted = payload.request.args.get(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    # PRD 4: newest created_at first.
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
    page, total, has_more = payload.paginate(rows, limit, offset)
    return list_response([serializers.risk_assessment(r) for r in page],
                         limit, offset, total, has_more)


@bp.get("/exec-protection/risk-assessments/<assessment_id>")
@endpoint(ROLE_SECURITY_ANALYST, ROLE_PROTECTION_MANAGER, ROLE_SECURITY_DIRECTOR,
          ROLE_COMPLIANCE_OFFICER)
def read_risk_assessment(assessment_id):
    return object_response(serializers.risk_assessment(get_assessment(assessment_id)))


@bp.post("/exec-protection/risk-assessments/<assessment_id>/submit")
@endpoint(ROLE_SECURITY_ANALYST)
def submit_risk_assessment(assessment_id):
    assessment = get_assessment(assessment_id)
    # PRD 3.2: both edges are available only to the authoring analyst.
    if assessment["authored_by_staff_id"] != acting_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if assessment["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")
    executive = get_executive(assessment["executive_id"])
    if executive["residential_survey_status"] == "PENDING":
        raise ApiError("ERR_RESIDENTIAL_SURVEY_INCOMPLETE")

    signals = signals_of_executive(executive["id"])
    now = store.now()
    # PRD 3.2: the rolling-window reading, every in-window signal at full weight.
    assessment["public_exposure_component"] = exposure_score(signals, now, False)
    assessment["residential_component_snapshot"] = executive["residential_component"]
    assessment["submitted_at"] = now
    assessment["status"] = "SUBMITTED"
    assessment["composite_risk_score"] = composite_risk_score(
        assessment["threat_monitoring_score"],
        assessment["public_exposure_component"],
        assessment["residential_component_snapshot"],
        executive["tier"],
        has_protest_floor_signal(signals, now),
    )
    touch(assessment)
    return object_response(serializers.risk_assessment(assessment))


@bp.post("/exec-protection/risk-assessments/<assessment_id>/review")
@endpoint(ROLE_SECURITY_DIRECTOR)
def review_risk_assessment(assessment_id):
    data = payload.body()
    outcome = payload.enum_field(data, "outcome", ASSESSMENT_REVIEW_OUTCOMES)
    review_notes = payload.string_field(data, "review_notes", required=False,
                                        max_len=500, default=None, nullable=True)
    # PRD 3.2: a RETURN outcome requires review_notes of 1 to 500 characters.
    if outcome == "RETURN":
        if review_notes is None or len(review_notes) < 1:
            raise ApiError("ERR_INVALID_REQUEST")

    assessment = get_assessment(assessment_id)
    # PRD 2.9 / 2.11 item 8: the author may not review their own assessment.
    if assessment["authored_by_staff_id"] == acting_id():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if assessment["status"] != "SUBMITTED":
        raise ApiError("ERR_ASSESSMENT_INVALID_STATE")

    if review_notes is not None:
        assessment["review_notes"] = review_notes

    if outcome == "RETURN":
        # PRD 3.2: increment first, then decide the destination.
        assessment["revision_round"] += 1
        if assessment["revision_round"] <= MAX_REVISION_ROUNDS:
            assessment["status"] = "RETURNED"
        else:
            assessment["status"] = "VOIDED"
        touch(assessment)
    else:
        cascade_assessment_approval(assessment, acting_id())
    return object_response(serializers.risk_assessment(assessment))
