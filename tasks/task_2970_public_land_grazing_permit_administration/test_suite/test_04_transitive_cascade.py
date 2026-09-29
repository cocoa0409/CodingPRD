"""Deep cascades: each hop is caused by the previous hop's output, forwards from a
closure order and backwards from an appeal reversal."""
from test_helpers import assert_ledger_conserved, assert_pct
from test_helpers.fixtures import (
    create_aoi,
    create_closure_order,
    create_permit,
    issue_permit,
    permittee_with_base_property,
    effective_stocking_adjustment,
    decide_appeal,
    docketed_appeal,
    get_allotment,
    get_aoi,
    get_bill,
    get_decision,
    get_permit,
    get_permittee,
    issued_aoi_setup,
    list_bills,
)


def _cascade_setup(**overrides):
    """A 1200-AUM allotment with an ISSUED 300-AUM permit and an ISSUED 2026 instruction
    whose 54,100-cent preliminary bill is still unpaid."""
    setup = issued_aoi_setup(
        authorized_aums=300, total_permitted_aums=1200, pasture_aum_capacity=300,
        carrying_capacity_aums=400, requested_aums=300, **overrides)
    assert setup["preliminary_bill"]["total_amount_cents"] == 54100
    assert setup["allotment"]["allocated_aums"] == 300
    assert setup["allotment"]["open_aums"] == 900
    return setup


def _revised_bill(aoi_id):
    """The single ISSUED REVISED_USE bill of an instruction."""
    revised = [b for b in list_bills(aoi_id=aoi_id, bill_type="REVISED_USE")
               if b["bill_status"] == "ISSUED"]
    assert len(revised) == 1, "expected exactly one live revised bill, got %d" % len(revised)
    return revised[0]


def test_drought_order_propagates_through_capacity_authorization_bill_and_balance():
    """A 0.30 drought order sets stocking_adjustment_pct to 0.3000, which floors
    effective_capacity_aums to 840, which re-authorizes the instruction from its 300-AUM
    snapshot to 210, which supersedes the unpaid 54,100-cent bill with a 36,120-cent
    REVISED_USE bill, which drops the permittee's balance to 36,120 cents.

    PRD 3.10: "Otherwise it is the **maximum** over two families of contributors: the
    `reduction_pct` of every closure order on the allotment in `order_status` `ACTIVE`, and the
    `adjustment_pct` of every permit decision on the allotment with `decision_type`
    `STOCKING_ADJUSTMENT` and `decision_status` `EFFECTIVE`."
    PRD 2.9: "The first line is **effective capacity**: `effective_capacity_aums` is the
    allotment's `total_permitted_aums` multiplied by one minus its `stocking_adjustment_pct`,
    with the product floored to a whole AUM."
    PRD 3.10: "For every operating instruction of the allotment whose `grazing_year` equals the
    allotment's `current_grazing_year` and whose `aoi_status` is `ISSUED` or `USE_REPORTED`, the
    `authorized_aums` becomes the instruction's own `authorized_aums_at_issue` snapshot
    multiplied by one minus `stocking_adjustment_pct`, floored to a whole AUM, and
    `billable_aums` becomes the new `authorized_aums` less `nonuse_aums`."
    PRD 3.10: "Each re-authorized instruction's outstanding use bill is superseded at the new
    `billable_aums` by a bill of `bill_type` `REVISED_USE` carrying `superseded_bill_id`,
    provided the old bill's `amount_paid_cents` is exactly 0; a bill that has already received
    money is left standing and the difference is issued as an `ADJUSTMENT_CREDIT`, or an
    `ADJUSTMENT_DEBIT` were the movement upward, exactly as §3.6 prescribes."
    PRD 3.10: "Hop five closes the ledger: each affected permittee's `outstanding_balance_cents`
    and `permittee_status` are recomputed and each of their permits' `account_status` is
    re-derived."

    Design: Difficulty/transitive_cascade/drought_closure_five_hop_cascade
    """
    setup = _cascade_setup()

    order = create_closure_order(
        setup["allotment"]["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.30,
        effective_start_date="2026-08-10", effective_end_date="2026-09-30",
        justification="Severe drought; forage production 40 percent of average.")
    assert order["order_status"] == "ACTIVE"

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.30)
    assert allotment["allotment_status"] == "RESTRICTED"
    assert allotment["effective_capacity_aums"] == 840, "floor(1200 x 0.70)"

    aoi = get_aoi(setup["aoi"]["id"])
    assert aoi["authorized_aums_at_issue"] == 300, "the snapshot is never rewritten"
    assert aoi["authorized_aums"] == 210, "floor(300 x 0.70)"
    assert aoi["billable_aums"] == 210
    assert aoi["aoi_status"] == "ISSUED"

    assert allotment["allocated_aums"] == 210
    assert allotment["open_aums"] == 630
    assert_ledger_conserved(allotment)

    assert get_bill(setup["preliminary_bill"]["id"])["bill_status"] == "VOIDED"
    revised = _revised_bill(setup["aoi"]["id"])
    assert revised["billed_aums"] == 210
    assert revised["base_amount_cents"] == 36120
    assert revised["admin_fee_cents"] == 0, "36,120 cents of base is below the first tier"
    assert revised["total_amount_cents"] == 36120
    assert revised["superseded_bill_id"] == setup["preliminary_bill"]["id"]

    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 36120
    permit = get_permit(setup["permit"]["id"])
    assert permit["account_status"] == "CURRENT"
    assert permit["permit_status"] == "ISSUED", (
        "the authorization dimension is untouched by a capacity movement")


