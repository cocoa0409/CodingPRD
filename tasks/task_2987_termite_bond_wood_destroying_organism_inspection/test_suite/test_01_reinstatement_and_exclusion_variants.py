"""Variant-pair arithmetic: bond reinstatement settlements and claim exclusion bases.

Two contrasts are exercised here.  A lapsed bond bought back inside 30 days of
its lapse date settles under the prorated-remainder treatment and keeps its
anniversary; the same bond bought back 45 days out settles under the
full-term-restart treatment and moves it.  A damage claim verified by a graph
that supersedes an earlier one is priced under FINDING_LEVEL; a claim verified
by a graph that supersedes nothing is priced under AGGREGATE_PRORATION.
"""

from test_helpers import (
    BOND_ACTIVE,
    BOND_LAPSED,
    CLAIM_UNDER_ADJUDICATION,
    CLAIM_WITHDRAWN,
    CONDUCIVE_EXCESS_MOISTURE,
    ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT,
    EXCLUSION_AGGREGATE_PRORATION,
    EXCLUSION_FINDING_LEVEL,
    MANAGER_HEADERS,
    assert_bond_money,
    assert_claim_money,
    assert_money,
    assert_repair_liability_conserved,
    assert_status,
    bonded_property,
    conducive_finding_payload,
    register_inspector,
    reinstatement_graph,
    reinstatement_payload,
    review_bond_term,
    set_clock,
    validate_error,
    validate_success,
    verified_claim,
    withdraw_claim,
)

# --- the shared bond geometry -------------------------------------------------
#
# An FL slab of 2000 square feet and 180 linear feet quotes at 1080.00, which
# gives base_premium_usd 194.40, a REPAIR_AND_RETREAT ceiling of 11664.00 and
# annual_premium_usd 241.06.  Issued on 2026-09-01 the term ends 2027-09-01 and
# the grace deadline that a lapse records is 2027-10-01.

CLOCK_START = "2026-08-01T00:00:00Z"
BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"
ANNUAL_PREMIUM_USD = 241.06
REPAIR_CAP_USD = 11664.00

FIRST_REVIEW_INSTANT = "2027-10-05T00:00:00Z"
FIRST_LAPSE_DATE = "2027-10-01"
FIRST_GRAPH_INSTANT = "2027-10-10T09:00:00Z"
FIRST_REINSTATE_INSTANT = "2027-10-16T00:00:00Z"
PRORATED_SETTLEMENT_USD = 352.40
PRORATED_ONE_CENT_SHORT_USD = 352.39
PRORATED_TERM_START = "2027-10-01"
PRORATED_TERM_END = "2028-08-31"

SECOND_REVIEW_INSTANT = "2028-10-05T00:00:00Z"
SECOND_LAPSE_DATE = "2028-09-30"
SECOND_GRAPH_INSTANT = "2028-11-10T09:00:00Z"
SECOND_REINSTATE_INSTANT = "2028-11-14T00:00:00Z"
RESTART_SETTLEMENT_USD = 414.81
RESTART_ONE_CENT_SHORT_USD = 414.80
RESTART_TERM_START = "2028-11-14"
RESTART_TERM_END = "2029-11-14"

# --- the shared verifying-graph findings --------------------------------------
#
# (grid_ref, damage_estimate_usd, pre_existing, severity).  The dollar split is
# 3500.00 + 1600.00 new against 2400.00 pre-existing; the severity split is
# 3 + 2 new against a total of 9.

DAMAGE_CELLS = (
    ("A1", 3500.00, False, 3),
    ("B2", 1600.00, False, 2),
    ("C3", 2400.00, True, 4),
)
CLAIMED_DAMAGE_USD = 6000.00
CLAIM_CLOCK_INSTANT = "2026-10-15T09:00:00Z"

FINDING_LEVEL_ELIGIBLE_USD = 5100.00
FINDING_LEVEL_EXCLUDED_USD = 900.00
FINDING_LEVEL_DEDUCTIBLE_USD = 357.00
FINDING_LEVEL_PROJECTED_USD = 4743.00

