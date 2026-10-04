"""ShortageAgreements: drought contingency sharing plans (PRD section 3.4).

Ratification appends the caller's district (X-User-ID) and flips to RATIFIED at
quorum. Activation against a shortage-tier year re-bases that year's current
published announcement to SHORTAGE_SHARING, recomputes its lines in place with
carried totals preserved, and reruns the curtailment cascade.
"""
from flask import Blueprint

import calc
from auth import ALL_ROLES, authenticate
from envelope import success
from errors import ApiError, not_found
from serial import agreement_view
from store import DB, new_record, touch
from validate import as_int, as_int_range, as_str, get_body, required

bp = Blueprint("shortage_agreements", __name__)


def agreement_or_404(agreement_id):
    agreement = DB["agreements"].get(agreement_id)
    if agreement is None:
        not_found("ShortageAgreement")
    return agreement


@bp.post("/water/shortage-agreements")
def create_agreement():
    authenticate(["ReclamationOperator"])
    body = get_body()
    name = as_str(required(body, "name"), "name")
    t1s = as_int_range(required(body, "tier_1_senior_pct"), "tier_1_senior_pct", 0, 100)
    t1j = as_int_range(required(body, "tier_1_junior_pct"), "tier_1_junior_pct", 0, 100)
    t2s = as_int_range(required(body, "tier_2_senior_pct"), "tier_2_senior_pct", 0, 100)
    t2j = as_int_range(required(body, "tier_2_junior_pct"), "tier_2_junior_pct", 0, 100)
    quorum = as_int_range(required(body, "quorum_district_count"),
                          "quorum_district_count", 1)
    rec = new_record()
    rec.update({
        "name": name,
        "tier_1_senior_pct": t1s,
        "tier_1_junior_pct": t1j,
        "tier_2_senior_pct": t2s,
        "tier_2_junior_pct": t2j,
        "quorum_district_count": quorum,
        "signatory_district_ids": [],
        "status": "PROPOSED",
        "activated_water_year_label": None,
    })
    DB["agreements"][rec["id"]] = rec
    return success(agreement_view(rec), 201)


@bp.get("/water/shortage-agreements/<string:agreement_id>")
def get_agreement(agreement_id):
    authenticate(ALL_ROLES)
    return success(agreement_view(agreement_or_404(agreement_id)))


@bp.post("/water/shortage-agreements/<string:agreement_id>/ratify")
def ratify_agreement(agreement_id):
    user_id, _role = authenticate(["DistrictManager"])
    agreement = agreement_or_404(agreement_id)
    if agreement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a PROPOSED agreement can be ratified")
    if user_id in agreement["signatory_district_ids"]:
        raise ApiError("ERR_ALREADY_RATIFIED", 409,
                       "this district has already ratified the agreement")
    agreement["signatory_district_ids"].append(user_id)
    if len(agreement["signatory_district_ids"]) >= agreement["quorum_district_count"]:
        agreement["status"] = "RATIFIED"
    touch(agreement)
    return success(agreement_view(agreement), 200)


@bp.post("/water/shortage-agreements/<string:agreement_id>/activate")
def activate_agreement(agreement_id):
    authenticate(["RegionalDirector"])
    body = get_body()
    label = as_int(required(body, "water_year_label"), "water_year_label")
    agreement = agreement_or_404(agreement_id)
    # existence: a water year with the given label must exist
    year = None
    for y in DB["water_years"].values():
        if y["label"] == label:
            year = y
            break
    if year is None:
        not_found("WaterYear")
    if agreement["status"] != "RATIFIED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a RATIFIED agreement can be activated")
    # activation conflicts: the year's current announcement must be in a
    # shortage tier, and no other agreement may already cover the label
    announcement = None
    if year["current_announcement_id"] is not None:
        announcement = DB["announcements"].get(year["current_announcement_id"])
    if announcement is None or announcement["shortage_tier"] not in ("TIER_1", "TIER_2"):
        raise ApiError("ERR_ACTIVATION_CONFLICT", 409,
                       "the water year's current announcement is not in a shortage tier")
    for other in DB["agreements"].values():
        if (other["id"] != agreement["id"] and other["status"] == "ACTIVATED"
                and other["activated_water_year_label"] == label):
            raise ApiError("ERR_ACTIVATION_CONFLICT", 409,
                           "another agreement is already ACTIVATED for this label")
    agreement["status"] = "ACTIVATED"
    agreement["activated_water_year_label"] = label
    touch(agreement)
    # re-base the year: in-place line recompute under the sharing formula,
    # carried delivered/transfer totals preserved, then the curtailment cascade
    announcement["allocation_basis"] = "SHORTAGE_SHARING"
    touch(announcement)
    allocations = calc.sharing_allocations(
        calc.active_contracts(), announcement["declared_supply_af"],
        announcement["shortage_tier"], agreement)
    lines = calc.lines_of(announcement["id"])
    for line in lines:
        new_alloc = allocations.get(line["contract_id"])
        if new_alloc is not None and line["allocated_af"] != new_alloc:
            line["allocated_af"] = new_alloc
            touch(line)
    calc.curtailment_cascade(lines)
    return success(agreement_view(agreement), 200)
