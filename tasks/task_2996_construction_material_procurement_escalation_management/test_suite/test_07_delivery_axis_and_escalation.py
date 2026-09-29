"""Compliance tests for the delivery axis and the twofold recognition of escalation.

Covers the physical posture edges of a purchase commitment (PRD §3.6) — the
declared edges, the early-buyout storage requirement standing between
`FABRICATING` and `DELIVERED`, and the closure cascade delivery runs — together
with the two escalation recognitions: `PROVISIONAL` at release against a
look-back reading and `FINAL` at delivery against the exact clock month.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_instant_equals,
    assert_material_package,
    assert_project,
    assert_purchase_commitment,
    assert_storage_arrangement,
    build_buyout_scenario,
    build_fabricating_scenario,
    build_released_scenario,
    build_stored_offsite_scenario,
    countersign_commitment,
    draft_clause,
    execute_clause,
    expected_carrying_cost,
    expected_escalation_accrued,
    file_document,
    issue_commitment,
    list_documents,
    move_posture,
    open_project,
    propose_clause,
    publish_reading,
    read_arrangement,
    read_commitment,
    read_package,
    read_project,
    register_package,
    register_supplier,
    revoke_document,
    set_clock,
    submit_quote,
    validate_error,
    validate_success,
    whole_months_between,
)
from test_helpers.factories import delivery_posture_payload

BUYOUT_MANAGER = TEST_USERS["buyout_manager_headers"]

# The four PPI_STEEL_MILL readings the escalation fixtures publish.
_STEEL_READINGS_FULL = (
    ("2026-07", 310.00),
    ("2026-08", 322.00),
    ("2026-09", 331.00),
    ("2026-12", 344.50),
)
# Only July and August published: nothing exists for September or December.
_STEEL_READINGS_JUL_AUG = (("2026-07", 310.00), ("2026-08", 322.00))
_STEEL_READINGS_JUL_ONLY = (("2026-07", 310.00),)

# The negotiated terms shared by the steel clauses in this file.
_CLAUSE_TERMS = {
    "baseline_index_period": "2026-07",
    "cap_pct": 8.0,
    "contractor_share_pct": 40.0,
    "deadband_pct": 2.0,
}


# ─── setup helpers (not tests: no Design tag) ─────────────────────────────

def _execute_clause_on(quote_id, index_code):
    """Draft → propose → execute a clause carrying the shared steel terms."""
    terms = dict(_CLAUSE_TERMS)
    terms["index_code"] = index_code
    clause = draft_clause(quote_id, **terms)
    propose_clause(clause["id"])
    return execute_clause(clause["id"])


def _setup_committed(*, readings, is_early_buyout=False, budget=500000.00):
    """A countersigned steel commitment sitting at SCHEDULED, clock untouched."""
    return build_buyout_scenario(
        readings=readings,
        project_overrides={"escalation_contingency_budget": budget},
        package_overrides={"estimated_cost": 1200000.00},
        quote_overrides={"base_price": 1150000.00},
        clause_overrides=dict(_CLAUSE_TERMS),
        commitment_overrides={"is_early_buyout": is_early_buyout},
    )


def _setup_released(*, release_at, readings, is_early_buyout=False, budget=500000.00):
    """The same commitment released for fabrication at `release_at`."""
    return build_released_scenario(
        release_at=release_at,
        readings=readings,
        project_overrides={"escalation_contingency_budget": budget},
        package_overrides={"estimated_cost": 1200000.00},
        quote_overrides={"base_price": 1150000.00},
        clause_overrides=dict(_CLAUSE_TERMS),
        commitment_overrides={"is_early_buyout": is_early_buyout},
    )


def _setup_fabricating(*, release_at, readings, is_early_buyout=False, budget=500000.00):
    """The same commitment carried on to FABRICATING."""
    return build_fabricating_scenario(
        release_at=release_at,
        readings=readings,
        project_overrides={"escalation_contingency_budget": budget},
        package_overrides={"estimated_cost": 1200000.00},
        quote_overrides={"base_price": 1150000.00},
        clause_overrides=dict(_CLAUSE_TERMS),
        commitment_overrides={"is_early_buyout": is_early_buyout},
    )


def _setup_copper_fabricating():
    """The copper feeder buyout of the four-step-chain instance, at FABRICATING."""
    return build_fabricating_scenario(
        release_at="2026-09-10T00:00:00.000Z",
        readings=(("2026-07", 200.00), ("2026-10", 220.00)),
        project_overrides={"escalation_contingency_budget": 500000.00},
        package_overrides={
            "scope_code": "ELEC-FEEDER-01",
            "description": "Electrical feeder conductor package",
            "commodity_index_code": "PPI_COPPER_WIRE",
            "estimated_cost": 900000.00,
            "required_onsite_date": "2027-05-01T00:00:00.000Z",
            "fabrication_duration_days": 60,
            "delivery_transit_days": 25,
            "submittal_review_days": 21,
        },
        supplier_overrides={"legal_name": "Continental Wire and Cable"},
        quote_overrides={"base_price": 875000.00},
        clause_overrides={
            "baseline_index_period": "2026-07",
            "cap_pct": 10.0,
            "contractor_share_pct": 30.0,
            "deadband_pct": 2.0,
        },
        commitment_overrides={"po_number": "PO-2996-0007", "is_early_buyout": False},
    )


def _setup_deadband_pair():
    """One project, two clauses on identical terms, two index moves either side of 2.0%."""
    project = open_project(escalation_contingency_budget=500000.00)
    supplier = register_supplier()
    publish_reading("PPI_STEEL_MILL", "2026-07", 310.00)
    publish_reading("PPI_STEEL_MILL", "2026-08", 316.20)
    publish_reading("PPI_COPPER_WIRE", "2026-07", 200.00)
    publish_reading("PPI_COPPER_WIRE", "2026-08", 204.10)
    steel_package = register_package(
        project["id"],
        scope_code="STRUCT-STEEL-01",
        commodity_index_code="PPI_STEEL_MILL",
        estimated_cost=1200000.00,
    )
    copper_package = register_package(
        project["id"],
        scope_code="ELEC-FEEDER-01",
        description="Electrical feeder conductor package",
        commodity_index_code="PPI_COPPER_WIRE",
        estimated_cost=1200000.00,
    )
    steel_quote = submit_quote(steel_package["id"], supplier["id"], base_price=1150000.00)
    copper_quote = submit_quote(copper_package["id"], supplier["id"], base_price=1150000.00)
    steel_clause = _execute_clause_on(steel_quote["id"], "PPI_STEEL_MILL")
    copper_clause = _execute_clause_on(copper_quote["id"], "PPI_COPPER_WIRE")
    steel_commitment = countersign_commitment(
        issue_commitment(
            project["id"],
            steel_quote["id"],
            po_number="PO-2996-0001",
            escalation_agreement_id=steel_clause["id"],
        )["id"]
    )
    copper_commitment = countersign_commitment(
        issue_commitment(
            project["id"],
            copper_quote["id"],
            po_number="PO-2996-0002",
            escalation_agreement_id=copper_clause["id"],
        )["id"]
    )
    return {
        "project": project,
        "steel_commitment": steel_commitment,
        "copper_commitment": copper_commitment,
    }


def _setup_mixed_package_ledger():
    """Three packages: one COMMITTED buyout, one PENDING buyout, one never quoted."""
    project = open_project(escalation_contingency_budget=500000.00)
    supplier = register_supplier()
    publish_reading("PPI_STEEL_MILL", "2026-07", 310.00)
    package_a = register_package(
        project["id"],
        scope_code="STRUCT-STEEL-01",
        commodity_index_code="PPI_STEEL_MILL",
        estimated_cost=1200000.00,
    )
    package_b = register_package(
        project["id"],
        scope_code="ELEC-FEEDER-01",
        description="Electrical feeder conductor package",
        commodity_index_code="PPI_COPPER_WIRE",
        estimated_cost=300000.00,
    )
    package_c = register_package(
        project["id"],
        scope_code="MECH-AHU-01",
        description="Rooftop air handling unit package",
        commodity_index_code="PPI_STEEL_MILL",
        estimated_cost=400000.00,
    )
    quote_a = submit_quote(package_a["id"], supplier["id"], base_price=1150000.00)
    clause_a = _execute_clause_on(quote_a["id"], "PPI_STEEL_MILL")
    commitment_a = countersign_commitment(
        issue_commitment(
            project["id"],
            quote_a["id"],
            po_number="PO-2996-0001",
            escalation_agreement_id=clause_a["id"],
        )["id"]
    )
    quote_b = submit_quote(package_b["id"], supplier["id"], base_price=290000.00)
    commitment_b = issue_commitment(project["id"], quote_b["id"], po_number="PO-2996-0002")
    return {
        "project": project,
        "package_a": package_a,
        "package_b": package_b,
        "package_c": package_c,
        "commitment_a": commitment_a,
        "commitment_b": commitment_b,
    }


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / escalation_provisional_at_release_versus_final_at_delivery
# ---------------------------------------------------------------------------

def test_delivery_axis_provisional_escalation_stamped_at_release():
    """Release recognises escalation provisionally off the newest period at or before the clock.

    The clause baseline is the 2026-07 reading of 310.00 and the newest published
    period at or before the 2026-09 clock month is 2026-09 at 331.00. The movement
    is 6.7742%, the 2.0 deadband leaves 4.7742%, the 8.0 cap does not bite, the
    owner-borne sixty percent leaves 2.86452% and a committed base cost of
    1150000.00 accrues 32941.98 — leaving 467058.02 of the 500000.00 contingency.

    PRD §3.6: "At **release**, the reading used is the one for the clause's `index_code` with the **greatest period at or before** the current clock month"
    PRD §3.6: "Release sets `escalation_variant` to `PROVISIONAL` and records the selected reading's period in `escalation_index_period`."
    PRD §3.6: "It stamps `released_for_fab_at` with the current logical clock, runs the provisional escalation arithmetic described below, and increments the project's `version` by 1"
    PRD §3.6: "`escalation_accrued` is `committed_base_cost` multiplied by the shared movement, divided by one hundred, and rounded half up to **two** decimal places"
    PRD §3.1: "`escalation_contingency_committed` is the sum of `escalation_accrued` over that same `COMMITTED`-or-`CLOSED` set, and `escalation_contingency_remaining` is the budget less that figure, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/escalation_provisional_at_release_versus_final_at_delivery
    """
    scenario = _setup_fabricating(
        release_at="2026-09-10T00:00:00.000Z", readings=_STEEL_READINGS_FULL
    )
    commitment = read_commitment(scenario["commitment"]["id"])
    assert_purchase_commitment(commitment)

    assert commitment["escalation_variant"] == "PROVISIONAL"
    assert commitment["escalation_index_period"] == "2026-09"
    assert commitment["escalation_accrued"] == pytest.approx(32941.98, abs=0.005)
    assert commitment["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(1150000.00, 310.00, 331.00, 2.0, 8.0, 40.0), abs=0.005
    )
    assert_instant_equals(commitment["released_for_fab_at"], "2026-09-10T00:00:00.000Z")
    assert commitment["delivered_at"] is None
    assert commitment["commitment_status"] == "COMMITTED"
    assert commitment["delivery_posture"] == "FABRICATING"

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["escalation_contingency_committed"] == pytest.approx(32941.98, abs=0.005)
    assert project["escalation_contingency_remaining"] == pytest.approx(467058.02, abs=0.005)
    assert project["committed_total_cost"] == pytest.approx(1182941.98, abs=0.005)


def test_delivery_axis_final_escalation_overwrites_the_provisional_at_delivery():
    """Delivery re-reads the index for exactly the clock month and overwrites the accrual.

    The 2026-12 reading of 344.50 moves 11.1290% off the 310.00 baseline; the
    deadband leaves 9.1290% and this time the 8.0 cap does bite, so the owner-borne
    sixty percent of 8.0 is 4.8% and 1150000.00 accrues 55200.00 — 22258.02 more
    than the 32941.98 stamped at release. Delivery also closes both the contractual
    axis and the scope package.

    PRD §3.6: "At **delivery**, the reading used is the one whose `period` equals the current clock month exactly. Delivery overwrites `escalation_accrued`, overwrites `escalation_index_period`, and sets `escalation_variant` to `FINAL`"
    PRD §3.6: "the capped movement is the lesser of the eligible movement and `cap_pct`"
    PRD §3.6: "Both paths then stamp `delivered_at` with the current logical clock, run the final escalation arithmetic, increment the project's `version` by 1, close the contractual axis by moving `commitment_status` from `COMMITTED` to `CLOSED`, and close the scope package by moving it from `BOUGHT_OUT` to `CLOSED`."
    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's `committed_base_cost` plus its `escalation_accrued`; commitments that are `PENDING`, `CANCELLED` or `VOIDED` contribute nothing."

    Design: Difficulty/dual_variant_calc/escalation_provisional_at_release_versus_final_at_delivery
    """
    scenario = _setup_fabricating(
        release_at="2026-09-10T00:00:00.000Z", readings=_STEEL_READINGS_FULL
    )
    provisional = scenario["commitment"]["escalation_accrued"]
    assert provisional == pytest.approx(32941.98, abs=0.005)

    set_clock("2026-12-20T00:00:00.000Z")
    delivered = validate_success(
        api_client.set_delivery_posture(
            scenario["commitment"]["id"], delivery_posture_payload("DELIVERED"), BUYOUT_MANAGER
        )
    )
    assert_purchase_commitment(delivered)

    assert delivered["escalation_variant"] == "FINAL"
    assert delivered["escalation_index_period"] == "2026-12"
    assert delivered["escalation_accrued"] == pytest.approx(55200.00, abs=0.005)
    assert delivered["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(1150000.00, 310.00, 344.50, 2.0, 8.0, 40.0), abs=0.005
    )
    assert delivered["escalation_accrued"] - provisional == pytest.approx(22258.02, abs=0.005)
    assert delivered["commitment_status"] == "CLOSED"
    assert delivered["delivery_posture"] == "DELIVERED"
    assert_instant_equals(delivered["delivered_at"], "2026-12-20T00:00:00.000Z")

    package = read_package(scenario["package"]["id"])
    assert_material_package(package)
    assert package["status"] == "CLOSED"

    project = read_project(scenario["project"]["id"])
    assert project["escalation_contingency_committed"] == pytest.approx(55200.00, abs=0.005)
    assert project["escalation_contingency_remaining"] == pytest.approx(444800.00, abs=0.005)
    assert project["committed_total_cost"] == pytest.approx(1205200.00, abs=0.005)
    assert project["buyout_variance"] == pytest.approx(-5200.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue A: combinatorial_formula / escalation_four_step_chain_with_single_intermediate_rounding
# ---------------------------------------------------------------------------

def test_delivery_axis_four_step_chain_single_intermediate_rounding_at_delivery():
    """The four-step escalation chain rounds once at four places and once at two.

    The copper baseline is 200.00 and the 2026-10 reading is 220.00, so the movement
    is exactly 10.0000%; the 2.0 deadband leaves 8.0%, the 10.0 cap does not bite,
    the owner-borne seventy percent leaves 5.6% and 875000.00 of committed base cost
    accrues 49000.00. Nothing between the movement and the dollars is re-rounded.

    PRD §3.6: "the reading's `value` for the selected period, less the clause's frozen `baseline_index_value`, divided by that same `baseline_index_value`, multiplied by one hundred, and rounded half up to **four** decimal places"
    PRD §3.6: "the shared movement is the capped movement multiplied by the owner-borne fraction, which is one minus `contractor_share_pct` divided by one hundred"
    PRD §3.6: "There is exactly one intermediate rounding — the index movement to four decimal places — and exactly one final rounding, to two."
    PRD §3.6: "At **delivery**, the reading used is the one whose `period` equals the current clock month exactly. Delivery overwrites `escalation_accrued`, overwrites `escalation_index_period`, and sets `escalation_variant` to `FINAL`"

    Design: Difficulty/combinatorial_formula/escalation_four_step_chain_with_single_intermediate_rounding
    """
    scenario = _setup_copper_fabricating()
    set_clock("2026-10-05T00:00:00.000Z")
    delivered = validate_success(
        api_client.set_delivery_posture(
            scenario["commitment"]["id"], delivery_posture_payload("DELIVERED"), BUYOUT_MANAGER
        )
    )
    assert_purchase_commitment(delivered)

    assert delivered["escalation_variant"] == "FINAL"
    assert delivered["escalation_index_period"] == "2026-10"
    assert delivered["escalation_accrued"] == pytest.approx(49000.00, abs=0.005)
    assert delivered["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(875000.00, 200.00, 220.00, 2.0, 10.0, 30.0), abs=0.005
    )
    assert delivered["commitment_status"] == "CLOSED"
    assert delivered["delivery_posture"] == "DELIVERED"

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["escalation_contingency_committed"] == pytest.approx(49000.00, abs=0.005)
    assert project["escalation_contingency_remaining"] == pytest.approx(451000.00, abs=0.005)
    assert project["committed_total_cost"] == pytest.approx(924000.00, abs=0.005)


def test_delivery_axis_four_step_chain_deadband_step_absorbs_the_look_back_movement():
    """The same chain run at release, where the deadband step alone decides the answer.

    Released in the 2026-09 clock month, the look-back finds only the 2026-07 baseline
    period itself, so the movement off 200.00 is 0.0000%, the deadband floors the
    eligible movement at zero, and the accrual is 0.00 while the variant is already
    PROVISIONAL against the selected 2026-07 period.

    PRD §3.6: "At **release**, the reading used is the one for the clause's `index_code` with the **greatest period at or before** the current clock month"
    PRD §3.6: "the eligible movement is the greater of zero and the index movement less `deadband_pct`, so movement wholly inside the deadband yields zero and a falling index yields zero rather than a credit to the owner"
    PRD §3.6: "Release sets `escalation_variant` to `PROVISIONAL` and records the selected reading's period in `escalation_index_period`."

    Design: Difficulty/combinatorial_formula/escalation_four_step_chain_with_single_intermediate_rounding
    """
    scenario = _setup_copper_fabricating()
    commitment = read_commitment(scenario["commitment"]["id"])
    assert_purchase_commitment(commitment)

    assert commitment["escalation_variant"] == "PROVISIONAL"
    assert commitment["escalation_index_period"] == "2026-07"
    assert commitment["escalation_accrued"] == pytest.approx(0.00, abs=0.005)
    assert commitment["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(875000.00, 200.00, 200.00, 2.0, 10.0, 30.0), abs=0.005
    )
    assert_instant_equals(commitment["released_for_fab_at"], "2026-09-10T00:00:00.000Z")

    project = read_project(scenario["project"]["id"])
    assert project["escalation_contingency_committed"] == pytest.approx(0.00, abs=0.005)
    assert project["escalation_contingency_remaining"] == pytest.approx(500000.00, abs=0.005)
    assert project["committed_total_cost"] == pytest.approx(875000.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / commitment_delivery_axis_cycles_while_commitment_status_holds_committed
# ---------------------------------------------------------------------------

def _find_document(documents, doc_type, *, revoked=False):
    """The one non-revoked document of `doc_type` on an arrangement's document list."""
    matches = [
        doc
        for doc in documents
        if doc["doc_type"] == doc_type and doc["revoked"] is revoked
    ]
    assert len(matches) == 1, f"expected exactly one {doc_type} with revoked={revoked}"
    return matches[0]