def test_cascade_hop_three_reaches_only_current_year_issued_instructions():
    """The re-authorization hop is scoped: a DRAFT instruction on a neighbouring permit of the
    same allotment keeps its 200 authorized AUMs while the ISSUED instruction is cut from its
    300-AUM snapshot to 210, and the allotment's ledger still balances.

    PRD 3.10: "Instructions in `aoi_status` `DRAFT`, `BILLED`, `CLOSED` or `VOIDED` are **not**
    re-authorized, and instructions of any other `grazing_year` are untouched."
    PRD 3.10: "The cascade is a **single pass**: hop three's changes to instruction
    authorizations never feed back into hop one, so the fixed point is reached in one traversal
    and an implementation that iterates to convergence will produce different, wrong figures."

    Design: Difficulty/transitive_cascade/drought_closure_five_hop_cascade
    """
    setup = _cascade_setup()
    neighbour = permittee_with_base_property(carrying_capacity_aums=400)
    neighbour_permit = issue_permit(create_permit(
        setup["allotment"]["id"], neighbour["permittee"]["id"],
        neighbour["base_property"]["id"], requested_aums=300)["id"])
    draft = create_aoi(neighbour_permit["id"], grazing_year=2026, authorized_aums=200,
                       season_start_date="2026-01-01", season_end_date="2026-12-31")
    assert draft["aoi_status"] == "DRAFT"

    create_closure_order(
        setup["allotment"]["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.30,
        effective_start_date="2026-08-10", effective_end_date="2026-09-30",
        justification="Severe drought; forage production 40 percent of average.")

    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 210
    untouched = get_aoi(draft["id"])
    assert untouched["authorized_aums"] == 200, (
        "a DRAFT instruction is outside hop three"
    )
    assert untouched["authorized_aums_at_issue"] == 200
    assert untouched["billable_aums"] == 200

    allotment = get_allotment(setup["allotment"]["id"])
    assert allotment["effective_capacity_aums"] == 840
    assert allotment["allocated_aums"] == 210, (
        "a single pass; the 210 is not re-reduced to 147 by a second traversal")
    assert_ledger_conserved(allotment)


def test_appeal_reversal_restores_capacity_authorization_and_bill_from_the_snapshot():
    """Reversing the appeal vacates the effective 0.20 stocking adjustment: the allotment's
    stocking_adjustment_pct is restored verbatim from pre_decision_adjustment_pct 0.0000,
    capacity returns to 1200, the instruction returns to 300 AUMs from its own snapshot, and
    the 41,280-cent reduced bill is superseded at 54,100 cents with the 2,500-cent
    administrative tier back in force, leaving no drift anywhere.

    PRD 3.8: "When an adjudicator reverses an appeal against a decision in `decision_status`
    `EFFECTIVE`, the decision moves `EFFECTIVE → VACATED` and the four-hop restoration runs: for
    a `STOCKING_ADJUSTMENT`, the allotment's `stocking_adjustment_pct` is restored verbatim from
    `pre_decision_adjustment_pct` and `effective_capacity_aums` recomputed; then, because
    capacity moved, every current-year instruction in `aoi_status` `ISSUED` or `USE_REPORTED` has
    its `authorized_aums` recomputed from its own snapshot; then, because `billable_aums` moved,
    each such instruction's unpaid use bill is superseded by a `REVISED_USE` bill; then each
    affected permittee's `outstanding_balance_cents` is recomputed and each affected permit's
    `account_status` re-evaluated."
    PRD 3.9: "`REVERSE` moves the case to `REVERSED`, sets `stay_granted` to false, and vacates
    the appealed decision: an `EFFECTIVE` decision runs the four-hop restoration of §3.8, while a
    `STAYED` decision is simply vacated with no cascade."

    Design: Difficulty/transitive_cascade/appeal_reversal_restoration_cascade
    """
    setup = _cascade_setup()
    decision = effective_stocking_adjustment(setup["allotment"]["id"], 0.20, nepa_level="EA")
    assert decision["decision_status"] == "EFFECTIVE"
    assert_pct(decision["pre_decision_adjustment_pct"], 0.0)

    reduced_aoi = get_aoi(setup["aoi"]["id"])
    assert reduced_aoi["authorized_aums"] == 240, "floor(300 x 0.80)"
    reduced_bill = _revised_bill(setup["aoi"]["id"])
    assert reduced_bill["total_amount_cents"] == 41280

    appeal = docketed_appeal(decision["id"], setup["permittee"]["id"], stay_requested=False)
    assert appeal["stay_granted"] is False, "a stay cannot un-ring an effective decision"

    reversed_appeal = decide_appeal(appeal["id"], "REVERSE")
    assert reversed_appeal["appeal_status"] == "REVERSED"
    assert reversed_appeal["stay_granted"] is False
    assert get_decision(decision["id"])["decision_status"] == "VACATED"

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.0)
    assert allotment["allotment_status"] == "OPEN"
    assert allotment["effective_capacity_aums"] == 1200
    assert allotment["allocated_aums"] == 300
    assert allotment["open_aums"] == 900
    assert_ledger_conserved(allotment)

    restored_aoi = get_aoi(setup["aoi"]["id"])
    assert restored_aoi["authorized_aums"] == 300
    assert restored_aoi["billable_aums"] == 300
    assert restored_aoi["authorized_aums_at_issue"] == 300

    assert get_bill(reduced_bill["id"])["bill_status"] == "VOIDED"
    restored_bill = _revised_bill(setup["aoi"]["id"])
    assert restored_bill["id"] != reduced_bill["id"]
    assert restored_bill["billed_aums"] == 300
    assert restored_bill["base_amount_cents"] == 51600
    assert restored_bill["admin_fee_cents"] == 2500
    assert restored_bill["total_amount_cents"] == 54100
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 54100


