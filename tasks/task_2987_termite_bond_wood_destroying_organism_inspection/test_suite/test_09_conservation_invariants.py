"""Two conserved quantities in two different units, each with its own pair.

A bond's repair ceiling is partitioned into paid, reserved and available money,
and verification/withdrawal move a reserve back and forth without changing the
total.  A structure's conducive-condition ledger is an integer count of
distinct codes partitioned into waived and open, where bond issuance suppresses
and bond termination restores, again without moving the total.
"""

from test_helpers import (
    BOND_ACTIVE,
    BOND_LAPSED,
    BOND_TERMINATED,
    CLAIM_APPROVED_REPAIR,
    CLAIM_SUBMITTED,
    CLAIM_UNDER_ADJUDICATION,
    CLAIM_WITHDRAWN,
    CLOCK_STARTUP_INSTANT,
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_FAULTY_GRADE,
    CONDUCIVE_WOOD_TO_GROUND,
    DECISION_APPROVE_REPAIR,
    EXCLUSION_AGGREGATE_PRORATION,
    FINDING_CONDUCIVE_CONDITION,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    TIER_REPAIR_AND_RETREAT,
    assert_bond_money,
    assert_claim_money,
    assert_conducive_counts_conserved,
    assert_money,
    assert_repair_liability_conserved,
    assert_status,
    conducive_finding_payload,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    adjudicate_claim,
    attach_verification,
    bonded_property,
    completed_liquid_plan,
    damage_graph,
    file_claim,
    graphed_inspection,
    issue_bond,
    register_inspector,
    register_property_and_inspector,
    review_bond_term,
    set_clock,
    withdraw_claim,
)

BOND_ISSUE_INSTANT = "2026-09-01T00:00:00Z"
CLAIM_INSTANT = "2026-10-01T00:00:00Z"
LAPSE_REVIEW_INSTANT = "2027-10-05T00:00:00Z"
TERMINATION_REVIEW_INSTANT = "2027-12-31T00:00:00Z"

# P1: FL SLAB, 2000 sq ft, 180 linear ft.  Its LIQUID_BARRIER plan is quoted
# 1080.00, so the base premium is 194.40 and the REPAIR_AND_RETREAT ceiling is
# sixty times that.
EXPECTED_REPAIR_CAP = 11664.00

# Every claim below is filed for 4000.00 REPAIR against a graph carrying
# 3000.00 of new damage at severity 3 and 1000.00 of pre-existing damage at
# severity 1, so the severity share is 3/4.
CLAIMED_DAMAGE = 4000.00
EXPECTED_ELIGIBLE = 3000.00
EXPECTED_EXCLUDED = 1000.00
EXPECTED_DEDUCTIBLE = 210.00
EXPECTED_RESERVE = 2790.00
EXPECTED_REMAINING_WHILE_RESERVED = 8874.00

DAMAGE_CELLS = (
    ("A2", 3000.00, False, 3),
    ("A3", 1000.00, True, 1),
)


def _bond(api, bond_id):
    """Re-read the bond so its money and version are the live ones."""
    return validate_success(api.get_bond(bond_id, MANAGER_HEADERS))


def _bonded_structure_with_a_damage_graph(api):
    """A bonded FL structure plus a signed damage graph a second licensee owns.

    The bond's own applicator may not certify damage against the treatment it
    performed, so the graph is opened and signed by a separate licensee.
    """
    set_clock(api, CLOCK_STARTUP_INSTANT)
    chain = bonded_property(api, state_code="FL", issue_instant=BOND_ISSUE_INSTANT)
    verifier = register_inspector(api, license_state="FL", full_name="Marisol Kane")
    set_clock(api, CLAIM_INSTANT)
    graph = damage_graph(api, chain["property"]["id"], verifier["id"], DAMAGE_CELLS)
    chain["verifier"] = verifier
    chain["verifying_inspection"] = graph
    return chain


def _file_and_verify(api, chain):
    """File one 4000.00 REPAIR claim and price it against the damage graph."""
    bond = _bond(api, chain["bond"]["id"])
    claim = file_claim(api, bond, chain["property"]["id"], CLAIMED_DAMAGE)
    verified = attach_verification(
        api,
        claim["id"],
        chain["verifying_inspection"]["id"],
        chain["verifier"]["id"],
    )
    return verified


