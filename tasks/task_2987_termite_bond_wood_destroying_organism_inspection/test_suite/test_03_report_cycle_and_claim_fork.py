"""Non-linear lifecycles: a statutory report's loop and a claim's branching exit.

A statutory report may run the issued/amended loop as often as it likes.  Each
re-entry is a genuine new visit — the issuance instant moves and the correction
window restarts from it — yet the service-level measurement stays frozen at the
first delivery.  A verified damage claim, by contrast, leaves its adjudication
state by one of two exits that price identically and settle the reserve
differently, and both exits are terminal.
"""

from test_helpers import (
    ADJUDICATOR_HEADERS,
    AMENDMENT_DAMAGE_SCOPE_REVISED,
    AMENDMENT_SECONDARY_EVIDENCE_ADDED,
    CLAIM_APPROVED_REPAIR,
    CLAIM_APPROVED_RETREAT_ONLY,
    CLAIM_TYPE_REPAIR,
    CLAIM_TYPE_RETREAT,
    CLAIM_UNDER_ADJUDICATION,
    CLAIMS_ADJUDICATOR_ID,
    DECISION_APPROVE_REPAIR,
    DECISION_APPROVE_RETREAT_ONLY,
    ERR_INVALID_CLAIM_STATE,
    ERR_INVALID_REPORT_STATE,
    FORM_FL_DACS_13645,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    PURPOSE_RENEWAL,
    REPORT_AMENDED,
    REPORT_DRAFT,
    REPORT_ISSUED,
    STATE_TURNAROUND_HOURS,
    adjudicate_claim,
    adjudication_payload,
    amend_wdo_report,
    assert_bond_money,
    assert_claim_money,
    assert_instant_equals,
    assert_money,
    assert_repair_liability_conserved,
    assert_status,
    assert_version,
    attach_verification,
    bonded_property,
    damage_graph,
    file_claim,
    issue_wdo_report,
    open_wdo_report,
    real_estate_graph,
    register_inspector,
    register_property_and_inspector,
    set_clock,
    validate_error,
    validate_success,
)

# --- the statutory report timeline --------------------------------------------
#
# An FL structure carries a 72-hour turnaround allowance and files on
# FL_DACS_13645.  The report is requested at 10:00Z on 2026-08-01 and the sale
# closes 2026-09-15, so every issuance below stays clear of the final 24 hours.

REPORT_CLOCK_START = "2026-08-01T09:00:00Z"
REQUEST_INSTANT = "2026-08-01T10:00:00Z"
DUE_AT_INSTANT = "2026-08-04T10:00:00Z"
CLOSING_DATE = "2026-09-15"

FIRST_ISSUE_INSTANT = "2026-08-03T09:30:00Z"
FIRST_AMEND_INSTANT = "2026-08-20T12:00:00Z"
SECOND_ISSUE_INSTANT = "2026-08-25T12:00:00Z"
SECOND_AMEND_INSTANT = "2026-09-05T08:00:00Z"
THIRD_ISSUE_INSTANT = "2026-09-05T08:00:00Z"

TURNAROUND_HOURS = 48
RECOMPUTED_TURNAROUND_HOURS = 578

# --- the bond and the two claims ----------------------------------------------

CLOCK_START = "2026-08-01T00:00:00Z"
BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"
CLAIM_CLOCK_INSTANT = "2026-10-15T09:00:00Z"

REPAIR_CAP_USD = 11664.00
DAMAGE_CELLS = (
    ("A1", 3500.00, False, 3),
    ("B2", 1600.00, False, 2),
    ("C3", 2400.00, True, 4),
)
CLAIMED_DAMAGE_USD = 6000.00
ELIGIBLE_DAMAGE_USD = 5100.00
DEDUCTIBLE_USD = 357.00
PROJECTED_PAYOUT_USD = 4743.00
CAP_AFTER_REPAIR_USD = 6921.00


def _draft_report(api):
    """A DRAFT statutory report on a signed real-estate visit, requested at 10:00Z."""
    set_clock(api, REPORT_CLOCK_START)
    prop, inspector = register_property_and_inspector(api, state_code="FL")
    graph = real_estate_graph(
        api, prop["id"], inspector["id"], closing_date=CLOSING_DATE
    )
    set_clock(api, REQUEST_INSTANT)
    report = open_wdo_report(api, graph["id"], state_code="FL")
    return graph, report