def _setup_stored_offsite_cycle():
    """An early-buyout steel commitment at STORED_OFFSITE with a complete document set."""
    return build_stored_offsite_scenario(
        release_at="2026-09-10T00:00:00.000Z",
        stored_from="2026-09-20T00:00:00.000Z",
        planned_release_date="2026-12-31T00:00:00.000Z",
        stored_value=862500.00,
        monthly_storage_rate_pct=0.1875,
        warehouse_name="Harbor Yard 7",
        doc_effective_date="2026-09-01T00:00:00.000Z",
        doc_expires_at="2027-06-01T00:00:00.000Z",
        readings=_STEEL_READINGS_FULL,
        project_overrides={"escalation_contingency_budget": 500000.00},
        package_overrides={"estimated_cost": 1200000.00},
        quote_overrides={"base_price": 1150000.00},
        clause_overrides=dict(_CLAUSE_TERMS),
    )


def test_delivery_axis_posture_cycles_out_of_and_back_into_stored_offsite():
    """The physical axis walks STORED_OFFSITE → STORAGE_NONCOMPLIANT → STORED_OFFSITE.

    Revoking the bailment agreement drops the arrangement out of completeness and
    flags the posture; filing a replacement bailment agreement restores the third
    mandatory type, returning the arrangement to ACTIVE with a count of 3, after
    which the same posture value the commitment already held is reachable again.

    PRD §3.6: "The same code and the same requirement govern the **return from non-compliance**, the move from `STORAGE_NONCOMPLIANT` back to `STORED_OFFSITE`, which additionally requires the arrangement to have climbed back to `ACTIVE`; this is the cycle `STORED_OFFSITE → STORAGE_NONCOMPLIANT → STORED_OFFSITE` on the delivery axis, and like the fabrication step it refreshes `updated_at` only."
    PRD §3.7: "Filing a replacement that restores the third mandatory type reverses the first two hops: the arrangement returns to `ACTIVE` with `documentation_status` `COMPLETE` and `verified_doc_type_count` back at 3, after which the `BuyoutManager` may move the posture back to `STORED_OFFSITE`."

    Design: Difficulty/non_linear_state_machine/commitment_delivery_axis_cycles_while_commitment_status_holds_committed
    """
    scenario = _setup_stored_offsite_cycle()
    arrangement_id = scenario["arrangement"]["id"]
    commitment_id = scenario["commitment"]["id"]
    assert scenario["commitment"]["delivery_posture"] == "STORED_OFFSITE"

    bailment = _find_document(list_documents(arrangement_id), "BAILMENT_AGREEMENT")
    revoke_document(
        bailment["id"], revocation_reason="Bailee changed custodian without notice"
    )
    flagged = read_commitment(commitment_id)
    assert flagged["delivery_posture"] == "STORAGE_NONCOMPLIANT"
    suspended = read_arrangement(arrangement_id)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["verified_doc_type_count"] == 2

    replacement = file_document(
        arrangement_id,
        doc_type="BAILMENT_AGREEMENT",
        reference_number="BAIL-2996-002",
        effective_date="2026-09-01T00:00:00.000Z",
        expires_at="2027-06-01T00:00:00.000Z",
        verified=True,
    )
    assert replacement["revoked"] is False

    restored = read_arrangement(arrangement_id)
    assert_storage_arrangement(restored)
    assert restored["status"] == "ACTIVE"
    assert restored["documentation_status"] == "COMPLETE"
    assert restored["verified_doc_type_count"] == 3

    returned = move_posture(commitment_id, "STORED_OFFSITE")
    assert_purchase_commitment(returned)
    assert returned["delivery_posture"] == "STORED_OFFSITE"
    assert _find_document(list_documents(arrangement_id), "BAILMENT_AGREEMENT", revoked=True)[
        "id"
    ] == bailment["id"]


