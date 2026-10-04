"""Partnership agreements: activation gates, funding, amendments (PRD §3.3)."""
from test_helpers import (
    DIRECTOR,
    FUNDER,
    ApiErrorId,
    api_client,
    assert_partnership_agreement,
    base_world,
    get_agreement,
    make_agreement,
    make_delivery,
    make_district,
    make_partner,
    make_program,
    make_school,
    make_area_office,
    make_volunteer,
    plan_delivery,
    partnership_agreement_payload,
    record_funding,
    transition_agreement,
    transition_district,
    validate_error,
    validate_success,
)


def test_funding_floor_exactly_met_activates_below_rejected(api):
    """PRD §3.3: "The floor is a base of 75,000 cents plus 25,000 cents for
    each session the program requires — a four-session program floors at
    175,000 cents, a five-session program at 200,000 cents — and a pledge
    exactly equal to the floor passes."

    Design: Corner/calculations/corner_funding_floor_exactly_met_activates_below_rejected
    """
    world = base_world(session_count=5, program_code="JA-ECO8", min_students=10)
    agr_a = make_agreement(
        world["school"]["id"], world["program"]["id"], world["partner"]["id"],
        funding_pledged_cents=200000,
    )
    transition_agreement(agr_a["id"], "PROPOSE")
    agr_b = make_agreement(
        world["school"]["id"], world["program"]["id"], world["partner"]["id"],
        funding_pledged_cents=199999,
    )
    transition_agreement(agr_b["id"], "PROPOSE")

    ok = api_client.transition_partnership_agreement(agr_a["id"], {"action": "ACTIVATE"}, DIRECTOR)
    data = validate_success(ok, 200)
    assert data["status"] == "ACTIVE", "pledge == floor 200000 must pass (inclusive boundary)"

    resp = api_client.transition_partnership_agreement(agr_b["id"], {"action": "ACTIVATE"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_FUNDING_BELOW_FLOOR)
    assert get_agreement(agr_b["id"])["status"] == "PROPOSED"


def test_record_funding_exact_pledge_then_overflow_rejected(api):
    """PRD §3.3: "the running total may never exceed the pledge: if
    `funding_received_cents` plus the new `amount_cents` would pass
    `funding_pledged_cents`, the record is rejected with
    `ERR_FUNDING_EXCEEDS_PLEDGE`."

    Design: Corner/errors/corner_record_funding_exact_pledge_then_overflow_rejected
    """
    world = base_world()  # 4-session program: pledge defaults to the 175000 floor
    agr_id = world["agreement"]["id"]
    funded = record_funding(agr_id, 175000)
    assert funded["funding_received_cents"] == 175000
    assert funded["funding_pledged_cents"] == 175000

    resp = api_client.transition_partnership_agreement(
        agr_id, {"action": "RECORD_FUNDING", "amount_cents": 1}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_FUNDING_EXCEEDS_PLEDGE)
    assert get_agreement(agr_id)["funding_received_cents"] == 175000


def test_agreement_activate_with_prospect_sponsor_rejected(api):
    """PRD §3.3: "the sponsor partner must currently be ACTIVE, else
    `ERR_SPONSOR_NOT_ACTIVE`"

    Design: Corner/validations/corner_agreement_activate_with_prospect_sponsor_rejected
    """
    office = make_area_office()
    district = make_district(office["id"], activate=True)
    school = make_school(district["id"])
    sponsor = make_partner(activate=False)  # left PROSPECT
    program = make_program()
    agreement = make_agreement(school["id"], program["id"], sponsor["id"])
    transition_agreement(agreement["id"], "PROPOSE")

    resp = api_client.transition_partnership_agreement(agreement["id"], {"action": "ACTIVATE"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_SPONSOR_NOT_ACTIVE)
    assert get_agreement(agreement["id"])["status"] == "PROPOSED"


def test_agreement_complete_with_live_delivery_rejected(api):
    """PRD §3.3: "COMPLETE moves ACTIVE to COMPLETED only when every delivery
    of the agreement is COMPLETED or CANCELLED with at least one COMPLETED,
    else `ERR_INVALID_STATE`"

    Design: Corner/state_machines/corner_agreement_complete_with_live_delivery_rejected
    """
    world = base_world()
    delivery = make_delivery(world["agreement"]["id"], world["volunteer"]["id"])
    plan_delivery(delivery["id"])

    resp = api_client.transition_partnership_agreement(
        world["agreement"]["id"], {"action": "COMPLETE"}, DIRECTOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_agreement(world["agreement"]["id"])["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: district relationship gates activation (two tests)
# ---------------------------------------------------------------------------

def _world_with_district_prospect():
    """Territory whose district is left PROSPECT; sponsor ACTIVE; pledge at floor."""
    office = make_area_office()
    district = make_district(office["id"], activate=False)
    school = make_school(district["id"])
    partner = make_partner(activate=True)
    make_volunteer(partner["id"], credentialed=True)
    program = make_program(code="JA-ECO6", session_count=5, min_students=10)
    agreement = make_agreement(
        school["id"], program["id"], partner["id"], funding_pledged_cents=200000
    )
    transition_agreement(agreement["id"], "PROPOSE")
    return {"district": district, "agreement": agreement}


def test_agreement_activation_blocked_under_prospect_and_at_risk_district(api):
    """PRD §3.3: "Three checks fire in the validation ladder's order: the
    school's district must currently be PARTNER, else `ERR_DISTRICT_NOT_PARTNER`"
    PRD §3.1: "because agreement activation requires a PARTNER district (§3.3),
    no agreement at its schools can be activated while the risk flag stands."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_gated_by_district_relationship
    """
    w = _world_with_district_prospect()
    agr_id = w["agreement"]["id"]

    resp1 = api_client.transition_partnership_agreement(agr_id, {"action": "ACTIVATE"}, DIRECTOR)
    validate_error(resp1, ApiErrorId.ERR_DISTRICT_NOT_PARTNER)
    assert get_agreement(agr_id)["status"] == "PROPOSED"

    # PARTNER -> AT_RISK: the gate closes again
    transition_district(w["district"]["id"], "ACTIVATE")
    transition_district(w["district"]["id"], "FLAG_RISK")
    resp2 = api_client.transition_partnership_agreement(agr_id, {"action": "ACTIVATE"}, DIRECTOR)
    validate_error(resp2, ApiErrorId.ERR_DISTRICT_NOT_PARTNER)
    assert get_agreement(agr_id)["status"] == "PROPOSED"


def test_agreement_activation_succeeds_once_district_restored_to_partner(api):
    """PRD §3.3: "ACTIVATE moves PROPOSED to ACTIVE and is the most heavily
    gated transition on the agreement. Three checks fire in the validation
    ladder's order: the school's district must currently be PARTNER, else
    `ERR_DISTRICT_NOT_PARTNER`; the sponsor partner must currently be ACTIVE,
    else `ERR_SPONSOR_NOT_ACTIVE`; and the pledge must meet the program's
    funding floor, else `ERR_FUNDING_BELOW_FLOOR`."

    Design: Difficulty/cross_entity_state_dependency/agreement_activation_gated_by_district_relationship
    """
    w = _world_with_district_prospect()
    agr_id = w["agreement"]["id"]
    transition_district(w["district"]["id"], "ACTIVATE")
    transition_district(w["district"]["id"], "FLAG_RISK")
    transition_district(w["district"]["id"], "RESTORE")

    resp = api_client.transition_partnership_agreement(agr_id, {"action": "ACTIVATE"}, DIRECTOR)
    data = validate_success(resp, 200)
    assert_partnership_agreement(data)
    assert data["status"] == "ACTIVE", "with district PARTNER the gate opens"


# ---------------------------------------------------------------------------
# Difficulty: state error masks funding floor error (two tests)
# ---------------------------------------------------------------------------

def _draft_agreement_below_floor():
    """Agreement on a 5-session program (floor 200000) pledged 100000, DRAFT."""
    world = base_world(session_count=5, program_code="JA-ECO4", min_students=10)
    agreement = make_agreement(
        world["school"]["id"], world["program"]["id"], world["partner"]["id"],
        funding_pledged_cents=100000,
    )
    return agreement


def test_activate_from_draft_reports_state_error_not_funding_floor(api):
    """PRD §2.7: "Every request is validated against an ordered ladder, and the
    first failing tier reports its error; later tiers are never consulted once
    an earlier one fails."
    PRD §2.7: "State legality: the target entity is in a state from which the
    requested transition or action is defined, including terminal-state
    lockdown, else `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/activate_from_draft_state_error_masks_funding_floor_error
    """
    agreement = _draft_agreement_below_floor()
    resp = api_client.transition_partnership_agreement(agreement["id"], {"action": "ACTIVATE"}, DIRECTOR)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert err["error_id"] != ApiErrorId.ERR_FUNDING_BELOW_FLOOR.value
    assert get_agreement(agreement["id"])["status"] == "DRAFT"


def test_same_agreement_reports_funding_floor_once_state_tier_passes(api):
    """PRD §2.7: "Fiscal rules: the funding floor at activation and amendment
    ratification, and the pledge ceiling on funding records and amendments,
    reporting `ERR_FUNDING_BELOW_FLOOR` or `ERR_FUNDING_EXCEEDS_PLEDGE`."
    PRD §3.3: "PROPOSE moves the agreement from DRAFT to PROPOSED."

    Design: Difficulty/priority_pair_validation_conflict/activate_from_draft_state_error_masks_funding_floor_error
    """
    agreement = _draft_agreement_below_floor()
    proposed = transition_agreement(agreement["id"], "PROPOSE")
    assert proposed["status"] == "PROPOSED"
    resp = api_client.transition_partnership_agreement(agreement["id"], {"action": "ACTIVATE"}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_FUNDING_BELOW_FLOOR)
    assert get_agreement(agreement["id"])["status"] == "PROPOSED"


# ---------------------------------------------------------------------------
# Difficulty: amendment ratify/reject cycle (two tests)
# ---------------------------------------------------------------------------

def _amendment_world():
    """ACTIVE agreement on a 5-session program (pledge 200000); a second
    4-session program exists as an amendment target."""
    world = base_world(session_count=5, program_code="JA-ECO2", min_students=10, pledge_cents=200000)
    world["program_b"] = make_program(code="JA-BIZ2", session_count=4)
    return world


def test_amendment_ratify_applies_pending_funding(api):
    """PRD §3.3: "PROPOSE_AMENDMENT moves ACTIVE to AMENDMENT_PENDING and may
    carry `new_program_catalog_id`, `new_funding_pledged_cents`, or both — at
    least one must be present, else `ERR_VALIDATION` — storing them in
    `pending_program_catalog_id` and `pending_funding_pledged_cents`, with an
    absent value leaving its pending field null."
    PRD §3.3: "Ratification copies the pending values into
    `program_catalog_id` and `funding_pledged_cents`, clears both pending
    fields to null, and leaves existing deliveries on their snapshotted
    program."

    Design: Difficulty/non_linear_state_machine/agreement_amendment_ratify_and_reject_cycles
    """
    world = _amendment_world()
    agr_id = world["agreement"]["id"]
    pending = transition_agreement(agr_id, "PROPOSE_AMENDMENT", new_funding_pledged_cents=250000)
    assert pending["status"] == "AMENDMENT_PENDING"
    assert pending["pending_funding_pledged_cents"] == 250000
    assert pending["pending_program_catalog_id"] is None

    ratified = transition_agreement(agr_id, "RATIFY_AMENDMENT")
    assert ratified["status"] == "ACTIVE"
    assert ratified["funding_pledged_cents"] == 250000
    assert ratified["pending_funding_pledged_cents"] is None
    assert ratified["pending_program_catalog_id"] is None
    assert ratified["program_catalog_id"] == world["program"]["id"]


def test_amendment_reject_discards_pending_program(api):
    """PRD §3.3: "REJECT_AMENDMENT also returns to ACTIVE, clearing the pending
    fields while leaving the program and the pledge untouched."

    Design: Difficulty/non_linear_state_machine/agreement_amendment_ratify_and_reject_cycles
    """
    world = _amendment_world()
    agr_id = world["agreement"]["id"]
    pending = transition_agreement(
        agr_id, "PROPOSE_AMENDMENT", new_program_catalog_id=world["program_b"]["id"]
    )
    assert pending["status"] == "AMENDMENT_PENDING"
    assert pending["pending_program_catalog_id"] == world["program_b"]["id"]

    rejected = transition_agreement(agr_id, "REJECT_AMENDMENT")
    assert rejected["status"] == "ACTIVE"
    assert rejected["program_catalog_id"] == world["program"]["id"], "rejected change is discarded"
    assert rejected["funding_pledged_cents"] == 200000
    assert rejected["pending_program_catalog_id"] is None
    assert rejected["pending_funding_pledged_cents"] is None