def _claims_with_status(api, bond_id, status):
    """The rows and total for one bond's claims in a single status."""
    return validate_paginated(
        api.list_damage_claims(MANAGER_HEADERS, bond_id=bond_id, status=status)
    )


class TestRepairCapMoneyConservation:
    """Reserve, release and settle, checking the identity after every request."""

    def test_a_submitted_claim_reserves_nothing(self, api):
        """Filing alone moves no money out of the available bucket.

        PRD 2.8: "`reserved_claim_amount_usd` is the sum of
        `projected_payout_usd` over the bond's claims in status
        `UNDER_ADJUDICATION`" and claims in status "`SUBMITTED`,
        `APPROVED_RETREAT_ONLY`, `DENIED` or `WITHDRAWN` feed neither sum."

        Design: Difficulty/compensating_invariant/repair_cap_money_conservation_across_reserve_release_and_settlement
        """
        chain = _bonded_structure_with_a_damage_graph(api)
        at_issuance = _bond(api, chain["bond"]["id"])
        assert_bond_money(
            at_issuance,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
        )

        claim = file_claim(
            api, at_issuance, chain["property"]["id"], CLAIMED_DAMAGE
        )
        assert_status(claim, CLAIM_SUBMITTED, "damage_claim")
        assert_claim_money(
            claim,
            eligible_damage_usd=0.00,
            deductible_usd=0.00,
            projected_payout_usd=0.00,
            approved_payout_usd=0.00,
        )

        after_filing = _bond(api, chain["bond"]["id"])
        assert_bond_money(
            after_filing,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
        )

    def test_withdrawal_releases_exactly_what_verification_reserved(self, api):
        """The compensating pair leaves the available bucket where it started.

        PRD 3.10: withdrawing from `UNDER_ADJUDICATION` "releases precisely the
        amount that verification reserved: `reserved_claim_amount_usd` falls by
        `projected_payout_usd` and `remaining_repair_cap_usd` rises by the
        identical figure, so `remaining_repair_cap_usd` returns to its exact
        pre-verification value with zero drift."

        Design: Difficulty/compensating_invariant/repair_cap_money_conservation_across_reserve_release_and_settlement
        """
        chain = _bonded_structure_with_a_damage_graph(api)

        verified = _file_and_verify(api, chain)
        assert_status(verified, CLAIM_UNDER_ADJUDICATION, "damage_claim")
        assert verified["exclusion_basis"] == EXCLUSION_AGGREGATE_PRORATION
        assert_claim_money(
            verified,
            eligible_damage_usd=EXPECTED_ELIGIBLE,
            excluded_pre_existing_usd=EXPECTED_EXCLUDED,
            deductible_usd=EXPECTED_DEDUCTIBLE,
            projected_payout_usd=EXPECTED_RESERVE,
        )
        reserved = _bond(api, chain["bond"]["id"])
        assert_bond_money(
            reserved,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=EXPECTED_RESERVE,
            remaining_repair_cap_usd=EXPECTED_REMAINING_WHILE_RESERVED,
        )

        withdrawn = withdraw_claim(api, verified["id"], chain["property"]["id"])
        assert_status(withdrawn, CLAIM_WITHDRAWN, "damage_claim")
        released = _bond(api, chain["bond"]["id"])
        assert_bond_money(
            released,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=EXPECTED_REPAIR_CAP,
        )

    def test_the_released_claim_keeps_its_priced_arithmetic(self, api):
        """The release is achieved by dropping the claim out of the sum.

        PRD 3.10: withdrawing from `UNDER_ADJUDICATION` "also sets
        `approved_payout_usd` to 0.00 and releases precisely the amount that
        verification reserved"; PRD 2.8 counts only claims in status
        `UNDER_ADJUDICATION` towards `reserved_claim_amount_usd`.

        Design: Difficulty/compensating_invariant/repair_cap_money_conservation_across_reserve_release_and_settlement
        """
        chain = _bonded_structure_with_a_damage_graph(api)
        verified = _file_and_verify(api, chain)
        withdraw_claim(api, verified["id"], chain["property"]["id"])

        settled = validate_success(
            api.get_damage_claim(verified["id"], MANAGER_HEADERS)
        )
        assert_status(settled, CLAIM_WITHDRAWN, "damage_claim")
        assert_claim_money(
            settled,
            eligible_damage_usd=EXPECTED_ELIGIBLE,
            excluded_pre_existing_usd=EXPECTED_EXCLUDED,
            deductible_usd=EXPECTED_DEDUCTIBLE,
            projected_payout_usd=EXPECTED_RESERVE,
            approved_payout_usd=0.00,
        )

        _rows, meta = _claims_with_status(
            api, chain["bond"]["id"], CLAIM_UNDER_ADJUDICATION
        )
        assert meta["total_count"] == 0, (
            "no claim backs the reserve once the only priced claim withdrew"
        )
        assert_repair_liability_conserved(_bond(api, chain["bond"]["id"]))

    def test_two_full_reserve_and_release_cycles_leave_no_drift(self, api):
        """Repeating the compensating pair accumulates no residue at all.

        PRD 2.8: "Verification and withdrawal form a compensating pair:
        verification reserves an amount, withdrawal releases exactly that
        amount, so `remaining_repair_cap_usd` returns to its pre-verification
        value with zero drift."

        Design: Difficulty/compensating_invariant/repair_cap_money_conservation_across_reserve_release_and_settlement
        """
        chain = _bonded_structure_with_a_damage_graph(api)
        issued = _bond(api, chain["bond"]["id"])
        baseline = (
            issued["repair_liability_cap_usd"],
            issued["claims_paid_to_date_usd"],
            issued["reserved_claim_amount_usd"],
            issued["remaining_repair_cap_usd"],
        )

        for _cycle in range(2):
            verified = _file_and_verify(api, chain)
            mid = _bond(api, chain["bond"]["id"])
            assert_bond_money(
                mid,
                reserved_claim_amount_usd=EXPECTED_RESERVE,
                remaining_repair_cap_usd=EXPECTED_REMAINING_WHILE_RESERVED,
            )

            withdraw_claim(api, verified["id"], chain["property"]["id"])
            back = _bond(api, chain["bond"]["id"])
            assert (
                back["repair_liability_cap_usd"],
                back["claims_paid_to_date_usd"],
                back["reserved_claim_amount_usd"],
                back["remaining_repair_cap_usd"],
            ) == baseline, "a completed cycle must restore the issued figures exactly"
            assert_repair_liability_conserved(back)

        _rows, meta = _claims_with_status(api, chain["bond"]["id"], CLAIM_WITHDRAWN)
        assert meta["total_count"] == 2, "both cycles left a WITHDRAWN claim behind"

    def test_approval_moves_money_between_buckets_without_touching_the_total(self, api):
        """Settlement debits the reserve, not the available headroom.

        PRD 3.10: on `APPROVE_REPAIR` "`claims_paid_to_date_usd` rises by that
        amount and `reserved_claim_amount_usd` falls by it, while
        `remaining_repair_cap_usd` is left exactly where it was — the money
        moves from reserved to paid, not from available to paid."

        Design: Difficulty/compensating_invariant/repair_cap_money_conservation_across_reserve_release_and_settlement
        """
        chain = _bonded_structure_with_a_damage_graph(api)
        verified = _file_and_verify(api, chain)
        before = _bond(api, chain["bond"]["id"])
        assert_bond_money(
            before,
            claims_paid_to_date_usd=0.00,
            reserved_claim_amount_usd=EXPECTED_RESERVE,
            remaining_repair_cap_usd=EXPECTED_REMAINING_WHILE_RESERVED,
        )

        approved = adjudicate_claim(api, verified["id"], DECISION_APPROVE_REPAIR)
        assert_status(approved, CLAIM_APPROVED_REPAIR, "damage_claim")
        assert_claim_money(approved, approved_payout_usd=EXPECTED_RESERVE)

        after = _bond(api, chain["bond"]["id"])
        assert_bond_money(
            after,
            repair_liability_cap_usd=EXPECTED_REPAIR_CAP,
            claims_paid_to_date_usd=EXPECTED_RESERVE,
            reserved_claim_amount_usd=0.00,
            remaining_repair_cap_usd=EXPECTED_REMAINING_WHILE_RESERVED,
        )
        assert_money(
            after["remaining_repair_cap_usd"], before["remaining_repair_cap_usd"]
        )

        paid_rows, paid_meta = _claims_with_status(
            api, chain["bond"]["id"], CLAIM_APPROVED_REPAIR
        )
        assert paid_meta["total_count"] == 1
        assert_money(
            sum(row["approved_payout_usd"] for row in paid_rows),
            after["claims_paid_to_date_usd"],
        )
        _open_rows, open_meta = _claims_with_status(
            api, chain["bond"]["id"], CLAIM_UNDER_ADJUDICATION
        )
        assert open_meta["total_count"] == 0, (
            "nothing remains to back the 0.00 reserve"
        )

    def test_the_ceiling_is_frozen_across_the_whole_claim_history(self, api):
        """The left-hand side of the identity never moves for the bond's life.

        PRD 2.8: "in every bond status, the bond's `repair_liability_cap_usd`
        equals the sum of `claims_paid_to_date_usd`, `reserved_claim_amount_usd`
        and `remaining_repair_cap_usd` — exact equality on two-decimal values,
        with no tolerance window."

        Design: Difficulty/compensating_invariant/repair_cap_money_conservation_across_reserve_release_and_settlement
        """
        chain = _bonded_structure_with_a_damage_graph(api)
        bond_id = chain["bond"]["id"]
        property_id = chain["property"]["id"]
        checkpoints = []

        def record():
            bond = _bond(api, bond_id)
            assert_money(bond["repair_liability_cap_usd"], EXPECTED_REPAIR_CAP)
            assert_repair_liability_conserved(bond)
            checkpoints.append(
                (
                    bond["claims_paid_to_date_usd"],
                    bond["reserved_claim_amount_usd"],
                    bond["remaining_repair_cap_usd"],
                )
            )

        record()
        first = file_claim(api, _bond(api, bond_id), property_id, CLAIMED_DAMAGE)
        record()
        attach_verification(
            api,
            first["id"],
            chain["verifying_inspection"]["id"],
            chain["verifier"]["id"],
        )
        record()
        withdraw_claim(api, first["id"], property_id)
        record()

        second = _file_and_verify(api, chain)
        record()
        withdraw_claim(api, second["id"], property_id)
        record()

        third = _file_and_verify(api, chain)
        record()
        adjudicate_claim(api, third["id"], DECISION_APPROVE_REPAIR)
        record()

        assert checkpoints == [
            (0.00, 0.00, EXPECTED_REPAIR_CAP),
            (0.00, 0.00, EXPECTED_REPAIR_CAP),
            (0.00, EXPECTED_RESERVE, EXPECTED_REMAINING_WHILE_RESERVED),
            (0.00, 0.00, EXPECTED_REPAIR_CAP),
            (0.00, EXPECTED_RESERVE, EXPECTED_REMAINING_WHILE_RESERVED),
            (0.00, 0.00, EXPECTED_REPAIR_CAP),
            (0.00, EXPECTED_RESERVE, EXPECTED_REMAINING_WHILE_RESERVED),
            (EXPECTED_RESERVE, 0.00, EXPECTED_REMAINING_WHILE_RESERVED),
        ], "the three buckets must follow the reserve/release/settle walk exactly"
        assert_status(_bond(api, bond_id), BOND_ACTIVE, "bond")