def test_delivery_axis_cycle_leaves_the_contractual_axis_and_escalation_alone():
    """Every hop of the storage cycle leaves commitment_status COMMITTED and the accrual untouched.

    The two axes are disjoint: the paperwork lapsing and being replaced moves only
    the physical axis, so the commitment reads COMMITTED at all four observations and
    the PROVISIONAL 32941.98 stamped against the 2026-09 period at release survives
    the whole cycle, with the scope package still BOUGHT_OUT throughout.

    PRD §2.11: "The two state-name sets are disjoint, so no transition request is ambiguous across the axes."
    PRD §3.7: "its `delivery_posture` moves to `STORAGE_NONCOMPLIANT` while its `commitment_status` is deliberately left at `COMMITTED` — the paperwork lapsing does not unwind the purchase order"
    PRD §3.6: "The same code and the same requirement govern the **return from non-compliance**, the move from `STORAGE_NONCOMPLIANT` back to `STORED_OFFSITE`, which additionally requires the arrangement to have climbed back to `ACTIVE`; this is the cycle `STORED_OFFSITE → STORAGE_NONCOMPLIANT → STORED_OFFSITE` on the delivery axis, and like the fabrication step it refreshes `updated_at` only."

    Design: Difficulty/non_linear_state_machine/commitment_delivery_axis_cycles_while_commitment_status_holds_committed
    """
    scenario = _setup_stored_offsite_cycle()
    arrangement_id = scenario["arrangement"]["id"]
    commitment_id = scenario["commitment"]["id"]

    def _observe():
        observed = read_commitment(commitment_id)
        assert_purchase_commitment(observed)
        assert observed["commitment_status"] == "COMMITTED"
        assert observed["escalation_variant"] == "PROVISIONAL"
        assert observed["escalation_index_period"] == "2026-09"
        assert observed["escalation_accrued"] == pytest.approx(32941.98, abs=0.005)
        assert observed["delivered_at"] is None
        return observed

    assert _observe()["delivery_posture"] == "STORED_OFFSITE"

    bailment = _find_document(list_documents(arrangement_id), "BAILMENT_AGREEMENT")
    revoke_document(
        bailment["id"], revocation_reason="Bailee changed custodian without notice"
    )
    assert _observe()["delivery_posture"] == "STORAGE_NONCOMPLIANT"

    file_document(
        arrangement_id,
        doc_type="BAILMENT_AGREEMENT",
        reference_number="BAIL-2996-002",
        effective_date="2026-09-01T00:00:00.000Z",
        expires_at="2027-06-01T00:00:00.000Z",
        verified=True,
    )
    assert _observe()["delivery_posture"] == "STORAGE_NONCOMPLIANT"

    move_posture(commitment_id, "STORED_OFFSITE")
    assert _observe()["delivery_posture"] == "STORED_OFFSITE"

    package = read_package(scenario["package"]["id"])
    assert package["status"] == "BOUGHT_OUT"