PRORATION_ELIGIBLE_USD = 3333.33
PRORATION_EXCLUDED_USD = 2666.67
PRORATION_DEDUCTIBLE_USD = 233.33
PRORATION_PROJECTED_USD = 3100.00


def _bonded_chain(api):
    """An ACTIVE REPAIR_AND_RETREAT bond on the shared FL slab, issued 2026-09-01."""
    set_clock(api, CLOCK_START)
    return bonded_property(
        api,
        state_code="FL",
        findings=[
            conducive_finding_payload("A1", CONDUCIVE_EXCESS_MOISTURE, severity=2)
        ],
        issue_instant=BOND_ISSUE_INSTANT,
    )


def _lapse(api, bond_id, review_instant):
    """Park the clock past the grace deadline and review the bond into LAPSED."""
    set_clock(api, review_instant)
    return review_bond_term(api, bond_id)


def _reinstatement_attempt(
    api, chain, supersedes_id, graph_instant, reinstate_instant, amount_usd
):
    """Sign a fresh REINSTATEMENT graph and tender the supplied settlement."""
    set_clock(api, graph_instant)
    graph = reinstatement_graph(
        api, chain["property"]["id"], chain["inspector"]["id"], supersedes_id
    )
    set_clock(api, reinstate_instant)
    response = api.reinstate_bond(
        chain["bond"]["id"],
        reinstatement_payload(graph["id"], amount_usd),
        MANAGER_HEADERS,
    )
    return graph, response


def test_prorated_remainder_reinstatement_preserves_the_anniversary(api):
    """A bond down 15 days settles on the unexpired fraction and keeps its term end.

    PRD 3.8: "When `lapse_days` is 30 or fewer, the prorated-remainder treatment
    applies: the premium charge is `annual_premium_usd` multiplied by the
    unexpired fraction of the term -- 365 less `lapse_days`, divided by 365 --
    rounded half up to two decimals; the bond's `current_term_start` becomes the
    old `lapse_date` and its `current_term_end` becomes the previous
    `current_term_end` plus 365 days, so the bond's anniversary date never
    moves."

    Design: Difficulty/dual_variant_calc/bond_reinstatement_prorated_remainder_vs_full_term_restart
    """
    chain = _bonded_chain(api)
    bond = chain["bond"]
    assert_money(bond["annual_premium_usd"], ANNUAL_PREMIUM_USD)

    lapsed = _lapse(api, bond["id"], FIRST_REVIEW_INSTANT)
    assert_status(lapsed, BOND_LAPSED, "bond")
    assert lapsed["lapse_date"] == FIRST_LAPSE_DATE

    _graph, response = _reinstatement_attempt(
        api,
        chain,
        chain["inspection"]["id"],
        FIRST_GRAPH_INSTANT,
        FIRST_REINSTATE_INSTANT,
        PRORATED_SETTLEMENT_USD,
    )
    reinstated = validate_success(response)

    assert_status(reinstated, BOND_ACTIVE, "bond")
    assert reinstated["current_term_start"] == PRORATED_TERM_START
    assert reinstated["current_term_end"] == PRORATED_TERM_END
    assert reinstated["reinstatement_count"] == 1
    assert reinstated["term_index"] == 2
    assert reinstated["lapse_date"] is None
    assert_money(reinstated["annual_premium_usd"], ANNUAL_PREMIUM_USD)