CONDUCIVE_CELLS = (
    ("A1", CONDUCIVE_EXCESS_MOISTURE, 2),
    ("B3", CONDUCIVE_WOOD_TO_GROUND, 1),
    ("C5", CONDUCIVE_EXCESS_MOISTURE, 3),
)

# Only EXCESS_MOISTURE is actually notated on the graph; FAULTY_GRADE is not.
WAIVER_CODES = [CONDUCIVE_EXCESS_MOISTURE, CONDUCIVE_FAULTY_GRADE]

EXPECTED_DISTINCT_CODES = 2
EXPECTED_NOTATION_ROWS = 3


def _structure_with_two_distinct_conducive_codes(api):
    """A FL structure whose signed graph carries three cells over two codes."""
    set_clock(api, CLOCK_STARTUP_INSTANT)
    prop, inspector = register_property_and_inspector(api, state_code="FL")
    findings = [
        conducive_finding_payload(grid_ref, code, severity=severity)
        for grid_ref, code, severity in CONDUCIVE_CELLS
    ]
    graph = graphed_inspection(api, prop["id"], inspector["id"], findings)
    plan = completed_liquid_plan(api, prop["id"], graph["id"], inspector["id"])
    return prop, inspector, graph, plan


def _ledger(api, property_id):
    """Read the structure's ledger, checking the count law and the flag."""
    prop = validate_success(api.get_property(property_id, OFFICER_HEADERS))
    assert_conducive_counts_conserved(prop)
    assert prop["active_infestation_on_record"] is False, (
        "recomputing the ledger must not disturb the infestation flag"
    )
    assert prop["waived_conducive_condition_count"] >= 0
    assert prop["open_conducive_condition_count"] >= 0
    assert (
        prop["open_conducive_condition_count"]
        <= prop["total_conducive_condition_count"]
    ), "the open count can never exceed the total"
    return prop