def _issued_report(api):
    """Take the report through its first issuance at 47.5 elapsed hours."""
    graph, report = _draft_report(api)
    set_clock(api, FIRST_ISSUE_INSTANT)
    return graph, issue_wdo_report(api, report["id"])


def _amended_once(api):
    """Issue, then amend inside the first 30-day correction window."""
    graph, issued = _issued_report(api)
    set_clock(api, FIRST_AMEND_INSTANT)
    amended = amend_wdo_report(
        api, issued["id"], amendment_reason_code=AMENDMENT_SECONDARY_EVIDENCE_ADDED
    )
    return graph, amended


def _issued_twice(api):
    """Close the loop once: issued, amended, issued again on 2026-08-25."""
    graph, amended = _amended_once(api)
    set_clock(api, SECOND_ISSUE_INSTANT)
    return graph, issue_wdo_report(api, amended["id"])


def test_first_issuance_pins_the_turnaround_measurement(api):
    """The opening delivery is measured in whole hours and graded against 72.

    PRD 3.4: "On the **first** issuance only, two measurements are taken:
    `turnaround_hours`, the number of whole hours from `requested_at` to
    `issued_at` rounded up so that any partial hour counts as a full one, and
    `sla_breached`, true exactly when `turnaround_hours` strictly exceeds the
    state's allowance."

    Design: Difficulty/non_linear_state_machine/wdo_report_issued_amended_issued_cycle_pins_first_turnaround
    """
    graph, report = _draft_report(api)

    assert_status(report, REPORT_DRAFT, "report")
    assert report["form_code"] == FORM_FL_DACS_13645
    assert report["closing_date"] == CLOSING_DATE
    assert_instant_equals(report["requested_at"], REQUEST_INSTANT)
    assert_instant_equals(report["due_at"], DUE_AT_INSTANT)

    set_clock(api, FIRST_ISSUE_INSTANT)
    issued = issue_wdo_report(api, report["id"])

    assert_status(issued, REPORT_ISSUED, "report")
    assert issued["inspection_id"] == graph["id"]
    assert_instant_equals(issued["issued_at"], FIRST_ISSUE_INSTANT)
    assert issued["turnaround_hours"] == TURNAROUND_HOURS
    assert issued["sla_breached"] is False
    assert TURNAROUND_HOURS <= STATE_TURNAROUND_HOURS["FL"]
    assert issued["amendment_count"] == 0


def test_an_issued_report_cannot_be_issued_again_without_an_amendment(api):
    """The loop is only re-entered through a correction, never issue upon issue.

    PRD 3.4: "Attempting to issue a report that is neither `DRAFT` nor `AMENDED`,
    or to amend one that is not `ISSUED`, or to touch one that is already `VOID`,
    is `ERR_INVALID_REPORT_STATE`."

    Design: Difficulty/non_linear_state_machine/wdo_report_issued_amended_issued_cycle_pins_first_turnaround
    """
    _graph, issued = _issued_report(api)

    refused = api.issue_wdo_report(issued["id"], {}, OFFICER_HEADERS)
    validate_error(refused, ERR_INVALID_REPORT_STATE)

    unchanged = validate_success(api.get_wdo_report(issued["id"], OFFICER_HEADERS))
    assert_status(unchanged, REPORT_ISSUED, "report")
    assert_instant_equals(unchanged["issued_at"], FIRST_ISSUE_INSTANT)
    assert unchanged["turnaround_hours"] == TURNAROUND_HOURS
    assert unchanged["amendment_count"] == 0


def test_an_amendment_records_its_reason_and_leaves_the_measurement_alone(api):
    """Correcting the report counts the correction and nothing else.

    PRD 3.4: "The amendment raises `amendment_count` by one and records the
    supplied reason on the report, and it explicitly does not recompute
    `turnaround_hours` or `sla_breached`: both stay pinned to the first issuance
    for ever."

    Design: Difficulty/non_linear_state_machine/wdo_report_issued_amended_issued_cycle_pins_first_turnaround
    """
    _graph, amended = _amended_once(api)

    assert_status(amended, REPORT_AMENDED, "report")
    assert amended["amendment_count"] == 1
    assert amended["amendment_reason_code"] == AMENDMENT_SECONDARY_EVIDENCE_ADDED
    assert amended["turnaround_hours"] == TURNAROUND_HOURS
    assert amended["sla_breached"] is False
    assert_instant_equals(amended["issued_at"], FIRST_ISSUE_INSTANT)