def test_prorated_remainder_settlement_is_owed_to_the_exact_cent(api):
    """One cent below the prorated amount owed is refused as an underpayment.

    PRD 3.8: "the amount owed is the premium charge plus a flat reinstatement fee
    of 95.00 plus 1.75 for each day of lapse, the whole sum rounded half up to
    two decimal places... If `amount_usd` is less than the amount owed, the
    attempt is `ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT`."

    Design: Difficulty/dual_variant_calc/bond_reinstatement_prorated_remainder_vs_full_term_restart
    """
    chain = _bonded_chain(api)
    _lapse(api, chain["bond"]["id"], FIRST_REVIEW_INSTANT)

    graph, response = _reinstatement_attempt(
        api,
        chain,
        chain["inspection"]["id"],
        FIRST_GRAPH_INSTANT,
        FIRST_REINSTATE_INSTANT,
        PRORATED_ONE_CENT_SHORT_USD,
    )
    validate_error(response, ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT)

    still_lapsed = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_status(still_lapsed, BOND_LAPSED, "bond")
    assert still_lapsed["reinstatement_count"] == 0

    accepted = validate_success(
        api.reinstate_bond(
            chain["bond"]["id"],
            reinstatement_payload(graph["id"], PRORATED_SETTLEMENT_USD),
            MANAGER_HEADERS,
        )
    )
    assert_status(accepted, BOND_ACTIVE, "bond")


def _first_reinstatement(api, chain):
    """Lapse the bond, buy it back 15 days later and return the graph it used."""
    _lapse(api, chain["bond"]["id"], FIRST_REVIEW_INSTANT)
    graph, response = _reinstatement_attempt(
        api,
        chain,
        chain["inspection"]["id"],
        FIRST_GRAPH_INSTANT,
        FIRST_REINSTATE_INSTANT,
        PRORATED_SETTLEMENT_USD,
    )
    return graph, validate_success(response)


def test_full_term_restart_reinstatement_moves_the_anniversary(api):
    """A bond down 45 days pays the whole premium and restarts its term on the clock.

    PRD 3.8: "When `lapse_days` exceeds 30, the full-term-restart treatment
    applies instead: the premium charge is the whole `annual_premium_usd` with no
    proration, `current_term_start` becomes the clock's UTC date and
    `current_term_end` becomes 365 days after the clock's UTC date, which moves
    the anniversary."

    Design: Difficulty/dual_variant_calc/bond_reinstatement_prorated_remainder_vs_full_term_restart
    """
    chain = _bonded_chain(api)
    first_graph, _first = _first_reinstatement(api, chain)

    lapsed_again = _lapse(api, chain["bond"]["id"], SECOND_REVIEW_INSTANT)
    assert_status(lapsed_again, BOND_LAPSED, "bond")
    assert lapsed_again["lapse_date"] == SECOND_LAPSE_DATE

    _graph, response = _reinstatement_attempt(
        api,
        chain,
        first_graph["id"],
        SECOND_GRAPH_INSTANT,
        SECOND_REINSTATE_INSTANT,
        RESTART_SETTLEMENT_USD,
    )
    restarted = validate_success(response)

    assert_status(restarted, BOND_ACTIVE, "bond")
    assert restarted["current_term_start"] == RESTART_TERM_START
    assert restarted["current_term_end"] == RESTART_TERM_END
    assert restarted["reinstatement_count"] == 2
    assert restarted["term_index"] == 3
    assert restarted["lapse_date"] is None
    assert_money(restarted["annual_premium_usd"], ANNUAL_PREMIUM_USD)


def test_full_term_restart_settlement_is_owed_to_the_exact_cent(api):
    """One cent below the unprorated amount owed is refused as an underpayment.

    PRD 3.8: "the premium charge is the whole `annual_premium_usd` with no
    proration... the amount owed is the premium charge plus a flat reinstatement
    fee of 95.00 plus 1.75 for each day of lapse, the whole sum rounded half up
    to two decimal places."

    Design: Difficulty/dual_variant_calc/bond_reinstatement_prorated_remainder_vs_full_term_restart
    """
    chain = _bonded_chain(api)
    first_graph, _first = _first_reinstatement(api, chain)
    _lapse(api, chain["bond"]["id"], SECOND_REVIEW_INSTANT)

    graph, response = _reinstatement_attempt(
        api,
        chain,
        first_graph["id"],
        SECOND_GRAPH_INSTANT,
        SECOND_REINSTATE_INSTANT,
        RESTART_ONE_CENT_SHORT_USD,
    )
    validate_error(response, ERR_REINSTATEMENT_PAYMENT_INSUFFICIENT)

    still_lapsed = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_status(still_lapsed, BOND_LAPSED, "bond")
    assert still_lapsed["reinstatement_count"] == 1

    accepted = validate_success(
        api.reinstate_bond(
            chain["bond"]["id"],
            reinstatement_payload(graph["id"], RESTART_SETTLEMENT_USD),
            MANAGER_HEADERS,
        )
    )
    assert_status(accepted, BOND_ACTIVE, "bond")
    assert accepted["reinstatement_count"] == 2


