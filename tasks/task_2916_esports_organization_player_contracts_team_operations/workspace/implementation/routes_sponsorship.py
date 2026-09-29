"""Sponsorship deals and the deliverables placed across a roster (PRD section 3.7)."""

from flask import Blueprint

import calc
import db
import response
import serializers as ser
import validation as v
from auth import endpoint, require_org_owner, require_player_owner
from db import store
from errors import fail

bp = Blueprint("sponsorship", __name__)

CATEGORIES = ("ENERGY_DRINK", "PERIPHERALS", "APPAREL", "BETTING", "CRYPTO")
MINOR_FORBIDDEN_CATEGORIES = ("BETTING", "CRYPTO")
MINOR_NOT_PERMITTED_CATEGORIES = ("ENERGY_DRINK", "BETTING", "CRYPTO")
DEAL_STATES = ("DRAFT", "ACTIVE", "FULFILLED")
DELIVERABLE_TYPES = ("STREAM_SEGMENT", "SOCIAL_POST", "APPEARANCE", "VOD_FEATURE")
ASSIGNMENT_STATES = ("ASSIGNED", "SUBMITTED", "APPROVED", "REJECTED", "VOIDED")


# ======================================================================================
# deals
# ======================================================================================

@bp.post("/sponsorship-deals")
@endpoint(["SponsorshipManager"])
def create_deal():
    payload = v.body()
    raw_org = payload.get("organization_id")
    if isinstance(raw_org, str):
        require_org_owner(raw_org)

    organization_id = v.req_str(payload, "organization_id")
    sponsor_name = v.req_str(payload, "sponsor_name", 1, 120)
    category = v.req_enum(payload, "exclusivity_category", CATEGORIES)
    total_fee_cents = v.req_int(payload, "total_fee_cents", 0)
    required = v.req_int(payload, "deliverable_count_required", 1)
    starts_at = v.req_instant(payload, "starts_at")
    ends_at = v.req_instant(payload, "ends_at")
    if not ends_at > starts_at:
        fail("ERR_INVALID_REQUEST", "Field 'ends_at' must be after 'starts_at'.")

    organization = v.find_organization(organization_id)
    record = {
        "organization_id": organization["id"],
        "sponsor_name": sponsor_name,
        "exclusivity_category": category,
        "total_fee_cents": total_fee_cents,
        "deliverable_count_required": required,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "deal_status": "DRAFT",
        "minor_permitted": category not in MINOR_NOT_PERMITTED_CATEGORIES,
    }
    db.insert(store.deals, record)
    return response.object_response(ser.deal(record), 201)