def test_reissuing_refreshes_the_issuance_instant_but_not_the_measurement(api):
    """The second delivery moves issued_at while the service-level grade holds still.

    PRD 3.4: "A re-issue... refreshes `issued_at` to the instant of this
    issuance -- which, since the amendment window is measured from `issued_at`,
    restarts the 30-day amendment window. It leaves `turnaround_hours` and
    `sla_breached` at their first-issuance values."

    Design: Difficulty/non_linear_state_machine/wdo_report_issued_amended_issued_cycle_pins_first_turnaround
    """
    _graph, reissued = _issued_twice(api)

    assert_status(reissued, REPORT_ISSUED, "report")
    assert_instant_equals(reissued["issued_at"], SECOND_ISSUE_INSTANT)
    assert reissued["turnaround_hours"] == TURNAROUND_HOURS
    assert reissued["turnaround_hours"] != RECOMPUTED_TURNAROUND_HOURS
    assert reissued["sla_breached"] is False
    assert reissued["amendment_count"] == 1
    assert_instant_equals(reissued["requested_at"], REQUEST_INSTANT)
    assert_instant_equals(reissued["due_at"], DUE_AT_INSTANT)


def test_the_correction_window_runs_from_the_latest_issuance(api):
    """A correction 33 days after the first delivery is in time because a second one intervened.

    PRD 3.4: "Amendment... is only available while the clock's UTC date is no
    later than 30 days after the date of the report's current `issued_at`; later
    attempts are `ERR_AMENDMENT_WINDOW_CLOSED`."

    Design: Difficulty/non_linear_state_machine/wdo_report_issued_amended_issued_cycle_pins_first_turnaround
    """
    _graph, reissued = _issued_twice(api)
    assert_instant_equals(reissued["issued_at"], SECOND_ISSUE_INSTANT)

    set_clock(api, SECOND_AMEND_INSTANT)
    amended = amend_wdo_report(
        api, reissued["id"], amendment_reason_code=AMENDMENT_DAMAGE_SCOPE_REVISED
    )

    assert_status(amended, REPORT_AMENDED, "report")
    assert amended["amendment_count"] == 2
    assert amended["amendment_reason_code"] == AMENDMENT_DAMAGE_SCOPE_REVISED
    assert_instant_equals(amended["issued_at"], SECOND_ISSUE_INSTANT)
    assert amended["turnaround_hours"] == TURNAROUND_HOURS


def test_the_full_cycle_accounts_for_three_issuances_and_two_corrections(api):
    """Running the loop twice leaves one version increment per accepted transition.

    PRD 3.4: "From `AMENDED` the report is re-issued, returning it to `ISSUED` and
    closing the loop; `amendment_count` records how many times the loop has run."

    Design: Difficulty/non_linear_state_machine/wdo_report_issued_amended_issued_cycle_pins_first_turnaround
    """
    _graph, reissued = _issued_twice(api)
    set_clock(api, SECOND_AMEND_INSTANT)
    amend_wdo_report(
        api, reissued["id"], amendment_reason_code=AMENDMENT_DAMAGE_SCOPE_REVISED
    )

    set_clock(api, THIRD_ISSUE_INSTANT)
    final = issue_wdo_report(api, reissued["id"])

    assert_status(final, REPORT_ISSUED, "report")
    assert_instant_equals(final["issued_at"], THIRD_ISSUE_INSTANT)
    assert final["turnaround_hours"] == TURNAROUND_HOURS
    assert final["sla_breached"] is False
    assert final["amendment_count"] == 2
    assert_version(final, 6, "report")