# ---------------------------------------------------------------------------
# Queue B: state_machines / invalid_transitions_scheduled_directly_to_stored_offsite_rejected
# ---------------------------------------------------------------------------

def test_delivery_axis_scheduled_may_not_jump_straight_to_stored_offsite():
    """SCHEDULED → STORED_OFFSITE is not a declared edge of the physical axis.

    Even for an early-buyout order that will eventually need storage, the jump skips
    both RELEASED_FOR_FAB and FABRICATING, so it is refused on the own-state rung and
    nothing about the commitment moves — no release stamp, no escalation.

    PRD §3.6: "A posture move requested on a commitment that is `PENDING`, `CANCELLED`, `VOIDED` or `CLOSED`, or a `to_posture` that is not a declared edge out of the current posture — asking to jump from `SCHEDULED` directly to `STORED_OFFSITE`, for instance — is refused with `ERR_INVALID_POSTURE_TRANSITION`."
    PRD §3.5: "The new row starts with `commitment_status` `PENDING` and `delivery_posture` `SCHEDULED`, with `released_for_fab_at`, `delivered_at`, `escalation_index_period` and `cancellation_reason` all null, `escalation_variant` `NONE` and `escalation_accrued` 0."

    Design: Corner/state_machines/invalid_transitions_scheduled_directly_to_stored_offsite_rejected
    """
    scenario = _setup_committed(readings=_STEEL_READINGS_JUL_ONLY, is_early_buyout=True)
    commitment_id = scenario["commitment"]["id"]
    assert scenario["commitment"]["delivery_posture"] == "SCHEDULED"

    validate_error(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("STORED_OFFSITE"), BUYOUT_MANAGER
        ),
        ApiErrorId.ERR_INVALID_POSTURE_TRANSITION.value,
        409,
    )

    unchanged = read_commitment(commitment_id)
    assert_purchase_commitment(unchanged)
    assert unchanged["delivery_posture"] == "SCHEDULED"
    assert unchanged["commitment_status"] == "COMMITTED"
    assert unchanged["released_for_fab_at"] is None
    assert unchanged["escalation_variant"] == "NONE"
    assert unchanged["escalation_accrued"] == pytest.approx(0.00, abs=0.005)
    assert unchanged["escalation_index_period"] is None