def test_restart_costs_strictly_more_and_lands_on_a_different_term_end(api):
    """The same bond's two buy-backs disagree on both money and term geometry.

    PRD 3.8: "For otherwise identical bonds the restart treatment always costs
    strictly more and lands on a different term end than the prorated one."

    Design: Difficulty/dual_variant_calc/bond_reinstatement_prorated_remainder_vs_full_term_restart
    """
    chain = _bonded_chain(api)
    first_graph, prorated = _first_reinstatement(api, chain)
    _lapse(api, chain["bond"]["id"], SECOND_REVIEW_INSTANT)
    _graph, response = _reinstatement_attempt(
        api,
        chain,
        first_graph["id"],
        SECOND_GRAPH_INSTANT,
        SECOND_REINSTATE_INSTANT,
        RESTART_SETTLEMENT_USD,
    )
    restarted = validate_success(response)

    assert RESTART_SETTLEMENT_USD > PRORATED_SETTLEMENT_USD
    assert prorated["current_term_end"] == PRORATED_TERM_END
    assert restarted["current_term_end"] == RESTART_TERM_END
    assert restarted["current_term_end"] != prorated["current_term_end"]
    assert restarted["current_term_start"] != prorated["current_term_start"]
    assert_money(restarted["annual_premium_usd"], prorated["annual_premium_usd"])


def _claim_chain(api):
    """A bonded structure plus a second licensee free to certify its damage.

    The chain's own licensee applied the chemical, so a claim it verified would
    be refused; the second licensee shares the jurisdiction and may verify.
    """
    chain = _bonded_chain(api)
    verifier = register_inspector(api, license_state="FL")
    set_clock(api, CLAIM_CLOCK_INSTANT)
    return chain, verifier


def test_finding_level_basis_excludes_whole_pre_existing_cells(api):
    """A claim verified by a superseding graph excludes the pre-existing dollars.

    PRD 3.10: "When the verifying graph carries a `supersedes_inspection_id`...
    the `exclusion_basis` recorded on the claim is `FINDING_LEVEL`." Under that
    basis "the `damage_estimate_usd` values of the graph's `DAMAGE` notations
    whose `pre_existing` is false are summed, and `eligible_damage_usd` is the
    lesser of that sum and the claim's `claimed_damage_usd`".

    Design: Difficulty/dual_variant_calc/claim_exclusion_finding_level_vs_aggregate_proration
    """
    chain, verifier = _claim_chain(api)

    priced = verified_claim(
        api,
        chain,
        CLAIMED_DAMAGE_USD,
        DAMAGE_CELLS,
        verifier=verifier,
        supersedes_inspection_id=chain["inspection"]["id"],
    )
    claim = priced["claim"]

    assert_status(claim, CLAIM_UNDER_ADJUDICATION, "claim")
    assert claim["exclusion_basis"] == EXCLUSION_FINDING_LEVEL
    assert claim["verifying_inspection_id"] == priced["verifying_inspection"]["id"]
    assert_claim_money(
        claim,
        eligible_damage_usd=FINDING_LEVEL_ELIGIBLE_USD,
        excluded_pre_existing_usd=FINDING_LEVEL_EXCLUDED_USD,
        deductible_usd=FINDING_LEVEL_DEDUCTIBLE_USD,
        projected_payout_usd=FINDING_LEVEL_PROJECTED_USD,
    )

    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_bond_money(
        bond,
        repair_liability_cap_usd=REPAIR_CAP_USD,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=FINDING_LEVEL_PROJECTED_USD,
        remaining_repair_cap_usd=REPAIR_CAP_USD - FINDING_LEVEL_PROJECTED_USD,
    )
    assert_repair_liability_conserved(bond)