def _bond_and_verifier(api):
    """An 11664.00-ceiling bond plus a licensee who did not apply the chemical."""
    set_clock(api, CLOCK_START)
    chain = bonded_property(api, state_code="FL", issue_instant=BOND_ISSUE_INSTANT)
    verifier = register_inspector(api, license_state="FL")
    set_clock(api, CLAIM_CLOCK_INSTANT)
    return chain, verifier


def _verified_claim(api, chain, verifier, supersedes_inspection_id, claim_type):
    """File a claim of the given kind and price it off a superseding damage graph."""
    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    claim = file_claim(
        api,
        bond,
        chain["property"]["id"],
        CLAIMED_DAMAGE_USD,
        claim_type=claim_type,
    )
    graph = damage_graph(
        api,
        chain["property"]["id"],
        verifier["id"],
        DAMAGE_CELLS,
        purpose=PURPOSE_RENEWAL,
        supersedes_inspection_id=supersedes_inspection_id,
    )
    priced = attach_verification(api, claim["id"], graph["id"], verifier["id"])
    assert_status(priced, CLAIM_UNDER_ADJUDICATION, "claim")
    assert_claim_money(
        priced,
        eligible_damage_usd=ELIGIBLE_DAMAGE_USD,
        deductible_usd=DEDUCTIBLE_USD,
        projected_payout_usd=PROJECTED_PAYOUT_USD,
    )
    return graph, priced


def test_retreat_only_approval_releases_the_reserve_and_raises_an_obligation(api):
    """One exit approves labour, hands the money back and books a re-treatment credit.

    PRD 3.10: "`APPROVE_RETREAT_ONLY` moves the claim to `APPROVED_RETREAT_ONLY`,
    sets `approved_payout_usd` to 0.00, and releases the reserve...  No money
    leaves the bond, but an obligation is raised: the bond's `retreat_required` is
    set true and its `retreat_credit_count` rises by one."

    Design: Difficulty/non_linear_state_machine/damage_claim_fork_retreat_only_versus_repair_settles_reserve_differently
    """
    chain, verifier = _bond_and_verifier(api)
    _graph, priced = _verified_claim(
        api, chain, verifier, chain["inspection"]["id"], CLAIM_TYPE_RETREAT
    )

    decided = adjudicate_claim(api, priced["id"], DECISION_APPROVE_RETREAT_ONLY)

    assert_status(decided, CLAIM_APPROVED_RETREAT_ONLY, "claim")
    assert_claim_money(decided, approved_payout_usd=0.00)
    assert decided["adjudicated_by_user_id"] == CLAIMS_ADJUDICATOR_ID

    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_bond_money(
        bond,
        repair_liability_cap_usd=REPAIR_CAP_USD,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=REPAIR_CAP_USD,
    )
    assert bond["retreat_credit_count"] == 1
    assert bond["retreat_required"] is True
    assert_repair_liability_conserved(bond)


def test_an_approved_claim_cannot_be_re_adjudicated(api):
    """Both approval exits are terminal, so a second decision moves nothing.

    PRD 3.10: "Adjudication is a `ClaimsAdjudicator` decision on an
    `UNDER_ADJUDICATION` claim"; withdrawing or re-deciding a claim that has
    already reached `APPROVED_REPAIR`, `APPROVED_RETREAT_ONLY`, `DENIED` or
    `WITHDRAWN` is `ERR_INVALID_CLAIM_STATE` because "all four of those... are
    terminal."

    Design: Difficulty/non_linear_state_machine/damage_claim_fork_retreat_only_versus_repair_settles_reserve_differently
    """
    chain, verifier = _bond_and_verifier(api)
    _graph, priced = _verified_claim(
        api, chain, verifier, chain["inspection"]["id"], CLAIM_TYPE_RETREAT
    )
    adjudicate_claim(api, priced["id"], DECISION_APPROVE_RETREAT_ONLY)

    refused = api.adjudicate_claim(
        priced["id"],
        adjudication_payload(DECISION_APPROVE_REPAIR),
        ADJUDICATOR_HEADERS,
    )
    validate_error(refused, ERR_INVALID_CLAIM_STATE)

    unchanged = validate_success(api.get_damage_claim(priced["id"], MANAGER_HEADERS))
    assert_status(unchanged, CLAIM_APPROVED_RETREAT_ONLY, "claim")
    assert_claim_money(unchanged, approved_payout_usd=0.00)

    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_bond_money(
        bond,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=REPAIR_CAP_USD,
    )
    assert bond["retreat_credit_count"] == 1
    assert_repair_liability_conserved(bond)


