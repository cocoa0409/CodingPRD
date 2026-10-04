"""Cross-entity state dependencies: one record's state gates another's action (PRD 3.4, 3.6)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, fund_program, occupy_new_home, setup_repair_advance,
    get_program, TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
UW = TEST_USERS["underwriter_headers"]


def _unenrolled_program_scenario():
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "28 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "29 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    sc["program"] = get_program(bp["id"])
    return sc


def test_repair_approval_is_refused_while_the_program_is_pending(api):
    """PRD section 3.4: "the program must be in a state where repairs make sense, that is,
    its advance axis must be `FUNDING` or `FUNDED`. An approval attempted while the
    program's advance axis has closed is refused with `ERR_ADVANCE_WINDOW_CLOSED`"

    Design: Difficulty/cross_entity_state_dependency/repair_advance_requires_program_funded
    """
    reset_clock()
    sc = _unenrolled_program_scenario()
    assert sc["program"]["advance_status"] == "PENDING", "the program was never funded"
    repair = setup_repair_advance(sc["program"]["id"], sc["departing"]["id"],
                                  approved_amount_cents=3_000_000)

    res = api.approve_repair_advance(repair["id"], UW)
    validate_error(res, ApiErrorId.ERR_ADVANCE_WINDOW_CLOSED.value, expected_status=409)


def test_repair_advance_stays_requested_after_a_refused_approval(api):
    """PRD section 3.4: "It opens `REQUESTED`."

    PRD section 3.4: "An approval attempted while the program's advance axis has closed is
    refused with `ERR_ADVANCE_WINDOW_CLOSED`"

    Design: Difficulty/cross_entity_state_dependency/repair_advance_requires_program_funded
    """
    reset_clock()
    sc = _unenrolled_program_scenario()
    repair = setup_repair_advance(sc["program"]["id"], sc["departing"]["id"],
                                  approved_amount_cents=3_000_000)
    assert repair["status"] == "REQUESTED"
    api.approve_repair_advance(repair["id"], UW)
    after = validate_success(api.get_repair_advance(repair["id"], COORD), 200)
    assert after["status"] == "REQUESTED", "the refused approval left the record untouched"


def test_repair_approval_succeeds_once_the_program_is_funding(api):
    """PRD section 3.4: "Approval is an underwriter action and carries three further
    conditions — the approved amount may not exceed 5000000 cents, the linked property must
    be of kind `DEPARTING`, and the program must be in a state where repairs make sense,
    that is, its advance axis must be `FUNDING` or `FUNDED`."

    Design: Difficulty/cross_entity_state_dependency/repair_advance_requires_program_funded
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "28 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "29 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, _loan = fund_program(bp["id"])
    assert get_program(program["id"])["advance_status"] == "FUNDING"

    repair = setup_repair_advance(program["id"], sc["departing"]["id"],
                                  approved_amount_cents=3_000_000)
    approved = validate_success(api.approve_repair_advance(repair["id"], UW), 200)
    assert approved["status"] == "APPROVED"


def _occupying_new_scenario(api):
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "30 Departing Way", "appraised_value_cents": 50_000_000,
                   "mortgage_payoff_cents": 20_000_000, "condition_grade": "B"},
        new={"address": "31 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    program, loan = fund_program(bp["id"])
    # The household has moved in but the old home has not been marketed yet.
    occupy_new_home(program["id"], sc["homeowner"]["id"])
    sc["program"] = get_program(program["id"])
    sc["loan"] = loan
    return sc


def test_issuing_a_backup_offer_before_marketing_is_a_state_error(api):
    """PRD section 3.6: "The offer also may not be issued until the household has actually
    moved: the linked program's `occupancy_status` must be `DEPARTING_LISTED` at the moment
    of issue, so the guarantee is issued only once the old home is genuinely on the market."

    Design: Difficulty/cross_entity_state_dependency/backup_offer_issue_requires_marketing
    """
    reset_clock()
    sc = _occupying_new_scenario(api)
    assert sc["program"]["occupancy_status"] == "OCCUPYING_NEW"
    offer = validate_success(api.create_backup_offer(
        {"departing_property_id": sc["departing"]["id"], "bridge_program_id": sc["program"]["id"],
         "offer_price_cents": 44_000_000, "window_days": 30,
         "window_start": "2026-09-01T00:00:00Z"}, COORD), 201)
    assert offer["status"] == "DRAFT"

    res = api.issue_backup_offer(offer["id"], COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    after = validate_success(api.get_backup_offer(offer["id"], COORD), 200)
    assert after["status"] == "DRAFT", "the refused issue left the offer as drafted"


def test_issuing_succeeds_once_the_old_home_is_on_the_market(api):
    """PRD section 3.6: "Issuing the offer starts the clock on the guarantee, and two things
    must be true. The offer must still be `DRAFT`, and the logical clock must have reached
    the offer's `window_start`"

    PRD section 3.6: "the linked program's `occupancy_status` must be `DEPARTING_LISTED` at
    the moment of issue, so the guarantee is issued only once the old home is genuinely on
    the market."

    Design: Difficulty/cross_entity_state_dependency/backup_offer_issue_requires_marketing
    """
    reset_clock()
    sc = _occupying_new_scenario(api)
    offer = validate_success(api.create_backup_offer(
        {"departing_property_id": sc["departing"]["id"], "bridge_program_id": sc["program"]["id"],
         "offer_price_cents": 44_000_000, "window_days": 30,
         "window_start": "2026-09-01T00:00:00Z"}, COORD), 201)

    from test_helpers import complete_repairs, draft_listing
    complete_repairs(sc["departing"]["id"], visits=3)
    listing = draft_listing(sc["departing"]["id"], sc["program"]["id"])
    validate_success(api.go_live_listing(listing["id"], COORD), 200)
    assert get_program(sc["program"]["id"])["occupancy_status"] == "DEPARTING_LISTED"

    issued = validate_success(api.issue_backup_offer(offer["id"], COORD), 200)
    assert issued["status"] == "ISSUED"