def test_aggregate_proration_basis_excludes_a_severity_weighted_share(api):
    """A claim verified by a graph with no ancestor is prorated on severity weights.

    PRD 3.10: "When it supersedes nothing, the basis is `AGGREGATE_PRORATION`."
    Under that basis "the `severity` weights of the `DAMAGE` notations whose
    `pre_existing` is false are summed, the `severity` weights of all the graph's
    `DAMAGE` notations are summed, and `eligible_damage_usd` is
    `claimed_damage_usd` multiplied by the first sum divided by the second,
    carried at full precision and rounded half up to two decimal places exactly
    once."

    Design: Difficulty/dual_variant_calc/claim_exclusion_finding_level_vs_aggregate_proration
    """
    chain, verifier = _claim_chain(api)

    priced = verified_claim(
        api, chain, CLAIMED_DAMAGE_USD, DAMAGE_CELLS, verifier=verifier
    )
    claim = priced["claim"]

    assert_status(claim, CLAIM_UNDER_ADJUDICATION, "claim")
    assert claim["exclusion_basis"] == EXCLUSION_AGGREGATE_PRORATION
    assert priced["verifying_inspection"]["supersedes_inspection_id"] is None
    assert_claim_money(
        claim,
        eligible_damage_usd=PRORATION_ELIGIBLE_USD,
        excluded_pre_existing_usd=PRORATION_EXCLUDED_USD,
        deductible_usd=PRORATION_DEDUCTIBLE_USD,
        projected_payout_usd=PRORATION_PROJECTED_USD,
    )

    bond = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_bond_money(
        bond,
        repair_liability_cap_usd=REPAIR_CAP_USD,
        claims_paid_to_date_usd=0.00,
        reserved_claim_amount_usd=PRORATION_PROJECTED_USD,
        remaining_repair_cap_usd=REPAIR_CAP_USD - PRORATION_PROJECTED_USD,
    )
    assert_repair_liability_conserved(bond)


def test_identical_findings_settle_differently_by_graph_lineage(api):
    """Two 6000.00 claims on the same cells part company on the verifier's ancestry.

    PRD 3.10: "For identical findings the two bases produce genuinely different
    eligible amounts; the lineage of the graph decides which one governs."

    Design: Difficulty/dual_variant_calc/claim_exclusion_finding_level_vs_aggregate_proration
    """
    chain, verifier = _claim_chain(api)

    first = verified_claim(
        api,
        chain,
        CLAIMED_DAMAGE_USD,
        DAMAGE_CELLS,
        verifier=verifier,
        supersedes_inspection_id=chain["inspection"]["id"],
    )["claim"]
    withdrawn = withdraw_claim(api, first["id"], chain["property"]["id"])
    assert_status(withdrawn, CLAIM_WITHDRAWN, "claim")

    released = validate_success(api.get_bond(chain["bond"]["id"], MANAGER_HEADERS))
    assert_bond_money(released, reserved_claim_amount_usd=0.00)
    assert_repair_liability_conserved(released)
    chain["bond"] = released

    second = verified_claim(
        api, chain, CLAIMED_DAMAGE_USD, DAMAGE_CELLS, verifier=verifier
    )["claim"]

    assert first["exclusion_basis"] == EXCLUSION_FINDING_LEVEL
    assert second["exclusion_basis"] == EXCLUSION_AGGREGATE_PRORATION
    assert_money(first["eligible_damage_usd"], FINDING_LEVEL_ELIGIBLE_USD)
    assert_money(second["eligible_damage_usd"], PRORATION_ELIGIBLE_USD)
    assert first["eligible_damage_usd"] != second["eligible_damage_usd"]
    assert_money(first["claimed_damage_usd"], second["claimed_damage_usd"])
    assert first["projected_payout_usd"] > second["projected_payout_usd"]
