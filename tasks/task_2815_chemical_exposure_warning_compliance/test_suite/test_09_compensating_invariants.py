"""Actions that must undo each other exactly, proved by returning to the same value.

A void that unwinds an executed settlement to the cent, a quantity edit driven
away and back, and a flag-and-remediate loop whose counter ratchets while its
roll-up does not move.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    assert_load,
    assert_margin,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    COMPONENT_STATUS_ACTIVE,
    COMPONENT_STATUS_REMOVED,
    DEFAULT_CLOCK,
    NOTICE_SETTLEMENT_NEGOTIATION,
    PLACEMENT_IMPLEMENTED,
    PLACEMENT_NON_COMPLIANT,
    POSTURE_ENFORCEMENT_HOLD,
    POSTURE_EXPOSURE_UNKNOWN,
    POSTURE_WARNING_ACTIVE,
    POSTURE_WARNING_REQUIRED,
    REQUIRED_CHANNEL_LABEL,
    ROUTE_DERMAL,
    SETTLEMENT_EXECUTED,
    SETTLEMENT_PROPOSED,
    SETTLEMENT_VOID,
)
from test_helpers.fixtures import (
    add_component,
    build_warned_product,
    escalate_notice_to_negotiation,
    execute_settlement,
    make_benzene,
    make_bpa,
    make_notice,
    make_product,
    make_supplied_material,
    make_supplier,
    propose_settlement,
    read_product,
    set_clock,
    void_settlement,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    LABELING_SPECIALIST,
    LS_1,
    REGULATORY_COUNSEL,
)


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def priced_settlement(api):
    """A PROPOSED settlement on a component-free product, priced at 2,000,000 cents.

    The product has zero components, so the warranty defence cannot apply and
    `mitigation_factor` is exactly 1.0; the notice was escalated rather than
    cured, so the cure factor does not apply either.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_benzene(api)
    product = make_product(
        api, "SKU-CI1", product_name="Solvent Wipe", annual_units=4000
    )
    notice = make_notice(api, product["id"], chemical["id"])
    notice = escalate_notice_to_negotiation(api, notice["id"])
    settlement = propose_settlement(
        api, notice["id"], 300000, reformulation_commitment=False
    )
    return {
        "chemical": chemical,
        "product": read_product(api, product["id"], REGULATORY_COUNSEL),
        "notice": notice,
        "settlement": settlement,
    }


@pytest.fixture
def two_material_load_product(api):
    """Two listed chemicals in two materials, each 0.37 g in one finished unit.

    Per-pair contributions round to three decimals first: 12.345 x 0.37 is
    4.568 and 6.789 x 0.37 is 2.512, so the conserved total is 7.080.
    """
    set_clock(api, DEFAULT_CLOCK)
    bpa = make_bpa(api)
    benzene = make_benzene(api)
    supplier = make_supplier(api, "Northgate Polymers")
    first = make_supplied_material(
        api,
        bpa["id"],
        declared_concentration_ppm=12.345,
        material_code="RM-100",
        supplier_id=supplier["id"],
    )
    second = make_supplied_material(
        api,
        benzene["id"],
        declared_concentration_ppm=6.789,
        material_code="RM-200",
        supplier_id=supplier["id"],
    )
    product = make_product(
        api, "SKU-CI2", product_name="Garden Hose", annual_units=50000
    )
    component_a = add_component(api, product["id"], first["material"]["id"], 0.37, 0.5)
    component_b = add_component(api, product["id"], second["material"]["id"], 0.37, 0.5)
    return {
        "bpa": bpa,
        "benzene": benzene,
        "component_a": component_a,
        "component_b": component_b,
        "product": read_product(api, product["id"]),
    }