# ---------------------------------------------------------------------------
# Queue B: state_machines / precondition_enforcement_early_buyout_cannot_skip_the_storage_step
# ---------------------------------------------------------------------------

def test_delivery_axis_early_buyout_cannot_skip_the_storage_step():
    """An early-buyout order may not walk FABRICATING → DELIVERED.

    `requires_storage_arrangement` mirrors `is_early_buyout`, so the material must
    physically pass through off-site storage first. The refusal leaves the posture at
    FABRICATING with `delivered_at` still null and the PROVISIONAL 12909.90 stamped
    at the 2026-08-05 release intact.

    PRD §3.6: "From `FABRICATING`, delivery is only permitted when `requires_storage_arrangement` is false; an early-buyout order may not skip the storage step on its way to site, and the attempt is refused with `ERR_STORAGE_STEP_REQUIRED`."
    PRD §3.5: "the server mirrors that declaration into `requires_storage_arrangement`, which always equals `is_early_buyout`"
    PRD §3.6: "Release sets `escalation_variant` to `PROVISIONAL` and records the selected reading's period in `escalation_index_period`."

    Design: Corner/state_machines/precondition_enforcement_early_buyout_cannot_skip_the_storage_step
    """
    scenario = _setup_fabricating(
        release_at="2026-08-05T00:00:00.000Z",
        readings=_STEEL_READINGS_JUL_AUG,
        is_early_buyout=True,
    )
    commitment_id = scenario["commitment"]["id"]
    assert scenario["commitment"]["requires_storage_arrangement"] is True

    validate_error(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("DELIVERED"), BUYOUT_MANAGER
        ),
        ApiErrorId.ERR_STORAGE_STEP_REQUIRED.value,
        409,
    )

    unchanged = read_commitment(commitment_id)
    assert_purchase_commitment(unchanged)
    assert unchanged["delivery_posture"] == "FABRICATING"
    assert unchanged["commitment_status"] == "COMMITTED"
    assert unchanged["delivered_at"] is None
    assert unchanged["escalation_variant"] == "PROVISIONAL"
    assert unchanged["escalation_index_period"] == "2026-08"
    assert unchanged["escalation_accrued"] == pytest.approx(12909.90, abs=0.005)
    assert unchanged["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(1150000.00, 310.00, 322.00, 2.0, 8.0, 40.0), abs=0.005
    )

    package = read_package(scenario["package"]["id"])
    assert package["status"] == "BOUGHT_OUT"


# ---------------------------------------------------------------------------
# Queue B: state_machines / cascade_down_delivery_closes_the_commitment_package_and_releases_the_arrangement
# ---------------------------------------------------------------------------

