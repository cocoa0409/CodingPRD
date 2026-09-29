"""Enforcement gates: the notice version guard, the negotiation round ceiling,
the violation window, the indemnity cap and the blocked settlement unwind.

Each case pairs a refusal with the neighbouring acceptance so the rule is shown
to hang on exactly one condition: the same settlement create succeeds once the
notice is negotiable and the version is fresh, the same COUNTER succeeds one
round earlier, the same create succeeds one day later on the clock, the same
ACCEPT_EXECUTE succeeds when the warranty defence was never taken, and the same
VOID succeeds when no COMPLETED reformulation project delivered the promise.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INDEMNITY_CAP_EXCEEDED,
    ERR_NOTICE_NOT_NEGOTIABLE,
    ERR_NO_VIOLATION_WINDOW,
    ERR_SETTLEMENT_NOT_VOIDABLE,
    ERR_SETTLEMENT_ROUND_LIMIT,
    ERR_STALE_NOTICE_VERSION,
)
from test_helpers.assertions import (
    assert_cents,
    assert_close,
    assert_concentration,
    assert_exposure,
    assert_fields_null,
    assert_instant,
    assert_money_waterfall,
    assert_posture,
    assert_shares_reconcile,
    assert_status,
)
from test_helpers.constants import (
    ASSESSMENT_SUPERSEDED,
    BASIS_SUPPLIER_DECLARED,
    DEFAULT_CLOCK,
    LINK_STATUS_DECLARED,
    MAX_SETTLEMENT_ROUNDS,
    METHOD_MODELED,
    NOTICE_LITIGATION,
    NOTICE_SETTLED,
    NOTICE_SETTLEMENT_NEGOTIATION,
    NOTICE_UNDER_EVALUATION,
    POSTURE_ENFORCEMENT_HOLD,
    PROJECT_COMPLETED,
    ROUTE_ORAL,
    SETTLEMENT_COUNTERED,
    SETTLEMENT_EXECUTED,
    SETTLEMENT_PROPOSED,
    SETTLEMENT_VOID,
)
from test_helpers.fixtures import (
    add_component,
    escalate_notice_to_negotiation,
    evaluate_notice,
    execute_settlement,
    make_benzene,
    make_bpa,
    make_final_assessment,
    make_material,
    make_notice,
    make_product,
    make_reformulation_project,
    make_supplied_material,
    make_warranted_supplier,
    propose_settlement,
    read_product,
    set_clock,
    submit_reformulation_verification,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    RC_1,
    RC_2,
    REGULATORY_COUNSEL,
    REGULATORY_COUNSEL_2,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _propose(api, notice_id, fees, expected_notice_version, commitment=f.OMIT):
    """The raw settlement create, so a refusal can be inspected."""
    return api.create_settlement(
        notice_id,
        f.settlement_payload(fees, expected_notice_version, commitment),
        REGULATORY_COUNSEL,
    )


def _move(api, settlement_id, action, headers=REGULATORY_COUNSEL):
    return api.settlement_transition(settlement_id, f.action_payload(action), headers)


def _notice_move(api, notice_id, action, headers=REGULATORY_COUNSEL):
    return api.notice_transition(notice_id, f.action_payload(action), headers)


def _read_notice(api, notice_id):
    return get_success_data(api.get_notice(notice_id, REGULATORY_COUNSEL))


def _read_settlement(api, settlement_id):
    return get_success_data(api.get_settlement(settlement_id, REGULATORY_COUNSEL))


def _read_project(api, project_id):
    return get_success_data(
        api.get_reformulation_project(project_id, COMPLIANCE_ANALYST)
    )


def _read_link(api, link_id):
    return get_success_data(api.get_material_chemical(link_id, COMPLIANCE_ANALYST))


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _settlement_count(api, notice_id):
    _, meta = validate_paginated(
        api.list_settlements(REGULATORY_COUNSEL, f.page(notice_id=notice_id))
    )
    return meta["total_count"]


def _project_count(api, product_id):
    _, meta = validate_paginated(
        api.list_reformulation_projects(
            COMPLIANCE_ANALYST, f.page(product_id=product_id)
        )
    )
    return meta["total_count"]


def _exhaust_rounds(api, settlement_id):
    """COUNTER, REVISE, COUNTER — the alternating walk up to the ceiling."""
    return [
        get_success_data(_move(api, settlement_id, "COUNTER", REGULATORY_COUNSEL_2)),
        get_success_data(_move(api, settlement_id, "REVISE", REGULATORY_COUNSEL)),
        get_success_data(_move(api, settlement_id, "COUNTER", REGULATORY_COUNSEL_2)),
    ]


def _noticed(api, product_id, chemical_id, alleged_units=4000):
    """A notice served 2026-07-01 alleging violations from 2026-05-01."""
    return make_notice(
        api,
        product_id,
        chemical_id,
        "2026-05-01T00:00:00Z",
        "2026-07-01T00:00:00Z",
        alleged_units=alleged_units,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clocked(api):
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def ordering(api, clocked):
    """SKU-ORD's notice sits in UNDER_EVALUATION, one version past intake.

    ``stale_version`` is the version the client read at intake, which the
    evaluation action has already advanced past.
    """
    chemical = make_bpa(api)
    product = make_product(
        api, "SKU-ORD", product_name="Ordering Widget", annual_units=1000
    )
    notice = _noticed(api, product["id"], chemical["id"], alleged_units=1000)
    evaluate_notice(api, notice["id"])
    return {
        "chemical": chemical,
        "product": product,
        "notice": notice,
        "stale_version": notice["version"],
    }


@pytest.fixture
def rounds(api, clocked):
    """SKU-ROUNDS is in negotiation with one PROPOSED settlement at round 0."""
    chemical = make_bpa(api)
    product = make_product(
        api, "SKU-ROUNDS", product_name="Rounds Widget", annual_units=1000
    )
    notice = _noticed(api, product["id"], chemical["id"], alleged_units=1000)
    escalate_notice_to_negotiation(api, notice["id"])
    settlement = propose_settlement(api, notice["id"], 200000)
    return {
        "chemical": chemical,
        "product": product,
        "notice": notice,
        "settlement": settlement,
    }


@pytest.fixture
def zero_window(api, clocked):
    """SKU-ZERO's notice was served on the very instant the clock reads.

    ``earliest_violation_date`` equals ``served_at`` equals the logical clock,
    so the notice itself is legal and the priced window is still empty.
    """
    chemical = make_bpa(api)
    product = make_product(
        api, "SKU-ZERO", product_name="Zero Window Widget", annual_units=4000
    )
    notice = make_notice(
        api,
        product["id"],
        chemical["id"],
        DEFAULT_CLOCK,
        DEFAULT_CLOCK,
        alleged_units=4000,
        noticing_party_name="Same Day Advocates",
    )
    escalate_notice_to_negotiation(api, notice["id"])
    return {"chemical": chemical, "product": product, "notice": notice}


@pytest.fixture
def indemnity_pair(api, clocked):
    """Two arms differing only in ``pass_through_warning_obligation``.

    Both suppliers carry an ACTIVE warranty of scope ALL_MATERIALS with the
    same 1000000 indemnity cap and the same open-ended window from 2026-01-01,
    both products sell 4000 units and hold one ACTIVE component of their own
    supplier's material, and both settlements request 500000 in fees.
    """
    chemical = make_bpa(api)
    arms = {"chemical": chemical}
    for key, sku, supplier_name, pass_through in (
        ("a", "SKU-IND-A", "Alpha Warranty Chemicals", True),
        ("b", "SKU-IND-B", "Beta No Passthrough Chemicals", False),
    ):
        supplier = make_warranted_supplier(
            api,
            supplier_name,
            pass_through_warning_obligation=pass_through,
            indemnity_cap_cents=1000000,
        )
        material = make_material(api, "RM-" + key.upper(), supplier["id"])
        product = make_product(
            api, sku, product_name="Indemnity " + key.upper(), annual_units=4000
        )
        add_component(api, product["id"], material["id"], 0.25, 0.5)
        notice = _noticed(api, product["id"], chemical["id"])
        escalate_notice_to_negotiation(api, notice["id"])
        settlement = propose_settlement(api, notice["id"], 500000)
        arms[key] = {
            "supplier": supplier,
            "material": material,
            "product": product,
            "notice": notice,
            "settlement": settlement,
        }
    return arms


@pytest.fixture
def void_pair(api, clocked):
    """Two executed settlements, both promising reformulation; only A delivered.

    SKU-V93A carries one ACTIVE component of RM-V93 (Benzene at 800.0 ppm,
    0.25 g/unit, contact_factor 0.5) whose FINAL modelled ORAL assessment read
    100.000 ug/day, and a reformulation project to 8.0 ppm has been carried all
    the way to COMPLETED. SKU-V93B has no components and no project at all.
    """
    chemical = make_benzene(api)
    supplied = make_supplied_material(
        api,
        chemical["id"],
        800.0,
        material_code="RM-V93",
        supplier_legal_name="Solvent Works",
    )
    product_a = make_product(
        api, "SKU-V93A", product_name="Void Blocked", annual_units=4000
    )
    add_component(api, product_a["id"], supplied["material"]["id"], 0.25, 0.5)
    assessment = make_final_assessment(
        api, product_a["id"], chemical["id"], METHOD_MODELED, ROUTE_ORAL, 1.0
    )
    project = make_reformulation_project(
        api, product_a["id"], chemical["id"], supplied["link"]["id"], 8.0
    )
    submit_reformulation_verification(api, project["id"])
    project = get_success_data(
        api.reformulation_transition(
            project["id"], f.action_payload("COMPLETE"), COMPLIANCE_ANALYST
        )
    )
    product_b = make_product(
        api, "SKU-V93B", product_name="Void Allowed", annual_units=4000
    )

    arms = {
        "chemical": chemical,
        "material": supplied["material"],
        "link": supplied["link"],
        "assessment": assessment,
        "project": project,
    }
    for key, product in (("a", product_a), ("b", product_b)):
        notice = _noticed(api, product["id"], chemical["id"])
        escalate_notice_to_negotiation(api, notice["id"])
        settlement = propose_settlement(
            api, notice["id"], 500000, reformulation_commitment=True
        )
        settlement = execute_settlement(api, settlement["id"])
        arms[key] = {"product": product, "notice": notice, "settlement": settlement}
    return arms


# ─────────────────────────────────────────────────────────────────────────────
# The notice version guard outranks the negotiable-status guard
# ─────────────────────────────────────────────────────────────────────────────


class TestStaleNoticeVersionOutranksNegotiability:
    """One create can break both rules; the concurrency guard reports first."""

    def test_a_stale_version_is_reported_even_though_the_notice_is_not_negotiable(
        self, api, ordering
    ):
        """Both rules are live, and the higher layer is the one that speaks.

        PRD: "If that value does not equal the notice's current `version`, the create is rejected with `ERR_STALE_NOTICE_VERSION` (HTTP 412)."

        PRD: "Both sit above every state and business rule, so a stale version is reported even when the request would also have failed a later check."

        Design: Corner/validations/val_stale_notice_version_reported_before_notice_not_negotiable
        """
        notice_id = ordering["notice"]["id"]
        assert_status(_read_notice(api, notice_id), NOTICE_UNDER_EVALUATION)

        refusal = _propose(api, notice_id, 200000, ordering["stale_version"])
        validate_error(refusal, ERR_STALE_NOTICE_VERSION, 412)
        assert _settlement_count(api, notice_id) == 0, (
            "A refused create must leave no Settlement row behind"
        )

    def test_the_current_version_then_surfaces_the_negotiable_status_guard(
        self, api, ordering
    ):
        """With the concurrency guard satisfied the state rule is what refuses.

        PRD: "The notice must be in status `SETTLEMENT_NEGOTIATION`, otherwise the create is refused with `ERR_NOTICE_NOT_NEGOTIABLE`, and the notice must not already hold a settlement in status `PROPOSED`, `COUNTERED` or `EXECUTED`, otherwise it is refused with `ERR_OPEN_SETTLEMENT_EXISTS`."

        Design: Corner/validations/val_stale_notice_version_reported_before_notice_not_negotiable
        """
        notice_id = ordering["notice"]["id"]
        validate_error(
            _propose(api, notice_id, 200000, ordering["stale_version"]),
            ERR_STALE_NOTICE_VERSION,
            412,
        )

        current = api.notice_version(notice_id, REGULATORY_COUNSEL)
        assert current == ordering["stale_version"] + 1, (
            "The evaluation action increments the notice version by 1, so the "
            f"current version should be {ordering['stale_version'] + 1}, got {current}"
        )

        validate_error(
            _propose(api, notice_id, 200000, current), ERR_NOTICE_NOT_NEGOTIABLE, 409
        )
        assert _settlement_count(api, notice_id) == 0, (
            "Neither refusal may create a Settlement row"
        )

    def test_escalation_with_a_refreshed_version_lets_the_identical_create_through(
        self, api, ordering
    ):
        """The same body succeeds once the notice is negotiable and the read is fresh.

        PRD: "Every action on this surface is reserved to a `RegulatoryCounsel` and increments the notice's `version` by 1 and the product's `version` by 1."

        PRD: "The second branch escalates straight to negotiation, taking the notice `UNDER_EVALUATION → SETTLEMENT_NEGOTIATION` and opening the settlement surface for it."

        PRD: "The create stamps `proposed_by_user_id` from the acting `X-User-ID`, sets `status` to `PROPOSED` with `round_count` 0, voids any earlier `PROPOSED` or `COUNTERED` settlement of the same notice, and increments the notice's `version` by 1."

        Design: Corner/validations/val_stale_notice_version_reported_before_notice_not_negotiable
        """
        notice_id = ordering["notice"]["id"]
        validate_error(
            _propose(api, notice_id, 200000, ordering["stale_version"]),
            ERR_STALE_NOTICE_VERSION,
            412,
        )

        escalated = get_success_data(_notice_move(api, notice_id, "ESCALATE"))
        assert_status(escalated, NOTICE_SETTLEMENT_NEGOTIATION)

        refreshed = api.notice_version(notice_id, REGULATORY_COUNSEL)
        assert refreshed == ordering["stale_version"] + 2, (
            "Evaluation and escalation each bump the notice version by 1, so the "
            f"captured version is stale by two: expected "
            f"{ordering['stale_version'] + 2}, got {refreshed}"
        )

        settlement = get_success_data(_propose(api, notice_id, 200000, refreshed))
        assert_status(settlement, SETTLEMENT_PROPOSED)
        assert settlement["round_count"] == 0, (
            f"A fresh settlement starts at round 0, got {settlement['round_count']!r}"
        )
        assert settlement["proposed_by_user_id"] == RC_1, (
            "proposed_by_user_id is stamped from the acting X-User-ID, expected "
            f"{RC_1!r}, got {settlement['proposed_by_user_id']!r}"
        )
        assert _settlement_count(api, notice_id) == 1

    def test_the_waterfall_prices_the_ninety_two_day_window_against_the_unit_measure(
        self, api, ordering
    ):
        """1000 alleged units cap the penalty far below the day-based measure.

        PRD: "`violation_days` is the number of whole days from the notice's `earliest_violation_date` to the logical clock at the moment the settlement row is created: the elapsed seconds divided by eighty-six thousand four hundred, taken as a floor to a whole number."

        PRD: "Step two computes `base_penalty_cents` as the **lesser** of two statutory measures: a day-based measure of two hundred and fifty thousand cents (2,500 dollars) per day of violation multiplied by `violation_days`, and a unit-based measure of five hundred cents (5 dollars) per unit multiplied by the notice's `alleged_units`."

        PRD: "When it is at least one hundred thousand cents but strictly below one million cents (10,000 dollars), the cap is the adjusted penalty multiplied by 1.00, floored."

        PRD: "Step seven splits the penalty. `state_share_cents` is the adjusted penalty multiplied by 0.75, floored to whole cents — the statutory state share. `noticing_party_share_cents` is `adjusted_penalty_cents` minus `state_share_cents`, so it absorbs the flooring remainder and the two shares sum to exactly `adjusted_penalty_cents`."

        PRD: "Step eight computes `total_settlement_cents` as `adjusted_penalty_cents` plus `allowed_fees_cents`."

        Design: Corner/validations/val_stale_notice_version_reported_before_notice_not_negotiable
        """
        notice_id = ordering["notice"]["id"]
        get_success_data(_notice_move(api, notice_id, "ESCALATE"))
        settlement = propose_settlement(api, notice_id, 200000)

        assert_money_waterfall(
            settlement,
            violation_days=92,
            base_penalty_cents=500000,
            mitigation_factor=1.0000,
            adjusted_penalty_cents=500000,
            fee_cap_cents=500000,
            allowed_fees_cents=200000,
            state_share_cents=375000,
            noticing_party_share_cents=125000,
            total_settlement_cents=700000,
        )
        assert_shares_reconcile(settlement)


# ─────────────────────────────────────────────────────────────────────────────
# The round ceiling counts counters and revisions alike
# ─────────────────────────────────────────────────────────────────────────────


class TestRoundCeilingCountsCounterAndRevise:
    """An alternating COUNTER/REVISE walk exhausts the same ceiling of three."""

    def test_each_move_of_the_alternating_walk_consumes_one_round(
        self, api, rounds
    ):
        """COUNTER, REVISE, COUNTER take round_count from 0 to 3.

        PRD: "A `RegulatoryCounsel` counters, taking the settlement `PROPOSED → COUNTERED`, and revises, taking it `COUNTERED → PROPOSED`."

        PRD: "Both consume a round: each increments `round_count` by 1, both require `round_count` to be strictly below the ceiling of 3 beforehand, and a counter or revision requested on a settlement whose `round_count` already equals 3 is refused with `ERR_SETTLEMENT_ROUND_LIMIT`."

        Design: Corner/validations/val_settlement_round_ceiling_counts_counter_and_revise
        """
        settlement = rounds["settlement"]
        assert_status(settlement, SETTLEMENT_PROPOSED)
        assert settlement["round_count"] == 0

        walk = _exhaust_rounds(api, settlement["id"])
        expected = (
            (SETTLEMENT_COUNTERED, 1),
            (SETTLEMENT_PROPOSED, 2),
            (SETTLEMENT_COUNTERED, 3),
        )
        for row, (status, round_count) in zip(walk, expected):
            assert_status(row, status)
            assert row["round_count"] == round_count, (
                f"Expected round_count {round_count} after this move, got "
                f"{row['round_count']!r}"
            )
        assert walk[-1]["round_count"] == MAX_SETTLEMENT_ROUNDS

    def test_the_frozen_window_is_never_recomputed_by_a_round(self, api, rounds):
        """violation_days and the base penalty it feeds stay exactly as created.

        PRD: "`violation_days` is the number of whole days from the notice's `earliest_violation_date` to the logical clock at the moment the settlement row is created: the elapsed seconds divided by eighty-six thousand four hundred, taken as a floor to a whole number."

        PRD: "Both actions may restate `requested_attorney_fees_cents` and `reformulation_commitment`; when either is supplied it overwrites the stored value and the money fields are recomputed from step three onward in the pinned order — `mitigation_factor`, `adjusted_penalty_cents`, `fee_cap_cents`, `allowed_fees_cents`, `state_share_cents`, `noticing_party_share_cents` and `total_settlement_cents` — while the frozen `violation_days` and the `base_penalty_cents` derived from it are kept as they were."

        Design: Corner/validations/val_settlement_round_ceiling_counts_counter_and_revise
        """
        settlement = rounds["settlement"]
        assert_money_waterfall(
            settlement,
            violation_days=92,
            base_penalty_cents=500000,
            mitigation_factor=1.0000,
            adjusted_penalty_cents=500000,
            fee_cap_cents=500000,
            allowed_fees_cents=200000,
            state_share_cents=375000,
            noticing_party_share_cents=125000,
            total_settlement_cents=700000,
        )

        for row in _exhaust_rounds(api, settlement["id"]):
            assert row["violation_days"] == 92, (
                "A counter or revision never re-prices the frozen window, "
                f"got violation_days {row['violation_days']!r}"
            )
            assert_cents(row["base_penalty_cents"], 500000, "base_penalty_cents")
            assert_cents(
                row["adjusted_penalty_cents"], 500000, "adjusted_penalty_cents"
            )
            assert_shares_reconcile(row)

    def test_the_fourth_move_is_refused_at_the_ceiling(self, api, rounds):
        """A revision requested at round three is refused just as a counter is.

        PRD: "Both consume a round: each increments `round_count` by 1, both require `round_count` to be strictly below the ceiling of 3 beforehand, and a counter or revision requested on a settlement whose `round_count` already equals 3 is refused with `ERR_SETTLEMENT_ROUND_LIMIT`."

        Design: Corner/validations/val_settlement_round_ceiling_counts_counter_and_revise
        """
        settlement_id = rounds["settlement"]["id"]
        _exhaust_rounds(api, settlement_id)

        refusal = _move(api, settlement_id, "REVISE", REGULATORY_COUNSEL)
        validate_error(refusal, ERR_SETTLEMENT_ROUND_LIMIT, 409)

        unchanged = _read_settlement(api, settlement_id)
        assert_status(unchanged, SETTLEMENT_COUNTERED)
        assert unchanged["round_count"] == MAX_SETTLEMENT_ROUNDS, (
            "The refused move may not consume a round, expected round_count "
            f"{MAX_SETTLEMENT_ROUNDS}, got {unchanged['round_count']!r}"
        )
        assert_cents(
            unchanged["adjusted_penalty_cents"], 500000, "adjusted_penalty_cents"
        )

    def test_litigation_is_the_escape_at_exactly_the_ceiling(self, api, rounds):
        """Exhausted negotiation is what unlocks LITIGATE, and it voids the row.

        PRD: "Litigation, taking the notice `SETTLEMENT_NEGOTIATION → LITIGATION`, is available only when some settlement of this notice has a `round_count` equal to the ceiling of 3 — negotiation must be genuinely exhausted first — and it voids every settlement of the notice whose status is `PROPOSED` or `COUNTERED`."

        Design: Corner/validations/val_settlement_round_ceiling_counts_counter_and_revise
        """
        settlement_id = rounds["settlement"]["id"]
        notice_id = rounds["notice"]["id"]
        _exhaust_rounds(api, settlement_id)

        litigated = get_success_data(_notice_move(api, notice_id, "LITIGATE"))
        assert_status(litigated, NOTICE_LITIGATION)
        assert_status(_read_settlement(api, settlement_id), SETTLEMENT_VOID)


# ─────────────────────────────────────────────────────────────────────────────
# The violation window is measured against the clock, not against service
# ─────────────────────────────────────────────────────────────────────────────


class TestZeroViolationWindowRefusesTheCreate:
    """A legal notice can still have nothing to price on the day it is served."""

    def test_the_notice_itself_is_legal_and_carries_the_sixty_day_cure_window(
        self, api, zero_window
    ):
        """earliest_violation_date equal to served_at passes the interval check.

        PRD: "Two temporal sanity checks apply and both report `ERR_INVALID_INTERVAL`: `earliest_violation_date` may not be later than `served_at`, and `served_at` may not be later than the current logical clock — a notice cannot have been served in the future."

        PRD: "Intake computes `cure_deadline_at` as `served_at` plus a cure window of exactly sixty days, that is sixty times eighty-six thousand four hundred seconds, and the window is **inclusive** of that instant."

        PRD: "The evaluation action takes the notice `RECEIVED → UNDER_EVALUATION` and computes `cure_eligible` from four conditions that must **all** hold."

        Design: Corner/validations/val_settlement_create_with_zero_violation_window_rejected
        """
        notice = _read_notice(api, zero_window["notice"]["id"])
        assert_status(notice, NOTICE_SETTLEMENT_NEGOTIATION)
        assert_instant(
            notice["cure_deadline_at"], "2026-09-30T00:00:00Z", "cure_deadline_at"
        )
        assert notice["cure_eligible"] is True, (
            "A private-party failure-to-warn notice on a product selling 4000 "
            "units a year with no executed settlement in the quiet period is "
            f"curable, got cure_eligible {notice['cure_eligible']!r}"
        )

    def test_a_zero_day_window_is_refused_at_create(self, api, zero_window):
        """Nothing has elapsed since the alleged violations began.

        PRD: "If the computed `violation_days` is zero or negative at create time there is no penalty window to price, and the create is refused with `ERR_NO_VIOLATION_WINDOW`."

        Design: Corner/validations/val_settlement_create_with_zero_violation_window_rejected
        """
        notice_id = zero_window["notice"]["id"]
        version = api.notice_version(notice_id, REGULATORY_COUNSEL)

        refusal = _propose(api, notice_id, 300000, version)
        validate_error(refusal, ERR_NO_VIOLATION_WINDOW, 422)
        assert _settlement_count(api, notice_id) == 0, (
            "A refused create must leave no Settlement row behind"
        )

    def test_advancing_the_clock_one_day_makes_the_identical_create_succeed(
        self, api, zero_window
    ):
        """The window is measured against the clock, so one day is enough.

        PRD: "`violation_days` is the number of whole days from the notice's `earliest_violation_date` to the logical clock at the moment the settlement row is created: the elapsed seconds divided by eighty-six thousand four hundred, taken as a floor to a whole number."

        PRD: "Step two computes `base_penalty_cents` as the **lesser** of two statutory measures: a day-based measure of two hundred and fifty thousand cents (2,500 dollars) per day of violation multiplied by `violation_days`, and a unit-based measure of five hundred cents (5 dollars) per unit multiplied by the notice's `alleged_units`."

        PRD: "When it is at least one hundred thousand cents but strictly below one million cents (10,000 dollars), the cap is the adjusted penalty multiplied by 1.00, floored."

        PRD: "Step six computes `allowed_fees_cents` as the lesser of `requested_attorney_fees_cents` and `fee_cap_cents`."

        Design: Corner/validations/val_settlement_create_with_zero_violation_window_rejected
        """
        notice_id = zero_window["notice"]["id"]
        validate_error(
            _propose(
                api, notice_id, 300000, api.notice_version(notice_id, REGULATORY_COUNSEL)
            ),
            ERR_NO_VIOLATION_WINDOW,
            422,
        )

        set_clock(api, "2026-08-02T00:00:00Z")
        settlement = get_success_data(
            _propose(
                api, notice_id, 300000, api.notice_version(notice_id, REGULATORY_COUNSEL)
            )
        )

        assert_status(settlement, SETTLEMENT_PROPOSED)
        assert_money_waterfall(
            settlement,
            violation_days=1,
            base_penalty_cents=250000,
            mitigation_factor=1.0000,
            adjusted_penalty_cents=250000,
            fee_cap_cents=250000,
            allowed_fees_cents=250000,
            state_share_cents=187500,
            noticing_party_share_cents=62500,
            total_settlement_cents=500000,
        )
        assert_shares_reconcile(settlement)
        assert settlement["requested_attorney_fees_cents"] == 300000, (
            "The request is stored as made even though the cap trims the award, "
            f"got {settlement['requested_attorney_fees_cents']!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# The indemnity cap is consulted only when the warranty defence was taken
# ─────────────────────────────────────────────────────────────────────────────


class TestIndemnityCapIsGatedOnTheWarrantyDefence:
    """The larger penalty executes and the smaller one is refused."""

    def test_the_warranty_defence_takes_the_penalty_down_to_sixty_percent(
        self, api, indemnity_pair
    ):
        """Every ACTIVE component stands behind a passed-through ACTIVE warranty.

        PRD: "The warranty factor of 0.60 applies when the warranty defence holds."

        PRD: "The warranty defence holds only when **every** component of the product in status `ACTIVE` has a material whose supplier satisfies all four of the following: `warranty_status` is `ACTIVE`; `pass_through_warning_obligation` is true; `warranty_scope` covers that material's `material_class`, with `ALL_MATERIALS` covering every class, `RAW_MATERIAL_ONLY` covering only `RAW_MATERIAL` and `PACKAGING_ONLY` covering only `PACKAGING`; and the supplier's half-open warranty window covers the notice's `served_at`, meaning `warranty_effective_from` is at or before `served_at` and `served_at` is strictly before `warranty_effective_to`, with a null `warranty_effective_to` treated as positive infinity."

        PRD: "Step four computes `adjusted_penalty_cents` as `base_penalty_cents` multiplied by the already-rounded `mitigation_factor`, rounded half up to whole cents."

        PRD: "At one million cents or above, the cap is the adjusted penalty multiplied by 0.60, floored."

        Design: Corner/validations/val_indemnity_cap_checked_only_when_warranty_defense_applied
        """
        settlement = indemnity_pair["a"]["settlement"]
        assert_money_waterfall(
            settlement,
            violation_days=92,
            base_penalty_cents=2000000,
            mitigation_factor=0.6000,
            adjusted_penalty_cents=1200000,
            fee_cap_cents=720000,
            allowed_fees_cents=500000,
            state_share_cents=900000,
            noticing_party_share_cents=300000,
            total_settlement_cents=1700000,
        )
        assert_shares_reconcile(settlement)

    def test_execution_is_refused_when_the_mitigated_penalty_overshoots_the_cap(
        self, api, indemnity_pair
    ):
        """1200000 exceeds the single supplier's 1000000 cap, so nothing executes.

        PRD: "It is also refused with `ERR_INDEMNITY_CAP_EXCEEDED` when this settlement's mitigation included the warranty factor of 0.60 and its `adjusted_penalty_cents` exceeds the summed `indemnity_cap_cents` of every supplier with an `ACTIVE` warranty standing behind the product's `ACTIVE` components."

        Design: Corner/validations/val_indemnity_cap_checked_only_when_warranty_defense_applied
        """
        arm = indemnity_pair["a"]
        refusal = _move(api, arm["settlement"]["id"], "ACCEPT_EXECUTE", REGULATORY_COUNSEL_2)
        validate_error(refusal, ERR_INDEMNITY_CAP_EXCEEDED, 409)

        unchanged = _read_settlement(api, arm["settlement"]["id"])
        assert_status(unchanged, SETTLEMENT_PROPOSED)
        assert_fields_null(unchanged, ["executed_by_user_id", "executed_at"])
        assert_status(_read_notice(api, arm["notice"]["id"]), NOTICE_SETTLEMENT_NEGOTIATION)

        product = read_product(api, arm["product"]["id"])
        assert_cents(product["accrued_penalty_cents"], 0, "accrued_penalty_cents")
        assert product["open_notice_count"] == 1, (
            "The refused execution may not close the notice, expected "
            f"open_notice_count 1, got {product['open_notice_count']!r}"
        )

    def test_without_the_pass_through_obligation_no_defence_applies(
        self, api, indemnity_pair
    ):
        """The one differing supplier flag leaves the full penalty standing.

        PRD: "The warranty defence holds only when **every** component of the product in status `ACTIVE` has a material whose supplier satisfies all four of the following: `warranty_status` is `ACTIVE`; `pass_through_warning_obligation` is true; `warranty_scope` covers that material's `material_class`, with `ALL_MATERIALS` covering every class, `RAW_MATERIAL_ONLY` covering only `RAW_MATERIAL` and `PACKAGING_ONLY` covering only `PACKAGING`; and the supplier's half-open warranty window covers the notice's `served_at`, meaning `warranty_effective_from` is at or before `served_at` and `served_at` is strictly before `warranty_effective_to`, with a null `warranty_effective_to` treated as positive infinity."

        PRD: "Step three computes `mitigation_factor` by multiplying together the applicable mitigation factors, starting from 1 and then applying the floor."

        Design: Corner/validations/val_indemnity_cap_checked_only_when_warranty_defense_applied
        """
        settlement = indemnity_pair["b"]["settlement"]
        assert_money_waterfall(
            settlement,
            violation_days=92,
            base_penalty_cents=2000000,
            mitigation_factor=1.0000,
            adjusted_penalty_cents=2000000,
            fee_cap_cents=1200000,
            allowed_fees_cents=500000,
            state_share_cents=1500000,
            noticing_party_share_cents=500000,
            total_settlement_cents=2500000,
        )
        assert_shares_reconcile(settlement)

    def test_the_cap_is_not_consulted_when_the_defence_was_never_taken(
        self, api, indemnity_pair
    ):
        """2000000 overshoots the same 1000000 cap by more, and still executes.

        PRD: "It is also refused with `ERR_INDEMNITY_CAP_EXCEEDED` when this settlement's mitigation included the warranty factor of 0.60 and its `adjusted_penalty_cents` exceeds the summed `indemnity_cap_cents` of every supplier with an `ACTIVE` warranty standing behind the product's `ACTIVE` components."

        PRD: "On success, `executed_by_user_id` and `executed_at` are stamped, and the cascade runs: at level one the product's `accrued_penalty_cents` increases by this settlement's `adjusted_penalty_cents`; at level two, because this settlement reached `EXECUTED`, its notice transitions `SETTLEMENT_NEGOTIATION → SETTLED` and the product's `open_notice_count` decrements by 1; at level three, because `open_notice_count` changed, `compliance_posture` is recomputed and leaves `ENFORCEMENT_HOLD` when the count reaches 0."

        Design: Corner/validations/val_indemnity_cap_checked_only_when_warranty_defense_applied
        """
        arm = indemnity_pair["b"]
        executed = get_success_data(
            _move(api, arm["settlement"]["id"], "ACCEPT_EXECUTE", REGULATORY_COUNSEL_2)
        )
        assert_status(executed, SETTLEMENT_EXECUTED)
        assert executed["executed_by_user_id"] == RC_2, (
            "executed_by_user_id is stamped from the acting X-User-ID, expected "
            f"{RC_2!r}, got {executed['executed_by_user_id']!r}"
        )
        assert_instant(executed["executed_at"], DEFAULT_CLOCK, "executed_at")

        assert_status(_read_notice(api, arm["notice"]["id"]), NOTICE_SETTLED)
        product = read_product(api, arm["product"]["id"])
        assert_cents(
            product["accrued_penalty_cents"], 2000000, "accrued_penalty_cents"
        )
        assert product["open_notice_count"] == 0, (
            "Execution settles the notice, so open_notice_count falls to 0, got "
            f"{product['open_notice_count']!r}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Voiding is blocked only once the promised reformulation was delivered
# ─────────────────────────────────────────────────────────────────────────────


class TestVoidBlockedByDeliveredReformulation:
    """The commitment flag and the COMPLETED project must both be present."""

    def test_the_completed_project_rewrote_the_link_and_tore_down_the_old_evidence(
        self, api, void_pair
    ):
        """800.0 ppm became 8.0 ppm, so 100.000 ug/day became 1.000 ug/day.

        PRD: "`baseline_daily_exposure_ug` is the `daily_exposure_ug` of the newest assessment in status `FINAL` for the same product and chemical pair, where "newest" means ranked by `finalized_at` descending and then by `created_at` descending as the tie-break; when the product has no `FINAL` assessment for that chemical the baseline is 0."

        PRD: "At level one the linked material-chemical's `declared_concentration_ppm` is overwritten with the project's `target_concentration_ppm`, its `status` resets to `DECLARED`, its `measurement_basis` resets to `SUPPLIER_DECLARED`, and `lab_name`, `lab_result_ppm`, `lab_loq_ppm` and `lab_reported_at` are all cleared — the old laboratory evidence describes a formulation that no longer exists."

        PRD: "Submitting for verification also stamps `verified_daily_exposure_ug` with the recomputed modelled exposure for the project's product and chemical pair and computes `reduction_pct` as one hundred times the difference between `baseline_daily_exposure_ug` and `verified_daily_exposure_ug` divided by `baseline_daily_exposure_ug`, rounded half up to two decimal places; when `baseline_daily_exposure_ug` is 0 the percentage is undefined and `reduction_pct` is null."

        PRD: "Completing takes the project `VERIFICATION → COMPLETED` and requires `verified_daily_exposure_ug` to be **strictly** below the chemical's `safe_harbor_level_ug_per_day`; exposure exactly equal to the safe harbour level fails with `ERR_TARGET_NOT_BELOW_THRESHOLD`, which is the mirror image of the assessment verdict rule, where exposure exactly at the level is treated as `BELOW_SAFE_HARBOR`."

        Design: Corner/validations/val_void_blocked_once_reformulation_consideration_was_delivered
        """
        project = _read_project(api, void_pair["project"]["id"])
        assert_status(project, PROJECT_COMPLETED)
        assert_exposure(
            project["baseline_daily_exposure_ug"], 100.000, "baseline_daily_exposure_ug"
        )
        assert_exposure(
            project["verified_daily_exposure_ug"], 1.000, "verified_daily_exposure_ug"
        )
        assert_close(project["reduction_pct"], 99.00, 2, "reduction_pct")

        link = _read_link(api, void_pair["link"]["id"])
        assert_concentration(link["declared_concentration_ppm"], 8.0)
        assert link["measurement_basis"] == BASIS_SUPPLIER_DECLARED, (
            "Verification resets the basis to SUPPLIER_DECLARED, got "
            f"{link['measurement_basis']!r}"
        )
        assert_status(link, LINK_STATUS_DECLARED)
        assert_fields_null(
            link, ["lab_name", "lab_result_ppm", "lab_loq_ppm", "lab_reported_at"]
        )

        assert_status(
            _read_assessment(api, void_pair["assessment"]["id"]), ASSESSMENT_SUPERSEDED
        )

    def test_the_reformulation_commitment_is_the_only_factor_that_applies(
        self, api, void_pair
    ):
        """No warranty and no cure, so the penalty runs at three quarters.

        PRD: "The reformulation factor of 0.75 applies when this settlement's `reformulation_commitment` is true."

        PRD: "A product with zero `ACTIVE` components does **not** get the warranty defence — the empty product is explicitly excluded rather than vacuously qualifying."

        Design: Corner/validations/val_void_blocked_once_reformulation_consideration_was_delivered
        """
        for key in ("a", "b"):
            settlement = _read_settlement(api, void_pair[key]["settlement"]["id"])
            assert settlement["reformulation_commitment"] is True, (
                "Both settlements carry the commitment, got "
                f"{settlement['reformulation_commitment']!r} on arm {key}"
            )
            assert_money_waterfall(
                settlement,
                violation_days=92,
                base_penalty_cents=2000000,
                mitigation_factor=0.7500,
                adjusted_penalty_cents=1500000,
                fee_cap_cents=900000,
                allowed_fees_cents=500000,
                state_share_cents=1125000,
                noticing_party_share_cents=375000,
                total_settlement_cents=2000000,
            )
            assert_status(settlement, SETTLEMENT_EXECUTED)

    def test_void_is_refused_once_the_promised_reformulation_was_delivered(
        self, api, void_pair
    ):
        """The conjunction holds on arm A, so the unwind never starts.

        PRD: "Voiding is blocked when the promised consideration has already been delivered: if the settlement's `reformulation_commitment` is true and the product already has a reformulation project in status `COMPLETED` naming the notice's `chemical_id`, the request is refused with `ERR_SETTLEMENT_NOT_VOIDABLE`."

        Design: Corner/validations/val_void_blocked_once_reformulation_consideration_was_delivered
        """
        arm = void_pair["a"]
        product = read_product(api, arm["product"]["id"])
        assert_cents(
            product["accrued_penalty_cents"], 1500000, "accrued_penalty_cents"
        )

        refusal = _move(api, arm["settlement"]["id"], "VOID", REGULATORY_COUNSEL)
        validate_error(refusal, ERR_SETTLEMENT_NOT_VOIDABLE, 409)

        assert_status(_read_settlement(api, arm["settlement"]["id"]), SETTLEMENT_EXECUTED)
        assert_status(_read_notice(api, arm["notice"]["id"]), NOTICE_SETTLED)
        after = read_product(api, arm["product"]["id"])
        assert_cents(after["accrued_penalty_cents"], 1500000, "accrued_penalty_cents")
        assert after["open_notice_count"] == 0, (
            "A refused void performs no partial unwind, so open_notice_count "
            f"stays 0, got {after['open_notice_count']!r}"
        )

    def test_the_commitment_flag_alone_does_not_block_the_unwind(
        self, api, void_pair
    ):
        """Arm B promised the same reformulation but completed no project.

        PRD: "It reverses every effect execution applied: the product's `accrued_penalty_cents` decreases by the same `adjusted_penalty_cents`, restoring the pre-execution value exactly with no drift; the notice transitions `SETTLED → SETTLEMENT_NEGOTIATION` and `open_notice_count` increments by 1; and `compliance_posture` is recomputed."

        PRD: "The reverse edge `SETTLED → SETTLEMENT_NEGOTIATION` is also system-driven and fires when the executed settlement is voided; it increments `open_notice_count` by 1 and recomputes `compliance_posture`, which re-enters `ENFORCEMENT_HOLD`."

        Design: Corner/validations/val_void_blocked_once_reformulation_consideration_was_delivered
        """
        arm = void_pair["b"]
        assert _project_count(api, arm["product"]["id"]) == 0, (
            "Arm B has no reformulation project at all"
        )

        voided = get_success_data(
            _move(api, arm["settlement"]["id"], "VOID", REGULATORY_COUNSEL)
        )
        assert_status(voided, SETTLEMENT_VOID)

        assert_status(
            _read_notice(api, arm["notice"]["id"]), NOTICE_SETTLEMENT_NEGOTIATION
        )
        product = read_product(api, arm["product"]["id"])
        assert_cents(product["accrued_penalty_cents"], 0, "accrued_penalty_cents")
        assert product["open_notice_count"] == 1, (
            "The unwind reopens the notice, expected open_notice_count 1, got "
            f"{product['open_notice_count']!r}"
        )
        assert_posture(product, POSTURE_ENFORCEMENT_HOLD)