def _counts(prop):
    """The ledger as a (total, waived, open) triple."""
    return (
        prop["total_conducive_condition_count"],
        prop["waived_conducive_condition_count"],
        prop["open_conducive_condition_count"],
    )


def _issue_waived_bond(api, property_id, plan_id):
    """Issue the bond that waives one present code and one absent code."""
    set_clock(api, BOND_ISSUE_INSTANT)
    return issue_bond(
        api,
        property_id,
        plan_id,
        coverage_tier=TIER_REPAIR_AND_RETREAT,
        conducive_waiver_codes=WAIVER_CODES,
    )


class TestConduciveCountConservation:
    """Issuance suppresses and termination restores, with the total frozen."""

    def test_the_ledger_counts_distinct_codes_not_notation_rows(self, api):
        """Two cells sharing one code collapse into a single counted condition.

        PRD 3.1: "the distinct `conducive_code` values are collected over that
        graph's cell notations whose `finding_type` is `CONDUCIVE_CONDITION` ...
        the number of distinct codes found is `total_conducive_condition_count`";
        PRD 3.3 counts the graph's own `conducive_condition_count` "per row
        rather than per distinct code."

        Design: Difficulty/compensating_invariant/conducive_condition_count_conservation_across_waiver_and_termination
        """
        prop, _inspector, graph, _plan = _structure_with_two_distinct_conducive_codes(
            api
        )

        assert graph["conducive_condition_count"] == EXPECTED_NOTATION_ROWS, (
            "the graph rollup counts rows, so A1 and C5 both count"
        )
        ledger = _ledger(api, prop["id"])
        assert _counts(ledger) == (EXPECTED_DISTINCT_CODES, 0, EXPECTED_DISTINCT_CODES), (
            "with no bond of record the two distinct codes are all open"
        )

        _rows, meta = validate_paginated(
            api.list_findings(
                graph["id"], OFFICER_HEADERS, finding_type=FINDING_CONDUCIVE_CONDITION
            )
        )
        assert meta["total_count"] == EXPECTED_NOTATION_ROWS

    def test_issuance_waives_only_the_codes_actually_present_on_the_graph(self, api):
        """A waiver for an absent code suppresses nothing at all.

        PRD 3.1: "The number of the structure's distinct conducive codes that
        also appear in that bond's `conducive_waiver_codes` array is
        `waived_conducive_condition_count`"; PRD 3.7 adds that the waived codes
        "move out of `open_conducive_condition_count` and into
        `waived_conducive_condition_count` on the spot, leaving
        `total_conducive_condition_count` untouched."

        Design: Difficulty/compensating_invariant/conducive_condition_count_conservation_across_waiver_and_termination
        """
        prop, _inspector, _graph, plan = _structure_with_two_distinct_conducive_codes(
            api
        )
        before = _ledger(api, prop["id"])

        bond = _issue_waived_bond(api, prop["id"], plan["id"])
        assert_status(bond, BOND_ACTIVE, "bond")
        assert sorted(bond["conducive_waiver_codes"]) == sorted(WAIVER_CODES)

        after = _ledger(api, prop["id"])
        assert _counts(after) == (EXPECTED_DISTINCT_CODES, 1, 1), (
            "only the intersection is suppressed, so FAULTY_GRADE waives nothing"
        )
        assert (
            after["total_conducive_condition_count"]
            == before["total_conducive_condition_count"]
        ), "issuance must leave the total untouched"

    def test_lapsing_does_not_release_the_suppression(self, api):
        """A lapsed bond is still the structure's bond of record.

        PRD 3.1: the bond of record is "the single bond on that structure whose
        status is `ACTIVE` or `LAPSED`, of which at most one may ever exist."

        Design: Difficulty/compensating_invariant/conducive_condition_count_conservation_across_waiver_and_termination
        """
        prop, _inspector, _graph, plan = _structure_with_two_distinct_conducive_codes(
            api
        )
        bond = _issue_waived_bond(api, prop["id"], plan["id"])

        set_clock(api, LAPSE_REVIEW_INSTANT)
        lapsed = review_bond_term(api, bond["id"])
        assert_status(lapsed, BOND_LAPSED, "bond")

        ledger = _ledger(api, prop["id"])
        assert _counts(ledger) == (EXPECTED_DISTINCT_CODES, 1, 1), (
            "lapsing changes no count because the suppressor is still of record"
        )

    def test_termination_restores_the_open_count_exactly(self, api):
        """Removing the suppressor returns the ledger to its pre-bond shape.

        PRD 3.8: on `LAPSED → TERMINATED` "the covered structure's
        `waived_conducive_condition_count` returns to 0 with
        `open_conducive_condition_count` restored to the full
        `total_conducive_condition_count`, because a terminated bond's
        `conducive_waiver_codes` no longer suppress anything."

        Design: Difficulty/compensating_invariant/conducive_condition_count_conservation_across_waiver_and_termination
        """
        prop, _inspector, graph, plan = _structure_with_two_distinct_conducive_codes(api)
        pristine = _counts(_ledger(api, prop["id"]))
        bond = _issue_waived_bond(api, prop["id"], plan["id"])

        set_clock(api, LAPSE_REVIEW_INSTANT)
        review_bond_term(api, bond["id"])
        set_clock(api, TERMINATION_REVIEW_INSTANT)
        terminated = review_bond_term(api, bond["id"])
        assert_status(terminated, BOND_TERMINATED, "bond")

        restored = _ledger(api, prop["id"])
        assert _counts(restored) == pristine, (
            "the restoration is exact, leaving no residue in the waived bucket"
        )
        assert _counts(restored) == (EXPECTED_DISTINCT_CODES, 0, EXPECTED_DISTINCT_CODES)

        rows, meta = validate_paginated(
            api.list_findings(
                graph["id"], OFFICER_HEADERS, finding_type=FINDING_CONDUCIVE_CONDITION
            )
        )
        assert meta["total_count"] == EXPECTED_NOTATION_ROWS, (
            "the restoration is driven by the bond, not by editing the graph"
        )
        assert sorted(row["conducive_code"] for row in rows) == sorted(
            code for _grid_ref, code, _severity in CONDUCIVE_CELLS
        )

    def test_the_total_never_moves_while_its_two_components_swap(self, api):
        """One unit crosses back and forth between waived and open.

        PRD 2.8: "`open_conducive_condition_count` plus
        `waived_conducive_condition_count` always equals
        `total_conducive_condition_count`. Bond issuance and bond termination
        form that pair — issuance suppresses the waived conditions, termination
        restores them — and the total is untouched by either."

        Design: Difficulty/compensating_invariant/conducive_condition_count_conservation_across_waiver_and_termination
        """
        prop, _inspector, _graph, plan = _structure_with_two_distinct_conducive_codes(
            api
        )
        walk = [_counts(_ledger(api, prop["id"]))]

        bond = _issue_waived_bond(api, prop["id"], plan["id"])
        walk.append(_counts(_ledger(api, prop["id"])))

        set_clock(api, LAPSE_REVIEW_INSTANT)
        review_bond_term(api, bond["id"])
        walk.append(_counts(_ledger(api, prop["id"])))

        set_clock(api, TERMINATION_REVIEW_INSTANT)
        review_bond_term(api, bond["id"])
        walk.append(_counts(_ledger(api, prop["id"])))

        assert walk == [
            (EXPECTED_DISTINCT_CODES, 0, EXPECTED_DISTINCT_CODES),
            (EXPECTED_DISTINCT_CODES, 1, 1),
            (EXPECTED_DISTINCT_CODES, 1, 1),
            (EXPECTED_DISTINCT_CODES, 0, EXPECTED_DISTINCT_CODES),
        ], "the conserved total is 2 at every checkpoint: %r" % (walk,)