def test_delivery_axis_delivery_from_storage_closes_everything_and_releases_the_arrangement():
    """Delivery from STORED_OFFSITE closes the order and the package and releases the bailment.

    One posture move stamps `delivered_at`, overwrites the accrual with the FINAL
    55200.00 read off the 2026-12 period, closes the contractual axis, closes the
    scope package, and moves the ACTIVE arrangement to RELEASED with its carrying
    cost frozen at the delivery instant — three whole months from 2026-09-20 at
    1768.13 per month, so 5304.39.

    PRD §3.6: "Both paths then stamp `delivered_at` with the current logical clock, run the final escalation arithmetic, increment the project's `version` by 1, close the contractual axis by moving `commitment_status` from `COMMITTED` to `CLOSED`, and close the scope package by moving it from `BOUGHT_OUT` to `CLOSED`."
    PRD §3.6: "Delivery from `STORED_OFFSITE` does one thing more: the `ACTIVE` storage arrangement moves to `RELEASED` and its `carrying_cost_frozen_at` is stamped with the current clock, freezing its carrying-cost accrual."
    PRD §3.7: "For a stored value of 862500.00 at a monthly rate of 0.1875 percent over three whole months, the storage component rounds from 1617.1875 to 1617.19 and the insurance component rounds from 150.9375 to 150.94, giving 1768.13 per month and 5304.39 in total"
    PRD §3.1: "`bought_out_variance` is the apples-to-apples figure: the sum of `estimated_cost` restricted to packages whose status is `BOUGHT_OUT` or `CLOSED`, less the same `committed_total_cost`, rounded the same way."

    Design: Corner/state_machines/cascade_down_delivery_closes_the_commitment_package_and_releases_the_arrangement
    """
    scenario = _setup_stored_offsite_cycle()
    set_clock("2026-12-20T00:00:00.000Z")
    delivered = validate_success(
        api_client.set_delivery_posture(
            scenario["commitment"]["id"], delivery_posture_payload("DELIVERED"), BUYOUT_MANAGER
        )
    )
    assert_purchase_commitment(delivered)
    assert delivered["delivery_posture"] == "DELIVERED"
    assert delivered["commitment_status"] == "CLOSED"
    assert_instant_equals(delivered["delivered_at"], "2026-12-20T00:00:00.000Z")
    assert delivered["escalation_variant"] == "FINAL"
    assert delivered["escalation_index_period"] == "2026-12"
    assert delivered["escalation_accrued"] == pytest.approx(55200.00, abs=0.005)

    package = read_package(scenario["package"]["id"])
    assert_material_package(package)
    assert package["status"] == "CLOSED"

    arrangement = read_arrangement(scenario["arrangement"]["id"])
    assert_storage_arrangement(arrangement)
    assert arrangement["status"] == "RELEASED"
    assert_instant_equals(arrangement["carrying_cost_frozen_at"], "2026-12-20T00:00:00.000Z")
    assert whole_months_between("2026-09-20T00:00:00.000Z", "2026-12-20T00:00:00.000Z") == 3
    assert arrangement["carrying_cost_accrued"] == pytest.approx(5304.39, abs=0.005)
    assert arrangement["carrying_cost_accrued"] == pytest.approx(
        expected_carrying_cost(862500.00, 0.1875, 3), abs=0.005
    )

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["committed_total_cost"] == pytest.approx(1205200.00, abs=0.005)
    assert project["escalation_contingency_committed"] == pytest.approx(55200.00, abs=0.005)
    assert project["escalation_contingency_remaining"] == pytest.approx(444800.00, abs=0.005)
    assert project["buyout_variance"] == pytest.approx(-5200.00, abs=0.005)
    assert project["bought_out_variance"] == pytest.approx(-5200.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: calculations / threshold_deadband_absorbs_a_two_percent_move_and_the_next_cent_escapes_it
# ---------------------------------------------------------------------------

def test_delivery_axis_deadband_absorbs_exactly_two_percent_and_the_next_cent_escapes():
    """A movement of exactly the deadband yields nothing; 2.05% yields 345.00.

    Two commitments on identical terms (2.0 deadband, 8.0 cap, 40.0 contractor share,
    1150000.00 base) are released in the same 2026-08 clock month. Steel moves
    310.00 → 316.20, exactly 2.0000%, so the eligible movement floors at zero.
    Copper moves 200.00 → 204.10, 2.0500%, leaving 0.05% eligible, 0.03% owner-borne
    and 345.00 accrued. Both record the selected 2026-08 period.

    PRD §3.6: "the eligible movement is the greater of zero and the index movement less `deadband_pct`, so movement wholly inside the deadband yields zero and a falling index yields zero rather than a credit to the owner"
    PRD §3.6: "`escalation_accrued` is `committed_base_cost` multiplied by the shared movement, divided by one hundred, and rounded half up to **two** decimal places"
    PRD §3.6: "Release sets `escalation_variant` to `PROVISIONAL` and records the selected reading's period in `escalation_index_period`."
    PRD §3.1: "`escalation_contingency_committed` is the sum of `escalation_accrued` over that same `COMMITTED`-or-`CLOSED` set, and `escalation_contingency_remaining` is the budget less that figure, rounded half up to 2 decimal places."

    Design: Corner/calculations/threshold_deadband_absorbs_a_two_percent_move_and_the_next_cent_escapes_it
    """
    scenario = _setup_deadband_pair()
    set_clock("2026-08-05T00:00:00.000Z")

    steel = move_posture(scenario["steel_commitment"]["id"], "RELEASED_FOR_FAB")
    copper = move_posture(scenario["copper_commitment"]["id"], "RELEASED_FOR_FAB")
    assert_purchase_commitment(steel)
    assert_purchase_commitment(copper)

    assert steel["escalation_variant"] == "PROVISIONAL"
    assert steel["escalation_index_period"] == "2026-08"
    assert steel["escalation_accrued"] == pytest.approx(0.00, abs=0.005)
    assert steel["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(1150000.00, 310.00, 316.20, 2.0, 8.0, 40.0), abs=0.005
    )

    assert copper["escalation_variant"] == "PROVISIONAL"
    assert copper["escalation_index_period"] == "2026-08"
    assert copper["escalation_accrued"] == pytest.approx(345.00, abs=0.005)
    assert copper["escalation_accrued"] == pytest.approx(
        expected_escalation_accrued(1150000.00, 200.00, 204.10, 2.0, 8.0, 40.0), abs=0.005
    )

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["escalation_contingency_committed"] == pytest.approx(345.00, abs=0.005)
    assert project["escalation_contingency_remaining"] == pytest.approx(499655.00, abs=0.005)
    assert project["committed_total_cost"] == pytest.approx(2300345.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: calculations / input_set_filtering_pending_commitments_leave_committed_cost_alone_but_still_buy_out_the_package
# ---------------------------------------------------------------------------

def test_delivery_axis_pending_commitment_is_excluded_from_cost_but_still_buys_out_its_package():
    """A PENDING buyout contributes nothing to committed cost yet still moves its package.

    Three packages estimated at 1200000.00, 300000.00 and 400000.00 give an
    `estimated_total_cost` of 1900000.00. Only the COMMITTED order counts, so
    `committed_total_cost` is 1150000.00 and the full-programme variance is 750000.00.
    The PENDING order's package is nonetheless BOUGHT_OUT, so the apples-to-apples
    variance is (1200000.00 + 300000.00) − 1150000.00 = 350000.00, while the
    never-quoted package sits in IDENTIFIED with no open quotes.

    PRD §3.1: "`committed_total_cost` is the sum, over the project's commitments whose `commitment_status` is `COMMITTED` or `CLOSED`, of each commitment's `committed_base_cost` plus its `escalation_accrued`; commitments that are `PENDING`, `CANCELLED` or `VOIDED` contribute nothing."
    PRD §3.1: "`estimated_total_cost` is the sum of `estimated_cost` over every scope package belonging to the project — every package, with no status filter at all"
    PRD §3.1: "`buyout_variance` is the full-programme figure: `estimated_total_cost` across every package, less `committed_total_cost`, rounded half up to 2 decimal places."
    PRD §3.1: "`bought_out_variance` is the apples-to-apples figure: the sum of `estimated_cost` restricted to packages whose status is `BOUGHT_OUT` or `CLOSED`, less the same `committed_total_cost`, rounded the same way."
    PRD §3.5: "The addressed package leaves `SOURCING` — or `SOURCING_STALLED`, since a stalled package can still be bought out from a quote created after the stall, provided that quote is `OPEN` — and becomes `BOUGHT_OUT`."
    PRD §3.1: "It begins `IDENTIFIED` with an `open_quote_count` of 0."

    Design: Corner/calculations/input_set_filtering_pending_commitments_leave_committed_cost_alone_but_still_buy_out_the_package
    """
    scenario = _setup_mixed_package_ledger()

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["estimated_total_cost"] == pytest.approx(1900000.00, abs=0.005)
    assert project["committed_total_cost"] == pytest.approx(1150000.00, abs=0.005)
    assert project["buyout_variance"] == pytest.approx(750000.00, abs=0.005)
    assert project["bought_out_variance"] == pytest.approx(350000.00, abs=0.005)
    assert project["escalation_contingency_committed"] == pytest.approx(0.00, abs=0.005)
    assert project["change_order_recovered_amount"] == pytest.approx(0.00, abs=0.005)

    package_b = read_package(scenario["package_b"]["id"])
    assert_material_package(package_b)
    assert package_b["status"] == "BOUGHT_OUT"

    package_c = read_package(scenario["package_c"]["id"])
    assert_material_package(package_c)
    assert package_c["status"] == "IDENTIFIED"
    assert package_c["open_quote_count"] == 0

    commitment_b = read_commitment(scenario["commitment_b"]["id"])
    assert_purchase_commitment(commitment_b)
    assert commitment_b["commitment_status"] == "PENDING"
    assert commitment_b["escalation_variant"] == "NONE"
    assert commitment_b["escalation_accrued"] == pytest.approx(0.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: validations / cascading_validation_delivery_needs_the_exact_month_after_release_took_a_look_back
# ---------------------------------------------------------------------------

def test_delivery_axis_delivery_demands_the_exact_month_release_was_allowed_to_look_back_for():
    """Release looked back to 2026-08; delivery in 2026-09 is refused for want of that month.

    With only the 2026-07 and 2026-08 periods published, releasing at 2026-08-05
    legitimately selects 2026-08 and stamps 12909.90. Moving the clock to 2026-09-05
    and starting fabrication is fine — it touches nothing — but delivery needs a
    reading for exactly 2026-09 and there is none, so the whole delivery is refused
    and the provisional figure stands.

    PRD §3.6: "Both paths require, when a clause is attached, a published reading for that clause's `index_code` whose `period` is **exactly** the current clock month — no look-back is permitted here — and a missing reading for that precise month is `ERR_INDEX_READING_MISSING`, because a delivery cannot be posted into an unpublished month."
    PRD §3.6: "At **release**, the reading used is the one for the clause's `index_code` with the **greatest period at or before** the current clock month"
    PRD §3.6: "**Starting fabrication** moves the posture from `RELEASED_FOR_FAB` to `FABRICATING` and does nothing else at all — it refreshes `updated_at` and touches no money, no project version, and no other row."

    Design: Corner/validations/cascading_validation_delivery_needs_the_exact_month_after_release_took_a_look_back
    """
    scenario = _setup_released(
        release_at="2026-08-05T00:00:00.000Z", readings=_STEEL_READINGS_JUL_AUG
    )
    commitment_id = scenario["commitment"]["id"]
    assert scenario["commitment"]["escalation_index_period"] == "2026-08"

    set_clock("2026-09-05T00:00:00.000Z")
    fabricating = validate_success(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("FABRICATING"), BUYOUT_MANAGER
        )
    )
    assert fabricating["delivery_posture"] == "FABRICATING"

    validate_error(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("DELIVERED"), BUYOUT_MANAGER
        ),
        ApiErrorId.ERR_INDEX_READING_MISSING.value,
        409,
    )

    unchanged = read_commitment(commitment_id)
    assert_purchase_commitment(unchanged)
    assert unchanged["delivery_posture"] == "FABRICATING"
    assert unchanged["delivered_at"] is None
    assert unchanged["commitment_status"] == "COMMITTED"
    assert unchanged["escalation_variant"] == "PROVISIONAL"
    assert unchanged["escalation_index_period"] == "2026-08"
    assert unchanged["escalation_accrued"] == pytest.approx(12909.90, abs=0.005)

    package = read_package(scenario["package"]["id"])
    assert package["status"] == "BOUGHT_OUT"

    project = read_project(scenario["project"]["id"])
    assert project["escalation_contingency_committed"] == pytest.approx(12909.90, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: validations / aggregate_validation_provisional_escalation_must_fit_the_remaining_contingency
# ---------------------------------------------------------------------------

def test_delivery_axis_release_refused_when_provisional_escalation_overruns_the_contingency():
    """A provisional accrual larger than the remaining contingency blocks the release entirely.

    The project set aside only 5000.00, but releasing in the 2026-08 clock month
    against the 322.00 reading would accrue 12909.90 on a 1150000.00 base. The
    fiscal ceiling is checked last and nothing is stamped: the posture stays
    SCHEDULED, `released_for_fab_at` stays null, the variant stays NONE and the
    contingency is untouched at the full 5000.00.

    PRD §3.6: "And the provisional escalation just computed must fit inside the project's `escalation_contingency_remaining`; if it would overrun the remaining contingency the release is refused with `ERR_CONTINGENCY_EXCEEDED` and nothing is stamped."
    PRD §3.1: "A freshly opened project has `version` 1 and reports every money roll-up as 0.00, with the single exception of `escalation_contingency_remaining`, which equals the budget just supplied."
    PRD §3.6: "`escalation_accrued` is `committed_base_cost` multiplied by the shared movement, divided by one hundred, and rounded half up to **two** decimal places"

    Design: Corner/validations/aggregate_validation_provisional_escalation_must_fit_the_remaining_contingency
    """
    scenario = _setup_committed(readings=_STEEL_READINGS_JUL_AUG, budget=5000.00)
    commitment_id = scenario["commitment"]["id"]
    set_clock("2026-08-05T00:00:00.000Z")

    assert expected_escalation_accrued(1150000.00, 310.00, 322.00, 2.0, 8.0, 40.0) == pytest.approx(
        12909.90, abs=0.005
    )
    validate_error(
        api_client.set_delivery_posture(
            commitment_id, delivery_posture_payload("RELEASED_FOR_FAB"), BUYOUT_MANAGER
        ),
        ApiErrorId.ERR_CONTINGENCY_EXCEEDED.value,
        409,
    )

    unchanged = read_commitment(commitment_id)
    assert_purchase_commitment(unchanged)
    assert unchanged["delivery_posture"] == "SCHEDULED"
    assert unchanged["released_for_fab_at"] is None
    assert unchanged["escalation_variant"] == "NONE"
    assert unchanged["escalation_accrued"] == pytest.approx(0.00, abs=0.005)
    assert unchanged["escalation_index_period"] is None
    assert unchanged["commitment_status"] == "COMMITTED"

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["escalation_contingency_committed"] == pytest.approx(0.00, abs=0.005)
    assert project["escalation_contingency_remaining"] == pytest.approx(5000.00, abs=0.005)
    assert project["committed_total_cost"] == pytest.approx(1150000.00, abs=0.005)


# ---------------------------------------------------------------------------
# Queue B: consistency_model / immediate_the_delivery_response_already_carries_the_final_variant_and_the_closures
# ---------------------------------------------------------------------------

def test_delivery_axis_delivery_response_already_carries_the_final_variant_and_the_closures():
    """The delivery response body itself reports FINAL escalation and the closed axis.

    Delivery is synchronous, so no re-read or settling delay is needed: the 200 body
    already carries `commitment_status` CLOSED, `delivery_posture` DELIVERED,
    `escalation_variant` FINAL and the 12909.90 read off the exact 2026-08 clock
    month. A follow-up GET repeats it verbatim, the package is already CLOSED, and
    the project's `version` has reached 5 — issue, countersign, release, delivery on
    top of the version 1 a fresh project carries.

    PRD §3.6: "Both paths then stamp `delivered_at` with the current logical clock, run the final escalation arithmetic, increment the project's `version` by 1, close the contractual axis by moving `commitment_status` from `COMMITTED` to `CLOSED`, and close the scope package by moving it from `BOUGHT_OUT` to `CLOSED`."
    PRD §3.6: "At **delivery**, the reading used is the one whose `period` equals the current clock month exactly. Delivery overwrites `escalation_accrued`, overwrites `escalation_index_period`, and sets `escalation_variant` to `FINAL`"
    PRD §2.4: "A project's `version` increments by exactly 1 only on the five events that genuinely enlarge or unwind a commitment: issuing a purchase commitment, countersigning it, cancelling it, releasing its material for fabrication, and accepting its delivery."
    PRD §3.1: "A freshly opened project has `version` 1 and reports every money roll-up as 0.00, with the single exception of `escalation_contingency_remaining`, which equals the budget just supplied."

    Design: Corner/consistency_model/immediate_the_delivery_response_already_carries_the_final_variant_and_the_closures
    """
    scenario = _setup_fabricating(
        release_at="2026-08-05T00:00:00.000Z", readings=_STEEL_READINGS_JUL_AUG
    )
    delivered = validate_success(
        api_client.set_delivery_posture(
            scenario["commitment"]["id"], delivery_posture_payload("DELIVERED"), BUYOUT_MANAGER
        )
    )
    assert_purchase_commitment(delivered)
    assert delivered["commitment_status"] == "CLOSED"
    assert delivered["delivery_posture"] == "DELIVERED"
    assert delivered["escalation_variant"] == "FINAL"
    assert delivered["escalation_index_period"] == "2026-08"
    assert delivered["escalation_accrued"] == pytest.approx(12909.90, abs=0.005)
    assert_instant_equals(delivered["delivered_at"], "2026-08-05T00:00:00.000Z")

    reread = read_commitment(scenario["commitment"]["id"])
    for field in (
        "commitment_status",
        "delivery_posture",
        "escalation_variant",
        "escalation_index_period",
    ):
        assert reread[field] == delivered[field], f"{field} changed between response and re-read"
    assert reread["escalation_accrued"] == pytest.approx(delivered["escalation_accrued"], abs=0.005)
    assert_instant_equals(reread["delivered_at"], delivered["delivered_at"])

    package = read_package(scenario["package"]["id"])
    assert package["status"] == "CLOSED"

    project = read_project(scenario["project"]["id"])
    assert_project(project)
    assert project["version"] == 5
    assert project["escalation_contingency_committed"] == pytest.approx(12909.90, abs=0.005)