@pytest.fixture
def covered_label_product(api):
    """A product whose single required LABEL channel is covered by an IMPLEMENTED placement."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    bundle = build_warned_product(
        api,
        chemical["id"],
        sku="SKU-CI3",
        route=ROUTE_DERMAL,
        channel=REQUIRED_CHANNEL_LABEL,
        product_overrides={"product_name": "Tool Grip", "annual_units": 50000},
    )
    bundle["chemical"] = chemical
    return bundle


def _read_settlement(api, settlement_id):
    return get_success_data(api.get_settlement(settlement_id, REGULATORY_COUNSEL))


def _read_notice(api, notice_id):
    return get_success_data(api.get_notice(notice_id, REGULATORY_COUNSEL))


def _read_component(api, component_id):
    return get_success_data(api.get_component(component_id, COMPLIANCE_ANALYST))


def _read_determination(api, determination_id):
    return get_success_data(
        api.get_determination(determination_id, COMPLIANCE_ANALYST)
    )


def _read_placement(api, placement_id):
    return get_success_data(api.get_placement(placement_id, COMPLIANCE_ANALYST))


def _patch_component(api, component_id, **fields):
    return get_success_data(
        api.patch_component(component_id, dict(fields), COMPLIANCE_ANALYST)
    )


def _remove_component(api, component_id):
    return get_success_data(
        api.component_transition(
            component_id, f.action_payload("REMOVE"), COMPLIANCE_ANALYST
        )
    )


def _flag(api, placement_id):
    return get_success_data(
        api.placement_transition(
            placement_id, f.action_payload("FLAG_NON_COMPLIANT"), REGULATORY_COUNSEL
        )
    )


def _remediate(api, placement_id):
    return get_success_data(
        api.placement_transition(
            placement_id, f.action_payload("REMEDIATE"), LABELING_SPECIALIST
        )
    )


def _load_of(api, product_id):
    return read_product(api, product_id)["total_listed_chemical_load_ug"]


# ─────────────────────────────────────────────────────────────────────────────
# The void unwinds the execution to the cent
# ─────────────────────────────────────────────────────────────────────────────


class TestSettlementVoidRestoresTheProduct:
    def test_the_settlement_is_priced_by_the_pinned_waterfall(
        self, api, priced_settlement
    ):
        """The unit measure is the lesser one, so every later step keys on 2,000,000 cents.

        PRD: "Step two computes `base_penalty_cents` as the **lesser** of two statutory measures: a day-based measure of two hundred and fifty thousand cents (2,500 dollars) per day of violation multiplied by `violation_days`, and a unit-based measure of five hundred cents (5 dollars) per unit multiplied by the notice's `alleged_units`."

        Design: Difficulty/compensating_invariant/settlement_void_restores_accrued_penalty_and_open_notice_count
        """
        settlement = priced_settlement["settlement"]
        assert_status(settlement, SETTLEMENT_PROPOSED)
        assert settlement["violation_days"] == 61
        assert_cents(settlement["base_penalty_cents"], 2000000, "base_penalty_cents")
        assert_margin(settlement["mitigation_factor"], 1.0)
        assert_cents(
            settlement["adjusted_penalty_cents"], 2000000, "adjusted_penalty_cents"
        )
        assert_cents(settlement["fee_cap_cents"], 1200000, "fee_cap_cents")
        assert_cents(settlement["allowed_fees_cents"], 300000, "allowed_fees_cents")
        assert_cents(settlement["state_share_cents"], 1500000, "state_share_cents")
        assert_cents(
            settlement["noticing_party_share_cents"],
            500000,
            "noticing_party_share_cents",
        )
        assert_cents(
            settlement["total_settlement_cents"], 2300000, "total_settlement_cents"
        )

    def test_execution_charges_the_penalty_and_closes_the_notice(
        self, api, priced_settlement
    ):
        """All three cascade levels fire: the money, the open count, and the posture.

        PRD: "On success, `executed_by_user_id` and `executed_at` are stamped, and the cascade runs: at level one the product's `accrued_penalty_cents` increases by this settlement's `adjusted_penalty_cents`; at level two, because this settlement reached `EXECUTED`, its notice transitions `SETTLEMENT_NEGOTIATION → SETTLED` and the product's `open_notice_count` decrements by 1; at level three, because `open_notice_count` changed, `compliance_posture` is recomputed and leaves `ENFORCEMENT_HOLD` when the count reaches 0."

        Design: Difficulty/compensating_invariant/settlement_void_restores_accrued_penalty_and_open_notice_count
        """
        bundle = priced_settlement
        before = bundle["product"]
        assert_cents(before["accrued_penalty_cents"], 0, "accrued_penalty_cents")
        assert before["open_notice_count"] == 1
        assert_posture(before, POSTURE_ENFORCEMENT_HOLD)

        executed = execute_settlement(api, bundle["settlement"]["id"])
        assert_status(executed, SETTLEMENT_EXECUTED)

        after = read_product(api, bundle["product"]["id"], REGULATORY_COUNSEL)
        assert_cents(
            after["accrued_penalty_cents"], 2000000, "accrued_penalty_cents"
        )
        assert after["open_notice_count"] == 0
        assert_posture(after, POSTURE_EXPOSURE_UNKNOWN)

    def test_voiding_restores_the_penalty_and_reopens_the_notice(
        self, api, priced_settlement
    ):
        """The accrued penalty returns to exactly 0, not to a residue of the same size.

        PRD: "It reverses every effect execution applied: the product's `accrued_penalty_cents` decreases by the same `adjusted_penalty_cents`, restoring the pre-execution value exactly with no drift; the notice transitions `SETTLED → SETTLEMENT_NEGOTIATION` and `open_notice_count` increments by 1; and `compliance_posture` is recomputed."

        Design: Difficulty/compensating_invariant/settlement_void_restores_accrued_penalty_and_open_notice_count
        """
        bundle = priced_settlement
        execute_settlement(api, bundle["settlement"]["id"])
        voided = void_settlement(api, bundle["settlement"]["id"])
        assert_status(voided, SETTLEMENT_VOID)

        product = read_product(api, bundle["product"]["id"], REGULATORY_COUNSEL)
        assert_cents(product["accrued_penalty_cents"], 0, "accrued_penalty_cents")
        assert product["open_notice_count"] == 1
        assert_posture(product, POSTURE_ENFORCEMENT_HOLD)

        notice = _read_notice(api, bundle["notice"]["id"])
        assert_status(notice, NOTICE_SETTLEMENT_NEGOTIATION)
        assert notice["cure_attempted"] is False

    def test_the_derived_counters_agree_with_their_definitions_after_the_cycle(
        self, api, priced_settlement
    ):
        """No settlement is EXECUTED and one notice is open, so the counters must read 0 and 1.

        PRD: "`accrued_penalty_cents` on a product is, by construction, the sum of `adjusted_penalty_cents` over every settlement in status `EXECUTED` whose `notice_id` points at a notice of that product, and `open_notice_count` is the number of notices of that product whose status is one of `RECEIVED`, `UNDER_EVALUATION`, `CURE_ELECTED`, `CURE_FAILED`, `SETTLEMENT_NEGOTIATION` or `LITIGATION`."

        Design: Difficulty/compensating_invariant/settlement_void_restores_accrued_penalty_and_open_notice_count
        """
        bundle = priced_settlement
        execute_settlement(api, bundle["settlement"]["id"])
        void_settlement(api, bundle["settlement"]["id"])

        settlement = _read_settlement(api, bundle["settlement"]["id"])
        assert_status(settlement, SETTLEMENT_VOID)
        assert (
            settlement["state_share_cents"] + settlement["noticing_party_share_cents"]
            == settlement["adjusted_penalty_cents"]
        )

        product = read_product(api, bundle["product"]["id"], REGULATORY_COUNSEL)
        assert_cents(product["accrued_penalty_cents"], 0, "accrued_penalty_cents")
        assert product["open_notice_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# The chemical load is conserved across a quantity round trip
# ─────────────────────────────────────────────────────────────────────────────


class TestChemicalLoadRoundTrip:
    def test_the_baseline_total_is_the_sum_of_two_rounded_terms(
        self, api, two_material_load_product
    ):
        """4.568 plus 2.512 is 7.080 — each term is rounded before the sum, not after.

        PRD: "Those rounded per-pair terms are then summed, and the sum is rounded half up to three decimal places."

        Design: Difficulty/compensating_invariant/component_quantity_roundtrip_conserves_total_chemical_load
        """
        bundle = two_material_load_product
        assert_load(bundle["product"]["total_listed_chemical_load_ug"], 7.08)
        assert_posture(bundle["product"], POSTURE_EXPOSURE_UNKNOWN)

    def test_a_quantity_driven_away_and_back_lands_on_the_identical_total(
        self, api, two_material_load_product
    ):
        """0.37 to 0.7101 to 0.37 returns to 7.080 with no accumulated drift.

        PRD: "Because the rounding order is pinned in exactly this way, the quantity is conserved: setting a component's `quantity_grams_per_unit` to some value and then back to its original restores the identical three-decimal total with no accumulated drift."

        Design: Difficulty/compensating_invariant/component_quantity_roundtrip_conserves_total_chemical_load
        """
        bundle = two_material_load_product
        product_id = bundle["product"]["id"]
        _patch_component(
            api, bundle["component_a"]["id"], quantity_grams_per_unit=0.7101
        )
        assert_load(_load_of(api, product_id), 11.278)

        _patch_component(api, bundle["component_a"]["id"], quantity_grams_per_unit=0.37)
        assert_load(_load_of(api, product_id), 7.08)

    def test_editing_the_contact_factor_does_not_move_the_load(
        self, api, two_material_load_product
    ):
        """Only the quantity multiplies the concentration, so a contact-factor edit is neutral.

        PRD: "For each such chemical-and-component pair the server evaluates the modelled effective concentration of that chemical in that component's material — the roll-up described in Section 3.5, always under the modelled variant regardless of any assessment — multiplies it by that component's `quantity_grams_per_unit`, and rounds the product half up to three decimal places."

        Design: Difficulty/compensating_invariant/component_quantity_roundtrip_conserves_total_chemical_load
        """
        bundle = two_material_load_product
        patched = _patch_component(api, bundle["component_a"]["id"], contact_factor=0.9)
        assert patched["contact_factor"] == pytest.approx(0.9, abs=1e-9)
        assert_status(patched, COMPONENT_STATUS_ACTIVE)
        assert_load(_load_of(api, bundle["product"]["id"]), 7.08)

    def test_removing_one_component_leaves_exactly_the_other_term(
        self, api, two_material_load_product
    ):
        """A REMOVED component contributes nothing, so 7.080 falls to A's own 4.568.

        PRD: "Removing a component takes it `ACTIVE → REMOVED` and excludes it from every exposure and load calculation from that instant on; a product whose last `ACTIVE` component is removed falls back to `EXPOSURE_UNKNOWN` through clause 2 of the posture ladder."

        Design: Difficulty/compensating_invariant/component_quantity_roundtrip_conserves_total_chemical_load
        """
        bundle = two_material_load_product
        removed = _remove_component(api, bundle["component_b"]["id"])
        assert_status(removed, COMPONENT_STATUS_REMOVED)
        assert_load(_load_of(api, bundle["product"]["id"]), 4.568)
        assert_status(
            _read_component(api, bundle["component_a"]["id"]), COMPONENT_STATUS_ACTIVE
        )


# ─────────────────────────────────────────────────────────────────────────────
# The remediation loop ratchets its counter and restores its roll-up
# ─────────────────────────────────────────────────────────────────────────────


class TestPlacementRemediationCycle:
    def test_the_single_covered_channel_is_full_coverage(
        self, api, covered_label_product
    ):
        """One IMPLEMENTED placement covering the clock satisfies the only required channel.

        PRD: "`covered_channel_count` is the number of distinct entries of `required_channels` for which at least one placement of this determination has a `status` of `IMPLEMENTED` or `VERIFIED` and an effective window that covers the current logical clock."

        Design: Difficulty/compensating_invariant/placement_remediation_cycle_conserves_covered_channel_count
        """
        bundle = covered_label_product
        determination = _read_determination(api, bundle["determination"]["id"])
        assert determination["required_channels"] == [REQUIRED_CHANNEL_LABEL]
        assert determination["covered_channel_count"] == 1
        assert_status(bundle["placement"], PLACEMENT_IMPLEMENTED)
        assert bundle["placement"]["remediation_count"] == 0
        assert_posture(bundle["product"], POSTURE_WARNING_ACTIVE)

    def test_flagging_the_placement_drops_the_coverage_and_the_posture(
        self, api, covered_label_product
    ):
        """With no covered channel left, clause 3 fails and the ladder falls through to clause 4.

        PRD: "4. **`WARNING_REQUIRED`** — clauses 1 through 3 do not apply, and some exposure assessment of this product in status `FINAL` has a `result` of `AT_OR_ABOVE_SAFE_HARBOR` or `NO_SAFE_HARBOR`."

        Design: Difficulty/compensating_invariant/placement_remediation_cycle_conserves_covered_channel_count
        """
        bundle = covered_label_product
        flagged = _flag(api, bundle["placement"]["id"])
        assert_status(flagged, PLACEMENT_NON_COMPLIANT)
        assert (
            _read_determination(api, bundle["determination"]["id"])[
                "covered_channel_count"
            ]
            == 0
        )
        assert_posture(
            read_product(api, bundle["product"]["id"]), POSTURE_WARNING_REQUIRED
        )

    def test_remediation_counts_the_round_and_restores_the_coverage(
        self, api, covered_label_product
    ):
        """remediation_count reaches 1 while covered_channel_count returns to its pre-flag 1.

        PRD: "A `LabelingSpecialist` then remediates, taking it `NON_COMPLIANT → IMPLEMENTED`, incrementing `remediation_count` by 1 and again requiring the parent determination to be `APPROVED`; this closes the `IMPLEMENTED → VERIFIED → NON_COMPLIANT → IMPLEMENTED` cycle, and the compensating invariant is that `covered_channel_count` returns to its pre-flag value."

        Design: Difficulty/compensating_invariant/placement_remediation_cycle_conserves_covered_channel_count
        """
        bundle = covered_label_product
        _flag(api, bundle["placement"]["id"])
        remediated = _remediate(api, bundle["placement"]["id"])
        assert_status(remediated, PLACEMENT_IMPLEMENTED)
        assert remediated["remediation_count"] == 1
        assert (
            _read_determination(api, bundle["determination"]["id"])[
                "covered_channel_count"
            ]
            == 1
        )
        assert_posture(
            read_product(api, bundle["product"]["id"]), POSTURE_WARNING_ACTIVE
        )

    def test_a_second_loop_ratchets_the_counter_but_not_the_coverage(
        self, api, covered_label_product
    ):
        """After two full loops the count is 2, the coverage is 1, and the implementer is unchanged.

        PRD: "Every one of these five placement actions recomputes the determination's `covered_channel_count` and the product's `compliance_posture`, and increments the placement's `version` by 1 and the product's `version` by 1."

        Design: Difficulty/compensating_invariant/placement_remediation_cycle_conserves_covered_channel_count
        """
        bundle = covered_label_product
        placement_id = bundle["placement"]["id"]
        _flag(api, placement_id)
        _remediate(api, placement_id)
        _flag(api, placement_id)
        second = _remediate(api, placement_id)

        assert_status(second, PLACEMENT_IMPLEMENTED)
        assert second["remediation_count"] == 2
        assert second["implemented_by_user_id"] == LS_1
        assert (
            _read_determination(api, bundle["determination"]["id"])[
                "covered_channel_count"
            ]
            == 1
        )
        assert_posture(
            read_product(api, bundle["product"]["id"]), POSTURE_WARNING_ACTIVE
        )
        assert_status(_read_placement(api, placement_id), PLACEMENT_IMPLEMENTED)
