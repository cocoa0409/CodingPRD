"""Owner change orders and the compensating cancellation of a purchase commitment.

Covers PRD §3.9 — substantiating documented escalation to the owner: the five pinned
steps, the administrative fee tier keyed on the gross, the claim cap, the substantiation
gates and the terminality of an owner disposition — together with PRD §3.5's cancellation
path and the contingency conservation invariant that unwinds with it.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_change_order_request,
    assert_instant_equals,
    assert_purchase_commitment,
    assert_substantiation_arithmetic,
    build_buyout_scenario,
    build_delivered_scenario,
    build_released_scenario,
    countersign_commitment,
    draft_clause,
    execute_clause,
    issue_commitment,
    make_buyout_manager_headers,
    move_posture,
    open_project,
    propose_clause,
    publish_readings,
    read_commitment,
    read_package,
    read_project,
    read_quote,
    register_package,
    register_supplier,
    set_clock,
    submit_quote,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.factories import (
    cancel_commitment_payload,
    create_change_order_request_payload,
    disposition_change_order_payload,
)

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]
PROJECT_EXECUTIVE = TEST_USERS["project_executive_headers"]
OWNER_REP = TEST_USERS["owner_rep_headers"]

# Two distinct BuyoutManager operators — segregation of duties is by X-User-ID (§2.1).
PREPARER = make_buyout_manager_headers("buyer-anita")
SUBMITTER = make_buyout_manager_headers("buyer-diego")

# The steel scenario used by several instances: 1150000.00 committed against a
# 2026-07 baseline of 310.00 escalating to 322.00 in 2026-08, with a 2.0 deadband,
# an 8.0 cap and a 40.0 contractor share, recognised at a clock of 2026-08-05.
EARLY_AUGUST = "2026-08-05T00:00:00.000Z"
STEEL_FINAL_ESCALATION = 12909.90
STEEL_ADMIN_FEE = 451.85
STEEL_SUBSTANTIATED = 13361.75

CLAIM_NARRATIVE = "Documented mill index escalation per executed clause"


def _setup_copper_delivered_commitment() -> dict:
    """A copper buyout of 875000.00 delivered at a clock of 2026-10-05.

    The clause caps at 10.0 with a 2.0 deadband and a 30.0 contractor share against a
    2026-07 baseline of 200.00; the 2026-10 reading of 220.00 is the only other
    published period, so the final escalation lands on exactly 49000.00.
    """
    project = open_project()
    package = register_package(
        project["id"],
        scope_code="ELEC-FEEDER-01",
        description="Medium voltage feeder conductor package",
        commodity_index_code="PPI_COPPER_WIRE",
        estimated_cost=900000.00,
        required_onsite_date="2027-05-01T00:00:00.000Z",
        fabrication_duration_days=60,
        delivery_transit_days=25,
        submittal_review_days=21,
    )
    supplier = register_supplier(legal_name="Continental Wire and Cable")
    quote = submit_quote(
        package["id"],
        supplier["id"],
        base_price=875000.00,
        received_at="2026-08-01T00:00:00.000Z",
        price_hold_days=45,
    )
    publish_readings("PPI_COPPER_WIRE", (("2026-07", 200.00), ("2026-10", 220.00)))
    agreement = draft_clause(
        quote["id"],
        index_code="PPI_COPPER_WIRE",
        baseline_index_period="2026-07",
        cap_pct=10.0,
        contractor_share_pct=30.0,
        deadband_pct=2.0,
        price_hold_through="2026-09-15T00:00:00.000Z",
    )
    propose_clause(agreement["id"])
    agreement = execute_clause(agreement["id"])
    commitment = issue_commitment(
        project["id"],
        quote["id"],
        po_number="PO-2996-0007",
        escalation_agreement_id=agreement["id"],
        is_early_buyout=False,
    )
    countersign_commitment(commitment["id"])
    set_clock("2026-09-10T00:00:00.000Z")
    move_posture(commitment["id"], "RELEASED_FOR_FAB")
    move_posture(commitment["id"], "FABRICATING")
    set_clock("2026-10-05T00:00:00.000Z")
    commitment = move_posture(commitment["id"], "DELIVERED")
    return {
        "project": project,
        "package": package,
        "supplier": supplier,
        "quote": quote,
        "agreement": agreement,
        "commitment": commitment,
    }


def _setup_delivered_steel_commitment() -> dict:
    """A steel buyout carried to DELIVERED with a FINAL escalation of 12909.90."""
    return build_delivered_scenario(release_at=EARLY_AUGUST, deliver_at=EARLY_AUGUST)


def _setup_two_delivered_commitments_straddling_the_tier_boundary() -> dict:
    """One project, two delivered POs whose gross escalations bracket 10000.00.

    Both clauses read a 2026-07 baseline of 300.00 rising to 312.00 in 2026-08 with a
    2.0 deadband, an 8.0 cap and a 50.0 contractor share, which leaves 1.0 percent to
    the owner: the 1000000.00 steel PO accrues exactly 10000.00 and the 950000.00
    copper PO accrues 9500.00.
    """
    project = open_project()
    supplier = register_supplier()
    publish_readings("PPI_STEEL_MILL", (("2026-07", 300.00), ("2026-08", 312.00)))
    publish_readings("PPI_COPPER_WIRE", (("2026-07", 300.00), ("2026-08", 312.00)))
    package_at = register_package(
        project["id"],
        scope_code="STRUCT-STEEL-01",
        description="Structural steel frame package",
        commodity_index_code="PPI_STEEL_MILL",
        estimated_cost=1000000.00,
    )
    package_below = register_package(
        project["id"],
        scope_code="ELEC-FEEDER-01",
        description="Electrical feeder conductor package",
        commodity_index_code="PPI_COPPER_WIRE",
        estimated_cost=950000.00,
    )
    quote_at = submit_quote(package_at["id"], supplier["id"], base_price=1000000.00)
    quote_below = submit_quote(package_below["id"], supplier["id"], base_price=950000.00)
    clause_terms = dict(
        baseline_index_period="2026-07",
        cap_pct=8.0,
        contractor_share_pct=50.0,
        deadband_pct=2.0,
        price_hold_through="2026-09-15T00:00:00.000Z",
    )
    agreement_at = draft_clause(quote_at["id"], index_code="PPI_STEEL_MILL", **clause_terms)
    agreement_below = draft_clause(
        quote_below["id"], index_code="PPI_COPPER_WIRE", **clause_terms
    )
    for agreement_id in (agreement_at["id"], agreement_below["id"]):
        propose_clause(agreement_id)
        execute_clause(agreement_id)
    commitment_at = issue_commitment(
        project["id"],
        quote_at["id"],
        po_number="PO-2996-0001",
        escalation_agreement_id=agreement_at["id"],
        is_early_buyout=False,
    )
    countersign_commitment(commitment_at["id"])
    commitment_below = issue_commitment(
        project["id"],
        quote_below["id"],
        po_number="PO-2996-0002",
        escalation_agreement_id=agreement_below["id"],
        is_early_buyout=False,
    )
    countersign_commitment(commitment_below["id"])
    set_clock(EARLY_AUGUST)
    for commitment_id in (commitment_at["id"], commitment_below["id"]):
        move_posture(commitment_id, "RELEASED_FOR_FAB")
        move_posture(commitment_id, "FABRICATING")
        move_posture(commitment_id, "DELIVERED")
    return {
        "project": project,
        "commitment_at": read_commitment(commitment_at["id"]),
        "commitment_below": read_commitment(commitment_below["id"]),
    }


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula /
#   change_order_admin_fee_tier_keyed_on_gross_not_running_total
# ---------------------------------------------------------------------------

def test_change_order_fee_tier_is_keyed_on_the_gross_not_the_running_total():
    """A gross of 49000.00 takes the 3.5 percent tier and substantiates 50715.00.

    PRD §3.9: "the administrative fee tier is selected **from that gross amount**: 5.0
    percent when the gross is below 10000.00, 3.5 percent when it is at least 10000.00
    but below 50000.00, and 2.0 percent when it is 50000.00 or more".
    PRD §3.9: "The fee tier is keyed on the step-one gross amount and **never** on the
    running total produced by step four".
    PRD §3.9: "A gross of 49000.00 with a claim of 52000.00 selects the 3.5 percent
    tier, yields a fee of 1715.00, and substantiates 50715.00."

    Design: Difficulty/combinatorial_formula/change_order_admin_fee_tier_keyed_on_gross_not_running_total
    """
    scenario = _setup_copper_delivered_commitment()
    assert scenario["commitment"]["escalation_variant"] == "FINAL"
    assert scenario["commitment"]["escalation_accrued"] == 49000.00

    response = api_client.create_change_order_request(
        create_change_order_request_payload(
            purchase_commitment_id=scenario["commitment"]["id"],
            claimed_amount=52000.00,
            narrative=CLAIM_NARRATIVE,
        ),
        PREPARER,
    )
    change_order = validate_success(response, 201)

    assert_change_order_request(change_order)
    assert_substantiation_arithmetic(change_order)
    assert change_order["gross_documented_amount"] == 49000.00
    assert change_order["admin_fee_pct"] == 3.5
    assert change_order["admin_fee_amount"] == 1715.00
    assert change_order["substantiated_amount"] == 50715.00
    # Keying the tier on the running total would drop it into the 2.0 percent tier.
    assert change_order["substantiated_amount"] != 49980.00
    assert change_order["status"] == "PREPARED"
    assert change_order["prepared_by_user_id"] == "buyer-anita"
    assert change_order["submitted_by_user_id"] is None


def test_change_order_claim_cap_binds_below_the_running_total():
    """The same 49000.00 gross with a claim of 45000.00 substantiates 45000.00.

    PRD §3.9: "`substantiated_amount` is the lesser of that running total and the
    `claimed_amount`, rounded half up to 2 decimal places — the owner is never asked for
    more than the contractor claimed, and a `claimed_amount` below the running total
    silently caps the claim rather than raising an error."
    PRD §3.9: "The same gross of 49000.00 with a claim of only 45000.00 substantiates
    45000.00, because the claim cap binds."

    Design: Difficulty/combinatorial_formula/change_order_admin_fee_tier_keyed_on_gross_not_running_total
    """
    scenario = _setup_copper_delivered_commitment()

    response = api_client.create_change_order_request(
        create_change_order_request_payload(
            purchase_commitment_id=scenario["commitment"]["id"],
            claimed_amount=45000.00,
            narrative=CLAIM_NARRATIVE,
        ),
        PREPARER,
    )
    change_order = validate_success(response, 201)

    assert_change_order_request(change_order)
    assert_substantiation_arithmetic(change_order)
    # The cap binds on the fifth step only; the first four steps are unchanged.
    assert change_order["gross_documented_amount"] == 49000.00
    assert change_order["admin_fee_pct"] == 3.5
    assert change_order["admin_fee_amount"] == 1715.00
    assert change_order["claimed_amount"] == 45000.00
    assert change_order["substantiated_amount"] == 45000.00
    assert change_order["status"] == "PREPARED"


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant /
#   cancel_returns_the_escalation_contingency_ledger_to_zero
# ---------------------------------------------------------------------------

def test_release_charges_the_escalation_contingency_ledger():
    """The forward hop: releasing for fabrication books 32941.98 against the contingency.

    PRD §3.6: "Releasing for fabrication ... is where escalation is first recognized";
    "Release sets `escalation_variant` to `PROVISIONAL` and records the selected
    reading's period in `escalation_index_period`."
    PRD §3.1: "`escalation_contingency_committed` is the sum of `escalation_accrued`
    over that same `COMMITTED`-or-`CLOSED` set, and `escalation_contingency_remaining`
    is the budget less that figure, rounded half up to 2 decimal places."
    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose
    `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's
    `committed_base_cost` plus its `escalation_accrued`".

    Design: Difficulty/compensating_invariant/cancel_returns_the_escalation_contingency_ledger_to_zero
    """
    scenario = build_released_scenario()
    commitment = read_commitment(scenario["commitment"]["id"])

    assert_purchase_commitment(commitment)
    assert commitment["commitment_status"] == "COMMITTED"
    assert commitment["delivery_posture"] == "RELEASED_FOR_FAB"
    assert commitment["escalation_variant"] == "PROVISIONAL"
    assert commitment["escalation_index_period"] == "2026-09"
    assert commitment["escalation_accrued"] == 32941.98
    assert_instant_equals(
        commitment["released_for_fab_at"], "2026-09-10T00:00:00.000Z", "released_for_fab_at"
    )

    project = read_project(scenario["project"]["id"])
    assert project["escalation_contingency_committed"] == 32941.98
    assert project["escalation_contingency_remaining"] == 467058.02
    assert project["committed_total_cost"] == 1182941.98
    assert project["estimated_total_cost"] == 1200000.00
    assert project["buyout_variance"] == 17058.02
    assert project["bought_out_variance"] == 17058.02


def test_cancel_returns_the_escalation_contingency_ledger_to_zero():
    """The compensating hop: cancelling the released PO restores the ledger to the cent.

    PRD §3.5: "When it is permitted, the compensation is complete: `escalation_accrued`
    returns to 0, `escalation_variant` returns to `NONE`, `escalation_index_period`
    returns to null, `released_for_fab_at` returns to null, and `delivery_posture`
    resets to `SCHEDULED`."
    PRD §3.5: "The project's `version` increments by 1, and its
    `escalation_contingency_committed` and `escalation_contingency_remaining` return to
    exactly the values they carried before the release — the contingency conservation
    invariant, which must hold to the cent."
    PRD §3.5: "The quote comes back to the market as `OPEN` if the clock is still
    strictly inside its hold"; "the package leaves `BOUGHT_OUT` for `SOURCING` when it
    still has at least one `OPEN` quote after the cancellation".

    Design: Difficulty/compensating_invariant/cancel_returns_the_escalation_contingency_ledger_to_zero
    """
    scenario = build_released_scenario()
    released_project = read_project(scenario["project"]["id"])
    assert released_project["escalation_contingency_committed"] == 32941.98

    response = api_client.cancel_purchase_commitment(
        scenario["commitment"]["id"], cancel_commitment_payload(), PROJECT_EXECUTIVE
    )
    commitment = validate_success(response)

    assert commitment["commitment_status"] == "CANCELLED"
    assert commitment["escalation_accrued"] == 0.00
    assert commitment["escalation_variant"] == "NONE"
    assert commitment["escalation_index_period"] is None
    assert commitment["released_for_fab_at"] is None
    assert commitment["delivery_posture"] == "SCHEDULED"
    assert commitment["cancellation_reason"]

    # The clock stands at 2026-09-10, strictly inside the hold that ends 2026-09-15.
    assert read_quote(scenario["quote"]["id"])["status"] == "OPEN"
    package = read_package(scenario["package"]["id"])
    assert package["status"] == "SOURCING"
    assert package["open_quote_count"] == 1

    project = read_project(scenario["project"]["id"])
    assert project["escalation_contingency_committed"] == 0.00
    assert project["escalation_contingency_remaining"] == 500000.00
    assert project["committed_total_cost"] == 0.00
    assert project["buyout_variance"] == 1200000.00
    assert project["bought_out_variance"] == 0.00
    assert project["version"] > released_project["version"]


# ---------------------------------------------------------------------------
# Queue B: state_machines / terminal_state_lockdown_cancel_on_a_closed_commitment_rejected
# ---------------------------------------------------------------------------

def test_cancel_on_a_closed_commitment_is_rejected():
    """A delivered PO is CLOSED and terminal, so cancellation is refused outright.

    PRD §3.5: "`CLOSED`, `CANCELLED` and `VOIDED` are all terminal on the contractual
    axis."
    PRD §2.9: "a commitment's countersign or cancel must match its `commitment_status`
    ... (`ERR_INVALID_STATE_TRANSITION`, 409)".
    PRD §3.6: "Accepting delivery ... close[s] the contractual axis by moving
    `commitment_status` from `COMMITTED` to `CLOSED`, and close[s] the scope package by
    moving it from `BOUGHT_OUT` to `CLOSED`."

    Design: Corner/state_machines/terminal_state_lockdown_cancel_on_a_closed_commitment_rejected
    """
    scenario = _setup_delivered_steel_commitment()
    commitment_id = scenario["commitment"]["id"]
    assert read_commitment(commitment_id)["commitment_status"] == "CLOSED"

    response = api_client.cancel_purchase_commitment(
        commitment_id, cancel_commitment_payload(), PROJECT_EXECUTIVE
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    # Nothing was unwound: the refusal left the closed row exactly as it stood.
    commitment = read_commitment(commitment_id)
    assert commitment["commitment_status"] == "CLOSED"
    assert commitment["delivery_posture"] == "DELIVERED"
    assert commitment["cancellation_reason"] is None
    assert commitment["escalation_variant"] == "FINAL"
    assert commitment["escalation_accrued"] == STEEL_FINAL_ESCALATION

    assert read_package(scenario["package"]["id"])["status"] == "CLOSED"
    project = read_project(scenario["project"]["id"])
    assert project["committed_total_cost"] == 1162909.90
    assert project["escalation_contingency_committed"] == STEEL_FINAL_ESCALATION
    assert project["escalation_contingency_remaining"] == 487090.10


# ---------------------------------------------------------------------------
# Queue B: state_machines / conditional_cascade_cancel_lands_the_package_in_sourcing_stalled
# ---------------------------------------------------------------------------

def test_cancel_lands_the_package_in_sourcing_stalled():
    """Cancelling once the hold has run out expires the quote and stalls the package.

    PRD §3.5: "The quote comes back to the market as `OPEN` if the clock is still
    strictly inside its hold and goes to `EXPIRED` if it is not."
    PRD §3.5: "the package leaves `BOUGHT_OUT` for `SOURCING` when it still has at least
    one `OPEN` quote after the cancellation, and for `SOURCING_STALLED` when it has
    none."
    PRD §3.5: "Cancelling a `COMMITTED` commitment is permitted **only** while
    `delivery_posture` is `SCHEDULED` or `RELEASED_FOR_FAB`".

    Design: Corner/state_machines/conditional_cascade_cancel_lands_the_package_in_sourcing_stalled
    """
    scenario = build_buyout_scenario()
    # The quote was CONVERTED by the countersignature, so advancing past its expiry
    # neither expires it nor lapses the executed clause — only the cancel does that.
    set_clock("2026-09-20T00:00:00.000Z")

    response = api_client.cancel_purchase_commitment(
        scenario["commitment"]["id"], cancel_commitment_payload(), PROJECT_EXECUTIVE
    )
    commitment = validate_success(response)

    assert commitment["commitment_status"] == "CANCELLED"
    assert commitment["delivery_posture"] == "SCHEDULED"
    assert commitment["escalation_accrued"] == 0.00
    assert commitment["escalation_variant"] == "NONE"

    assert read_quote(scenario["quote"]["id"])["status"] == "EXPIRED"
    package = read_package(scenario["package"]["id"])
    assert package["status"] == "SOURCING_STALLED"
    assert package["open_quote_count"] == 0
    # The executed clause is untouched by a cancellation.
    assert read_commitment(commitment["id"])["escalation_agreement_id"] == (
        scenario["agreement"]["id"]
    )

    project = read_project(scenario["project"]["id"])
    assert project["committed_total_cost"] == 0.00
    assert project["escalation_contingency_committed"] == 0.00


# ---------------------------------------------------------------------------
# Queue B: state_machines /
#   terminal_state_lockdown_second_disposition_on_an_owner_approved_change_order_rejected
# ---------------------------------------------------------------------------

def test_second_disposition_on_an_owner_approved_change_order_is_rejected():
    """OWNER_APPROVED is terminal, so a follow-up rejection is refused.

    PRD §3.9: "It is permitted only while the change order is `SUBMITTED`: a disposition
    attempted against one still `PREPARED`, or against one already `OWNER_APPROVED` or
    `OWNER_REJECTED`, is `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.9: "An approval feeds the project's `change_order_recovered_amount` on the
    next project read".
    PRD §3.9: "an approved change order does **not** reduce the project's
    `escalation_contingency_committed`."

    Design: Corner/state_machines/terminal_state_lockdown_second_disposition_on_an_owner_approved_change_order_rejected
    """
    scenario = _setup_delivered_steel_commitment()
    change_order = validate_success(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=scenario["commitment"]["id"],
                claimed_amount=20000.00,
                narrative=CLAIM_NARRATIVE,
            ),
            PREPARER,
        ),
        201,
    )
    validate_success(
        api_client.submit_change_order_request(change_order["id"], SUBMITTER)
    )
    approved = validate_success(
        api_client.disposition_change_order_request(
            change_order["id"], disposition_change_order_payload("APPROVED"), OWNER_REP
        )
    )
    assert approved["status"] == "OWNER_APPROVED"

    response = api_client.disposition_change_order_request(
        change_order["id"], disposition_change_order_payload("REJECTED"), OWNER_REP
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    final = validate_success(
        api_client.get_change_order_request(change_order["id"], OWNER_REP)
    )
    assert final["status"] == "OWNER_APPROVED"
    assert final["gross_documented_amount"] == STEEL_FINAL_ESCALATION
    assert final["admin_fee_pct"] == 3.5
    assert final["admin_fee_amount"] == STEEL_ADMIN_FEE
    assert final["substantiated_amount"] == STEEL_SUBSTANTIATED

    project = read_project(scenario["project"]["id"])
    assert project["change_order_recovered_amount"] == STEEL_SUBSTANTIATED
    # Owner recovery and contractor contingency are separate ledgers.
    assert project["escalation_contingency_committed"] == STEEL_FINAL_ESCALATION


# ---------------------------------------------------------------------------
# Queue B: calculations / tiered_pricing_fee_tier_flips_at_exactly_ten_thousand_gross
# ---------------------------------------------------------------------------

def test_fee_tier_flips_at_exactly_ten_thousand_gross():
    """A gross of exactly 10000.00 takes 3.5 percent while 9500.00 takes 5.0 percent.

    PRD §3.9: "the administrative fee tier is selected **from that gross amount**: 5.0
    percent when the gross is below 10000.00, 3.5 percent when it is at least 10000.00
    but below 50000.00, and 2.0 percent when it is 50000.00 or more; each tier boundary
    is an inclusive lower bound on the tier above it, and the selected percentage is
    persisted as `admin_fee_pct`."
    PRD §3.9: "`admin_fee_amount` is the gross amount multiplied by that percentage,
    divided by one hundred, and rounded half up to 2 decimal places."
    PRD §3.9: "a rejection leaves that figure exactly where it was" — neither claim is
    dispositioned, so `change_order_recovered_amount` stays 0.00.

    Design: Corner/calculations/tiered_pricing_fee_tier_flips_at_exactly_ten_thousand_gross
    """
    scenario = _setup_two_delivered_commitments_straddling_the_tier_boundary()
    assert scenario["commitment_at"]["escalation_accrued"] == 10000.00
    assert scenario["commitment_below"]["escalation_accrued"] == 9500.00

    at_boundary = validate_success(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=scenario["commitment_at"]["id"],
                claimed_amount=20000.00,
                narrative=CLAIM_NARRATIVE,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    below_boundary = validate_success(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=scenario["commitment_below"]["id"],
                claimed_amount=20000.00,
                narrative=CLAIM_NARRATIVE,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )

    assert_substantiation_arithmetic(at_boundary)
    assert at_boundary["gross_documented_amount"] == 10000.00
    assert at_boundary["admin_fee_pct"] == 3.5
    assert at_boundary["admin_fee_amount"] == 350.00
    assert at_boundary["substantiated_amount"] == 10350.00

    assert_substantiation_arithmetic(below_boundary)
    assert below_boundary["gross_documented_amount"] == 9500.00
    assert below_boundary["admin_fee_pct"] == 5.0
    assert below_boundary["admin_fee_amount"] == 475.00
    assert below_boundary["substantiated_amount"] == 9975.00

    # The smaller gross carries the larger rate and the larger absolute fee.
    assert below_boundary["admin_fee_amount"] > at_boundary["admin_fee_amount"]

    project = read_project(scenario["project"]["id"])
    assert project["change_order_recovered_amount"] == 0.00
    assert project["escalation_contingency_committed"] == 19500.00


# ---------------------------------------------------------------------------
# Queue B: validations /
#   conditional_validation_a_change_order_on_a_provisional_commitment_is_not_substantiated
# ---------------------------------------------------------------------------

def test_change_order_on_a_provisional_commitment_is_not_substantiated():
    """A released-but-undelivered PO carries PROVISIONAL escalation and cannot be claimed.

    PRD §3.9: "Preparation is only possible against a commitment whose escalation is
    **final**. The claim's `gross_documented_amount` is the commitment's
    `escalation_accrued`, and only when that commitment's `escalation_variant` is
    `FINAL`; a commitment still at `PROVISIONAL`, or one at `NONE`, yields a gross of
    0.00 and the preparation is refused with `ERR_CLAIM_NOT_SUBSTANTIATED`."
    PRD §1: "the system refuses to let a change order be substantiated from anything
    other than the final figure."

    Design: Corner/validations/conditional_validation_a_change_order_on_a_provisional_commitment_is_not_substantiated
    """
    scenario = build_released_scenario(release_at=EARLY_AUGUST)
    commitment_id = scenario["commitment"]["id"]
    assert read_commitment(commitment_id)["escalation_variant"] == "PROVISIONAL"

    response = api_client.create_change_order_request(
        create_change_order_request_payload(
            purchase_commitment_id=commitment_id,
            claimed_amount=20000.00,
            narrative=CLAIM_NARRATIVE,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value, 409)

    # Nothing was created and nothing upstream moved.
    listed, meta = validate_paginated(
        api_client.list_change_order_requests(
            BUYOUT_MANAGER, params={"purchase_commitment_id": commitment_id}
        )
    )
    assert meta["total_count"] == 0
    assert listed == []

    commitment = read_commitment(commitment_id)
    assert commitment["delivery_posture"] == "RELEASED_FOR_FAB"
    assert commitment["escalation_variant"] == "PROVISIONAL"
    assert commitment["escalation_accrued"] == STEEL_FINAL_ESCALATION

    project = read_project(scenario["project"]["id"])
    assert project["change_order_recovered_amount"] == 0.00
    assert project["escalation_contingency_committed"] == STEEL_FINAL_ESCALATION


# ---------------------------------------------------------------------------
# Queue B: validations /
#   conditional_validation_a_zero_claimed_amount_is_not_substantiated_even_when_final
# ---------------------------------------------------------------------------

def test_zero_claimed_amount_is_not_substantiated_even_when_final():
    """A claim of 0.00 is refused even against FINAL escalation; 20000.00 then succeeds.

    PRD §3.9: "The same code covers a commitment whose final `escalation_accrued` is
    0.00 and a `claimed_amount` that is not strictly greater than zero."
    PRD §2.9: "A change order requires a commitment whose escalation is final and
    greater than zero, and a `claimed_amount` greater than zero
    (`ERR_CLAIM_NOT_SUBSTANTIATED`, 409)."
    PRD §3.9: "The caller's `X-User-ID` is recorded in `prepared_by_user_id`,
    `submitted_by_user_id` and `owner_note` start null, and the request opens in
    `PREPARED`."

    Design: Corner/validations/conditional_validation_a_zero_claimed_amount_is_not_substantiated_even_when_final
    """
    scenario = _setup_delivered_steel_commitment()
    commitment_id = scenario["commitment"]["id"]
    assert read_commitment(commitment_id)["escalation_variant"] == "FINAL"

    refused = api_client.create_change_order_request(
        create_change_order_request_payload(
            purchase_commitment_id=commitment_id,
            claimed_amount=0.00,
            narrative=CLAIM_NARRATIVE,
        ),
        BUYOUT_MANAGER,
    )
    validate_error(refused, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value, 409)

    accepted = validate_success(
        api_client.create_change_order_request(
            create_change_order_request_payload(
                purchase_commitment_id=commitment_id,
                claimed_amount=20000.00,
                narrative=CLAIM_NARRATIVE,
            ),
            BUYOUT_MANAGER,
        ),
        201,
    )
    assert_change_order_request(accepted)
    assert_substantiation_arithmetic(accepted)
    assert accepted["status"] == "PREPARED"
    assert accepted["gross_documented_amount"] == STEEL_FINAL_ESCALATION
    assert accepted["admin_fee_pct"] == 3.5
    assert accepted["admin_fee_amount"] == STEEL_ADMIN_FEE
    assert accepted["substantiated_amount"] == STEEL_SUBSTANTIATED
    assert accepted["submitted_by_user_id"] is None
    assert accepted["owner_note"] is None