def test_repair_approval_moves_the_reserve_into_money_paid(api):
    """The other exit pays the priced figure out of the reserve, not out of headroom.

    PRD 3.10: "On the bond, `claims_paid_to_date_usd` rises by that amount and
    `reserved_claim_amount_usd` falls by it, while `remaining_repair_cap_usd` is
    left exactly where it was -- the money moves from reserved to paid, not from
    available to paid."

    Design: Difficulty/non_linear_state_machine/damage_claim_fork_retreat_only_versus_repair_settles_reserve_differently
    """
    chain, verifier = _bond_and_verifier(api)
    _graph, priced = _verified_claim(
        api, chain, verifier, chain["inspection"]["id"], CLAIM_TYPE_REPAIR
    )

    decided = adjudicate_claim(api, priced["id"], DECISION_APPROVE_REPAIR)

    assert_status(decided, CLAIM_APPROVED_REPAIR, "claim")
    assert_claim_money(decided, approved_payout_usd=PROJECTED_PAYOUT_USD)
    assert decided["adjudicated_by_user_id"] == CLAIMS_ADJUDICATOR_ID

    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_bond_money(
        bond,
        repair_liability_cap_usd=REPAIR_CAP_USD,
        claims_paid_to_date_usd=PROJECTED_PAYOUT_USD,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=CAP_AFTER_REPAIR_USD,
    )
    assert bond["retreat_credit_count"] == 0
    assert_repair_liability_conserved(bond)


def test_the_two_exits_price_alike_and_settle_the_reserve_differently(api):
    """Two claims priced at 4743.00 leave adjudication with opposite ledger effects.

    PRD 3.10: "The three branches settle the reserve in three different ways, and
    each records `adjudicated_by_user_id` as the acting identifier and raises both
    the claim's and the bond's `version` by one."

    Design: Difficulty/non_linear_state_machine/damage_claim_fork_retreat_only_versus_repair_settles_reserve_differently
    """
    chain, verifier = _bond_and_verifier(api)

    first_graph, first_priced = _verified_claim(
        api, chain, verifier, chain["inspection"]["id"], CLAIM_TYPE_RETREAT
    )
    reserved = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_bond_money(reserved, reserved_claim_amount_usd=PROJECTED_PAYOUT_USD)
    assert_repair_liability_conserved(reserved)

    retreat_exit = adjudicate_claim(
        api, first_priced["id"], DECISION_APPROVE_RETREAT_ONLY
    )
    after_retreat = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_repair_liability_conserved(after_retreat)

    _second_graph, second_priced = _verified_claim(
        api, chain, verifier, first_graph["id"], CLAIM_TYPE_REPAIR
    )
    repair_exit = adjudicate_claim(api, second_priced["id"], DECISION_APPROVE_REPAIR)
    after_repair = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))

    assert_money(
        first_priced["projected_payout_usd"], second_priced["projected_payout_usd"]
    )
    assert_money(second_priced["projected_payout_usd"], PROJECTED_PAYOUT_USD)

    assert_status(retreat_exit, CLAIM_APPROVED_RETREAT_ONLY, "claim")
    assert_status(repair_exit, CLAIM_APPROVED_REPAIR, "claim")
    assert_claim_money(retreat_exit, approved_payout_usd=0.00)
    assert_claim_money(repair_exit, approved_payout_usd=PROJECTED_PAYOUT_USD)

    assert_bond_money(
        after_retreat,
        claims_paid_to_date_usd=0.00,
        remaining_repair_cap_usd=REPAIR_CAP_USD,
    )
    assert_bond_money(
        after_repair,
        claims_paid_to_date_usd=PROJECTED_PAYOUT_USD,
        reserved_claim_amount_usd=0.00,
        remaining_repair_cap_usd=CAP_AFTER_REPAIR_USD,
    )
    assert after_repair["retreat_credit_count"] == after_retreat["retreat_credit_count"]
    assert after_repair["retreat_credit_count"] == 1
    assert_repair_liability_conserved(after_repair)