def test_vacatur_restores_the_snapshot_rather_than_zeroing_the_adjustment():
    """With a 0.10 drought order already active, the effective 0.20 decision snapshots
    pre_decision_adjustment_pct 0.1000 before its own cascade, so its reversal restores the
    allotment to 0.1000 and RESTRICTED — capacity 1080, instruction 270 AUMs, bill 46,440
    cents — rather than to 0 and OPEN.

    PRD 3.8: "Two fields are stamped **before** any cascade runs: `effective_date` takes the
    logical-clock date in `YYYY-MM-DD` form, and `pre_decision_adjustment_pct` takes a snapshot
    of the allotment's `stocking_adjustment_pct` **as it stands before the adjustment is
    applied**."
    PRD 3.8: "Taking that snapshot first is what makes a later vacatur exactly reversible;
    taking it afterwards would record the new figure and make restoration a no-op."
    PRD 3.10: "Contributors are **never summed**: a 0.40 drought reduction standing beside a 0.30
    effective stocking adjustment yields 0.40, not 0.70."

    Design: Difficulty/transitive_cascade/appeal_reversal_restoration_cascade
    """
    setup = _cascade_setup()
    create_closure_order(
        setup["allotment"]["id"], order_type="DROUGHT_REDUCTION", reduction_pct=0.10,
        effective_start_date="2026-08-10", effective_end_date="2026-09-30",
        justification="Early-season drought indicators justify a modest reduction.")
    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 270, "floor(300 x 0.90)"

    decision = effective_stocking_adjustment(setup["allotment"]["id"], 0.20, nepa_level="EA")
    assert_pct(decision["pre_decision_adjustment_pct"], 0.10)
    assert_pct(get_allotment(setup["allotment"]["id"])["stocking_adjustment_pct"], 0.20)
    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 240

    appeal = docketed_appeal(decision["id"], setup["permittee"]["id"], stay_requested=False)
    decide_appeal(appeal["id"], "REVERSE")

    allotment = get_allotment(setup["allotment"]["id"])
    assert_pct(allotment["stocking_adjustment_pct"], 0.10)
    assert allotment["allotment_status"] == "RESTRICTED", "the drought order still stands"
    assert allotment["effective_capacity_aums"] == 1080
    assert_ledger_conserved(allotment)

    assert get_aoi(setup["aoi"]["id"])["authorized_aums"] == 270
    restored_bill = _revised_bill(setup["aoi"]["id"])
    assert restored_bill["billed_aums"] == 270
    assert restored_bill["base_amount_cents"] == 46440
    assert restored_bill["admin_fee_cents"] == 0
    assert restored_bill["total_amount_cents"] == 46440
    assert get_permittee(setup["permittee"]["id"])["outstanding_balance_cents"] == 46440
