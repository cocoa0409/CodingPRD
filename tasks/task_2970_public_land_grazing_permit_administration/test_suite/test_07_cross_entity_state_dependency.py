"""Gates that live on a third entity: an allotment's posture, an appeal's stay and a
permittee's ledger each decide what a wholly conforming request may do."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    assert_pct,
    make_adjudicator_headers,
    make_officer_headers,
    make_permittee_headers,
    make_specialist_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_use_record,
    allotment_with_pasture,
    create_aoi,
    create_closure_order,
    create_pasture,
    create_permit,
    decide_appeal,
    filed_appeal,
    finalized_assessment,
    get_allotment,
    get_aoi,
    get_appeal,
    get_bill,
    get_decision,
    get_permit,
    get_permittee,
    get_use_record,
    issue_permit,
    issued_aoi_setup,
    lift_closure_order,
    permittee_with_base_property,
    signed_decision,
)
from test_helpers.test_users import JUDGE_1, OFFICER_1, SPECIALIST_1


def _successors(permit_id):
    items, _meta = validate_paginated(api_client.list_permits(
        make_officer_headers(), {"predecessor_permit_id": permit_id, "limit": 100}))
    return items


def _posture_setup():
    """A RESTRICTED allotment — 0.30 drought order in force — carrying a DRAFT 2026
    instruction of 200 AUMs with one 62.00-AUM rotation window already scheduled on it."""
    land = allotment_with_pasture(total_permitted_aums=1200, pasture_aum_capacity=300,
                                  required_pasture_rotation_count=2, acres=36000)
    north = land["pasture"]
    south = create_pasture(land["allotment"]["id"], pasture_aum_capacity=300, sequence_order=2)
    holder = permittee_with_base_property(carrying_capacity_aums=400)
    permit = issue_permit(create_permit(
        land["allotment"]["id"], holder["permittee"]["id"], holder["base_property"]["id"],
        requested_aums=300)["id"])
    drought = create_closure_order(
        land["allotment"]["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.30,
        effective_start_date="2026-08-10", effective_end_date="2026-09-30",
        justification="Drought reduction of thirty percent for the remainder of the season.")
    aoi = create_aoi(permit["id"], grazing_year=2026, authorized_aums=200,
                     season_start_date="2026-01-01", season_end_date="2026-12-31")
    record = add_use_record(aoi["id"], north["id"], planned_head_count=60,
                            livestock_kind="CATTLE", planned_entry_date="2026-08-15",
                            planned_exit_date="2026-09-15")
    return {"allotment": land["allotment"], "north": north, "south": south,
            "permittee": holder["permittee"], "permit": permit, "drought": drought,
            "aoi": aoi, "record": record}


def _south_leg(setup):
    return f.use_record_payload(setup["south"]["id"], planned_entry_date="2026-08-15",
                                planned_exit_date="2026-09-15", planned_head_count=60,
                                livestock_kind="CATTLE")


def _wildfire_order(allotment_id):
    """A total closure whose request omits reduction_pct altogether."""
    return get_success_data(api_client.create_closure_order(
        {"allotment_id": allotment_id, "order_type": "WILDFIRE_CLOSURE",
         "effective_start_date": "2026-10-08", "effective_end_date": "2026-12-31",
         "justification": "Burned area closed to livestock pending seeding establishment."},
        make_officer_headers()), 201)


def test_scheduling_a_rotation_window_is_decided_by_the_grandparent_allotments_posture():
    """The identical rotation window that was scheduled while the allotment was merely
    RESTRICTED is refused with ERR_ALLOTMENT_CLOSED once a wildfire closure drives the
    allotment to CLOSED — the instruction is still DRAFT and 62.00 AUMs is nowhere near the
    300-AUM pasture, so only the third entity's status changed.

    PRD 2.6: "When the governing allotment's `allotment_status` is `CLOSED`, no permit may be
    issued, renewed or transferred onto it, no operating instruction may be created or issued for
    any of its permits, and no use record may be scheduled on such an instruction."
    PRD 2.6: "A `RESTRICTED` allotment still permits all six — only its reduced capacity applies."
    PRD 3.10: "A `WILDFIRE_CLOSURE` order and a `FULL_CLOSURE` order are total: `reduction_pct`
    should be omitted, or sent as exactly 1.0, and the server records 1.0 in either case."
    PRD 3.10: "It is exactly 1.0 when any closure order on the allotment in `order_status`
    `ACTIVE` has `order_type` `WILDFIRE_CLOSURE` or `FULL_CLOSURE`."

    Design: Difficulty/cross_entity_state_dependency/aoi_creation_gated_by_allotment_posture
    """
    setup = _posture_setup()
    restricted = get_allotment(setup["allotment"]["id"])
    assert restricted["allotment_status"] == "RESTRICTED"
    assert restricted["effective_capacity_aums"] == 840
    assert setup["aoi"]["aoi_status"] == "DRAFT"
    assert_aums(setup["record"]["planned_aums"], 62.00)

    order = _wildfire_order(setup["allotment"]["id"])
    assert order["order_status"] == "ACTIVE"
    assert_pct(order["reduction_pct"], 1.0)

    closed = get_allotment(setup["allotment"]["id"])
    assert closed["allotment_status"] == "CLOSED"
    assert_pct(closed["stocking_adjustment_pct"], 1.0)
    assert closed["effective_capacity_aums"] == 0, "no cap at 0.9 for a total closure"

    validate_error(
        api_client.create_use_record(setup["aoi"]["id"], _south_leg(setup),
                                     make_specialist_headers()),
        ApiErrorId.ERR_ALLOTMENT_CLOSED, 409)
    validate_error(
        api_client.issue_aoi(setup["aoi"]["id"], make_officer_headers()),
        ApiErrorId.ERR_ALLOTMENT_CLOSED, 409)

    untouched = get_aoi(setup["aoi"]["id"])
    assert untouched["aoi_status"] == "DRAFT", (
        "the refusal is not an instruction-state failure; DRAFT is what scheduling requires")
    assert untouched["distinct_pasture_count"] == 1
    surviving = get_use_record(setup["record"]["id"])
    assert surviving["record_status"] == "SCHEDULED", (
        "the closure does not retroactively delete a scheduled window")
    assert_aums(surviving["planned_aums"], 62.00)


def test_lifting_the_closure_returns_the_allotment_to_restricted_and_reopens_scheduling():
    """Lifting the wildfire order recomputes over the surviving 0.30 drought source, so the
    allotment lands on RESTRICTED rather than OPEN, capacity returns to 840, and the very same
    62.00-AUM rotation window is then accepted.

    PRD 3.10: "The order moves `ACTIVE → LIFTED` and the identical five-hop cascade re-runs over
    the **remaining** sources, so a lift recomputes rather than subtracts: lifting a 0.40 drought
    order while a 0.30 effective stocking adjustment survives leaves the allotment at 0.30 and
    `RESTRICTED`, not at 0.0 and `OPEN`."
    PRD 3.10: "The `allotment_status` becomes `CLOSED` when `stocking_adjustment_pct` is exactly
    1.0, `RESTRICTED` when it is strictly between 0 and 1, and `OPEN` when it is exactly 0."

    Design: Difficulty/cross_entity_state_dependency/aoi_creation_gated_by_allotment_posture
    """
    setup = _posture_setup()
    order = _wildfire_order(setup["allotment"]["id"])
    assert get_allotment(setup["allotment"]["id"])["allotment_status"] == "CLOSED"

    lifted = lift_closure_order(order["id"])
    assert lifted["order_status"] == "LIFTED"

    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["allotment_status"] == "RESTRICTED", "the drought order still stands"
    assert_pct(allotment["stocking_adjustment_pct"], 0.30)
    assert allotment["effective_capacity_aums"] == 840
    assert allotment["open_aums"] == 840, "the instruction is still DRAFT and commits nothing"

    accepted = get_success_data(api_client.create_use_record(
        setup["aoi"]["id"], _south_leg(setup), make_specialist_headers()), 201)
    assert_aums(accepted["planned_aums"], 62.00)
    assert accepted["record_status"] == "SCHEDULED"
    assert get_aoi(setup["aoi"]["id"])["distinct_pasture_count"] == 2


def _stay_setup():
    """A FINAL 0.20 STOCKING_ADJUSTMENT decision frozen by an appeal filed with a stay."""
    setup = issued_aoi_setup(authorized_aums=300, total_permitted_aums=1200,
                             pasture_aum_capacity=300, carrying_capacity_aums=400,
                             requested_aums=300, allotment_overrides={"acres": 24000})
    assessment = finalized_assessment(setup["allotment"]["id"], assessment_year=2026)
    decision = signed_decision(
        setup["allotment"]["id"], signer_user_id=OFFICER_1,
        decision_type="STOCKING_ADJUSTMENT", assessment_id=assessment["id"],
        adjustment_pct=0.20, nepa_level="EA")
    assert decision["decision_status"] == "FINAL"
    appeal = filed_appeal(decision["id"], setup["permittee"]["id"], stay_requested=True)
    setup["assessment"] = assessment
    setup["decision"] = decision
    setup["appeal"] = appeal
    return setup


def test_a_filed_stay_freezes_a_decision_that_is_otherwise_ready_to_take_effect():
    """The appeal is only FILED, yet its stay moves the signed decision to STAYED and the
    deciding officer's own make-effective call is refused with ERR_DECISION_STAYED; the
    allotment shows the cascade never ran.

    PRD 3.9: "When `stay_requested` is true **and** the decision is in `decision_status` `FINAL`
    — signed but not yet in effect — the petition is granted at filing: `stay_granted` becomes
    true and the decision moves `FINAL → STAYED`, which freezes it completely."
    PRD 3.9: "No allotment, permit, instruction or bill field is written by the stay; it is a pure
    hold."
    PRD 3.8: "The decision must be in `decision_status` `FINAL`, else
    `ERR_DECISION_STATE_INVALID`, and it must not be frozen by an appeal — a decision in
    `decision_status` `STAYED` yields `ERR_DECISION_STAYED`."

    Design: Difficulty/cross_entity_state_dependency/decision_effectiveness_gated_by_appeal_stay
    """
    setup = _stay_setup()
    appeal = get_appeal(setup["appeal"]["id"])
    assert appeal["appeal_status"] == "FILED"
    assert appeal["stay_granted"] is True
    assert appeal["remand_count"] == 0
    assert get_decision(setup["decision"]["id"])["decision_status"] == "STAYED"

    validate_error(
        api_client.make_decision_effective(setup["decision"]["id"],
                                           make_officer_headers(OFFICER_1)),
        ApiErrorId.ERR_DECISION_STAYED, 409)

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.0)
    assert allotment["allotment_status"] == "OPEN"
    assert allotment["effective_capacity_aums"] == 1200
    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 300, "the held-back cascade"
    assert get_bill(setup["preliminary_bill"]["id"])["bill_status"] == "ISSUED"


def test_a_standing_stay_also_blocks_a_fresh_decision_of_the_same_type():
    """While the stay stands the allotment may not receive another STOCKING_ADJUSTMENT
    document at all: authoring one against a current allotment version is refused with
    ERR_DECISION_STAYED rather than a concurrency or state error.

    PRD 2.6: "**Appeal stay gate** — `ERR_DECISION_STAYED`, HTTP 409, on two operations: making a
    decision effective, and authoring a new decision."
    PRD 2.6: "A decision whose `decision_status` is `STAYED` may not be made effective, and while
    that stay stands the allotment it targets may not receive a further decision of the same
    `decision_type`."

    Design: Difficulty/cross_entity_state_dependency/decision_effectiveness_gated_by_appeal_stay
    """
    setup = _stay_setup()
    version = get_allotment(setup["allotment"]["id"])["version"]

    validate_error(
        api_client.create_decision(
            f.decision_payload(setup["allotment"]["id"], version,
                               decision_type="STOCKING_ADJUSTMENT",
                               assessment_id=setup["assessment"]["id"],
                               adjustment_pct=0.10, nepa_level="EA"),
            make_specialist_headers(SPECIALIST_1)),
        ApiErrorId.ERR_DECISION_STAYED, 409)

    assert get_decision(setup["decision"]["id"])["decision_status"] == "STAYED"
    assert_pct(get_allotment(setup["allotment"]["id"])["stocking_adjustment_pct"], 0.0)


def test_affirming_the_appeal_releases_the_stayed_decision_into_effect():
    """The stay is released by the adjudicator, not by the officer: docketing and then
    AFFIRMING the case clears stay_granted, carries the decision STAYED -> EFFECTIVE and runs
    the cascade it was holding back, so capacity falls to 960 and the instruction to 240 AUMs.

    PRD 3.9: "`AFFIRM` moves the case to `appeal_status` `AFFIRMED`, sets `stay_granted` to
    false, and — if the appealed decision is `STAYED` — releases it into effect, running its
    full cascade at that moment."
    PRD 2.6: "The stay is released only when the appeal case leaves `FILED` and `UNDER_REVIEW`."
    PRD 2.9: "The first line is **effective capacity**: `effective_capacity_aums` is the
    allotment's `total_permitted_aums` multiplied by one minus its `stocking_adjustment_pct`,
    with the product floored to a whole AUM."

    Design: Difficulty/cross_entity_state_dependency/decision_effectiveness_gated_by_appeal_stay
    """
    setup = _stay_setup()
    docketed = get_success_data(api_client.docket_appeal(
        setup["appeal"]["id"], make_adjudicator_headers(JUDGE_1)))
    assert docketed["appeal_status"] == "UNDER_REVIEW"
    assert docketed["stay_granted"] is True, "docketing does not revisit the stay"

    affirmed = decide_appeal(setup["appeal"]["id"], "AFFIRM", adjudicator_user_id=JUDGE_1)
    assert affirmed["appeal_status"] == "AFFIRMED"
    assert affirmed["stay_granted"] is False

    decision = get_decision(setup["decision"]["id"])
    assert decision["decision_status"] == "EFFECTIVE"
    assert_pct(decision["pre_decision_adjustment_pct"], 0.0)

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.20)
    assert allotment["allotment_status"] == "RESTRICTED"
    assert allotment["effective_capacity_aums"] == 960
    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 240


def _debt_setup():
    """An ISSUED 300-AUM permit whose holder owes 54,100 cents on an unpaid preliminary bill."""
    setup = issued_aoi_setup(authorized_aums=300, total_permitted_aums=1200,
                             pasture_aum_capacity=300, carrying_capacity_aums=400,
                             requested_aums=300, allotment_overrides={"acres": 24000})
    assert setup["preliminary_bill"]["total_amount_cents"] == 54100
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 54100
    return setup


def _renewal(setup):
    return api_client.renew_permit(
        setup["permit"]["id"],
        f.renew_payload(setup["base_property"]["id"], requested_aums=300,
                        term_start_date="2031-01-01", term_end_date="2035-12-31"),
        make_officer_headers())


def test_renewal_is_refused_while_the_holding_permittee_owes_money():
    """The renewal request is impeccable in itself — the term follows the predecessor's and the
    base property qualifies 400 AUMs against 300 — but the permittee's live 54,100-cent balance
    answers with ERR_OUTSTANDING_BALANCE and HTTP 402, and no successor is born.

    PRD 2.6: "**Debt gate** — `ERR_OUTSTANDING_BALANCE`, HTTP 402, on permit issuance, permit
    renewal, permit transfer and operating-instruction creation."
    PRD 2.6: "None of those four may proceed while the permittee who would hold the permit has an
    `outstanding_balance_cents` greater than zero, evaluated against the live permittee aggregate."
    PRD 3.4: "The permittee's `outstanding_balance_cents` must be at most zero, the named base
    property's `qualified_aums` must be at least the permit's `permitted_aums`, and the
    allotment's `allotment_status` must be `OPEN` or `RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/permit_renewal_gated_by_permittee_debt
    """
    setup = _debt_setup()
    permittee = get_permittee(setup["permittee"]["id"])
    assert permittee["permittee_status"] == "IN_GOOD_STANDING", (
        "the bill is ISSUED and not yet past its due date")

    validate_error(_renewal(setup), ApiErrorId.ERR_OUTSTANDING_BALANCE, 402)

    assert get_permit(setup["permit"]["id"])["permit_status"] == "ISSUED", (
        "the refused renewal did not expire the predecessor")
    assert _successors(setup["permit"]["id"]) == []
    assert get_bill(setup["preliminary_bill"]["id"])["bill_status"] == "ISSUED"


def test_the_same_renewal_succeeds_the_moment_the_debt_is_cleared():
    """Paying the 54,100-cent bill in full brings the ledger to zero, and the identical renewal
    request then expires the predecessor and mints the successor — proving the gate reads the
    permittee's live aggregate rather than anything on the permit.

    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."
    PRD 3.4: "On success the predecessor moves to `permit_status` `EXPIRED`, and a successor
    permit is created carrying `predecessor_permit_id` pointing at the predecessor,
    `permit_status` `ISSUED`, `account_status` `CURRENT`, the same `permittee_id`,
    `allotment_id`, `base_property_id`, `permitted_aums` and `livestock_kind` as the
    predecessor, and the supplied term dates."

    Design: Difficulty/cross_entity_state_dependency/permit_renewal_gated_by_permittee_debt
    """
    setup = _debt_setup()

    paid = get_success_data(api_client.record_payment(
        setup["preliminary_bill"]["id"], f.payment_payload(54100),
        make_permittee_headers(setup["permittee"]["id"])), 201)
    assert paid["bill_status"] == "PAID"
    assert paid["amount_paid_cents"] == 54100
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 0

    get_success_data(_renewal(setup))

    assert get_permit(setup["permit"]["id"])["permit_status"] == "EXPIRED"
    successors = _successors(setup["permit"]["id"])
    assert len(successors) == 1
    successor = successors[0]
    assert successor["predecessor_permit_id"] == setup["permit"]["id"]
    assert successor["permit_status"] == "ISSUED"
    assert successor["account_status"] == "CURRENT"
    assert successor["permitted_aums"] == 300
    assert successor["permittee_id"] == setup["permittee"]["id"]
    assert successor["livestock_kind"] == setup["permit"]["livestock_kind"]