@bp.get("/sponsorship-deals/<deal_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "SponsorshipManager"])
def read_deal(deal_id):
    record = v.find_deal(deal_id)
    require_org_owner(record["organization_id"])
    return response.object_response(ser.deal(record))


@bp.get("/sponsorship-deals")
@endpoint(["LeagueAdmin", "GeneralManager", "SponsorshipManager"])
def list_deals():
    limit, offset = response.pagination()
    organization_id = v.str_filter("organization_id")
    deal_status = v.enum_filter("deal_status", DEAL_STATES)
    category = v.enum_filter("exclusivity_category", CATEGORIES)
    records = list(store.deals.values())
    if organization_id is not None:
        records = [d for d in records if d["organization_id"] == organization_id]
    if deal_status is not None:
        records = [d for d in records if d["deal_status"] == deal_status]
    if category is not None:
        records = [d for d in records if d["exclusivity_category"] == category]
    return response.paginated(db.in_creation_order(records), ser.deal, limit, offset)


@bp.get("/organizations/<organization_id>/sponsorship-deals")
@endpoint(["LeagueAdmin", "GeneralManager", "SponsorshipManager"])
def list_organization_deals(organization_id):
    organization = v.find_organization(organization_id)
    require_org_owner(organization["id"])
    limit, offset = response.pagination()
    deal_status = v.enum_filter("deal_status", DEAL_STATES)
    records = [d for d in store.deals.values()
               if d["organization_id"] == organization["id"]]
    if deal_status is not None:
        records = [d for d in records if d["deal_status"] == deal_status]
    return response.paginated(db.in_creation_order(records), ser.deal, limit, offset)


@bp.post("/sponsorship-deals/<deal_id>/activate")
@endpoint(["SponsorshipManager"])
def activate_deal(deal_id):
    record = v.find_deal(deal_id)
    require_org_owner(record["organization_id"])
    if record["deal_status"] != "DRAFT":
        fail("ERR_DEAL_NOT_ACTIVE")
    if calc.exclusivity_conflict_on_activation(record):
        fail("ERR_EXCLUSIVITY_CONFLICT")
    record["deal_status"] = "ACTIVE"
    db.touch(record)
    return response.object_response(ser.deal(record))


# ======================================================================================
# deliverable placement
# ======================================================================================

@bp.post("/sponsorship-deals/<deal_id>/deliverables")
@endpoint(["SponsorshipManager"])
def place_deliverable(deal_id):
    deal = v.find_deal(deal_id)
    require_org_owner(deal["organization_id"])
    payload = v.body()
    contract_id = v.req_str(payload, "contract_id")
    deliverable_type = v.req_enum(payload, "deliverable_type", DELIVERABLE_TYPES)
    due_at = v.req_instant(payload, "due_at")
    expected_version = v.req_int(payload, "expected_deal_version")

    # ---- band 6 ----------------------------------------------------------------
    contract = v.find_contract(contract_id)

    # ---- band 7 ----------------------------------------------------------------
    if expected_version != deal["version"]:
        fail("ERR_DEAL_VERSION_STALE")

    # ---- band 8 ----------------------------------------------------------------
    if deal["deal_status"] != "ACTIVE":
        fail("ERR_DEAL_NOT_ACTIVE")
    if contract["contract_status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE")

    # ---- band 9, in the §2.6 internal order ------------------------------------
    player = store.players.get(contract["player_id"])
    organization = store.organizations.get(deal["organization_id"])
    minor = player is not None and calc.is_minor(player, organization)
    if player is not None and calc.guardian_consent_status(player, organization) == "REQUIRED":
        fail("ERR_GUARDIAN_CONSENT_REQUIRED")
    if minor and deal["exclusivity_category"] in MINOR_FORBIDDEN_CATEGORIES:
        # No guardian can waive this one.
        fail("ERR_MINOR_CATEGORY_FORBIDDEN")
    if contract["obligation_status"] == "BREACH":
        fail("ERR_OBLIGATION_BREACH_BLOCKS_ASSIGNMENT")

    # ---- band 10 ---------------------------------------------------------------
    if not (deal["starts_at"] <= due_at < deal["ends_at"]):
        fail("ERR_DELIVERABLE_DUE_OUTSIDE_DEAL")

    # ---- band 11 ---------------------------------------------------------------
    if not calc.deal_assigned_count(deal) < deal["deliverable_count_required"]:
        fail("ERR_DELIVERABLE_QUOTA_EXCEEDED")

    # ---- band 12 ---------------------------------------------------------------
    if calc.exclusivity_conflict(deal, contract["id"]):
        fail("ERR_EXCLUSIVITY_CONFLICT")

    record = {
        # PRD section 2.10 -- nested creation takes the parent key from the PATH.
        "sponsorship_deal_id": deal["id"],
        "contract_id": contract["id"],
        "deliverable_type": deliverable_type,
        "due_at": due_at,
        "fee_share_cents": calc.per_item_fee_cents(deal),
        "assignment_status": "ASSIGNED",
        "rejection_count": 0,
        "submission_note": None,
        "review_note": None,
    }
    db.insert(store.assignments, record)
    # The deal's own version advances, which invalidates every other client's token.
    db.touch(deal)
    return response.object_response(ser.assignment(record), 201)


@bp.get("/sponsorship-deals/<deal_id>/deliverables")
@endpoint(["LeagueAdmin", "GeneralManager", "SponsorshipManager"])
def list_deal_deliverables(deal_id):
    deal = v.find_deal(deal_id)
    require_org_owner(deal["organization_id"])
    limit, offset = response.pagination()
    status = v.enum_filter("assignment_status", ASSIGNMENT_STATES)
    records = calc.assignments_of_deal(deal["id"])
    if status is not None:
        records = [a for a in records if a["assignment_status"] == status]
    return response.paginated(db.in_creation_order(records), ser.assignment, limit, offset)


# ======================================================================================
# assignments
# ======================================================================================

def _assignment_owners(record):
    contract = store.contracts.get(record["contract_id"])
    deal = store.deals.get(record["sponsorship_deal_id"])
    org_ids = []
    player_ids = []
    if deal is not None:
        org_ids.append(deal["organization_id"])
    if contract is not None:
        org_ids.append(contract["organization_id"])
        player_ids.append(contract["player_id"])
    require_org_owner(*org_ids)
    require_player_owner(*player_ids)
    return contract, deal


@bp.get("/deliverable-assignments/<assignment_id>")
@endpoint(["GeneralManager", "PlayerAgent", "SponsorshipManager"])
def read_assignment(assignment_id):
    record = v.find_assignment(assignment_id)
    _assignment_owners(record)
    return response.object_response(ser.assignment(record))


@bp.get("/deliverable-assignments")
@endpoint(["GeneralManager", "PlayerAgent", "SponsorshipManager"])
def list_assignments():
    limit, offset = response.pagination()
    deal_id = v.str_filter("sponsorship_deal_id")
    contract_id = v.str_filter("contract_id")
    status = v.enum_filter("assignment_status", ASSIGNMENT_STATES)
    records = list(store.assignments.values())
    if deal_id is not None:
        records = [a for a in records if a["sponsorship_deal_id"] == deal_id]
    if contract_id is not None:
        records = [a for a in records if a["contract_id"] == contract_id]
    if status is not None:
        records = [a for a in records if a["assignment_status"] == status]
    return response.paginated(db.in_creation_order(records), ser.assignment, limit, offset)


@bp.post("/deliverable-assignments/<assignment_id>/submit")
@endpoint(["PlayerAgent"])
def submit_assignment(assignment_id):
    record = v.find_assignment(assignment_id)
    contract, _deal = _assignment_owners(record)
    payload = v.body()
    submission_note = v.free_text(payload, "submission_note")
    if contract is None or contract["contract_status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if record["assignment_status"] not in ("ASSIGNED", "REJECTED"):
        fail("ERR_ASSIGNMENT_NOT_SUBMITTED")
    if submission_note is not None:
        record["submission_note"] = submission_note
    record["assignment_status"] = "SUBMITTED"
    db.touch(record)
    return response.object_response(ser.assignment(record))


@bp.post("/deliverable-assignments/<assignment_id>/review")
@endpoint(["SponsorshipManager"])
def review_assignment(assignment_id):
    record = v.find_assignment(assignment_id)
    _contract, deal = _assignment_owners(record)
    payload = v.body()
    decision = v.req_enum(payload, "decision", ("APPROVE", "REJECT"))
    review_note = v.free_text(payload, "review_note")
    if record["assignment_status"] != "SUBMITTED":
        fail("ERR_ASSIGNMENT_NOT_SUBMITTED")

    if review_note is not None:
        record["review_note"] = review_note
    if decision == "REJECT":
        record["assignment_status"] = "REJECTED"
        record["rejection_count"] = record["rejection_count"] + 1
        db.touch(record)
        return response.object_response(ser.assignment(record))

    record["assignment_status"] = "APPROVED"
    db.touch(record)
    if deal is not None:
        # Fulfilment bubbles up from the child counts rather than being set directly.
        if deal["deal_status"] == "ACTIVE" and calc.deal_is_fulfilled(deal):
            deal["deal_status"] = "FULFILLED"
        db.touch(deal)
    return response.object_response(ser.assignment(record))
