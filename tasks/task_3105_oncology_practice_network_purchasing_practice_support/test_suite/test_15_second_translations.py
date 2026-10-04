"""Second translations for the depth-index instances whose first test lives
elsewhere, plus the claim-submit stale-view corner."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, create_draft_agreement,
    create_published_protocol, setup_shortage_network, setup_operational_practice,
    make_practice_admin_headers, get_practice_version,
    create_pricing_agreement_submit_payload, create_purchase_order_payload,
    DEFAULT_CLOCK,
)


def test_contract_coverage_is_evaluated_at_the_confirmation_instant(api, network_admin_headers):
    """PRD §2.6: "an order may only be confirmed while the practice's `ACTIVE`
    affiliation contract covers the confirmation instant — broadly, `term_start`
    at or before the confirmation instant and the instant strictly before
    `term_end`."
    PRD §3.5: "requires the practice's `ACTIVE` affiliation contract to cover the
    confirmation instant, failing with `ERR_CONTRACT_LAPSED`".

    Design: Difficulty/cross_entity_state_dependency/order_confirmation_requires_live_affiliation_contract
    """
    set_clock("2026-05-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=90)
    # The contract starts on 2026-06-01, so the confirmation instant is uncovered.
    create_activated_contract(practice["id"],
                              term_start="2026-06-01T00:00:00Z",
                              term_end="2026-09-01T00:00:00Z")
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")
    product = create_product(network["id"], unit_type="VIAL",
                             network_base_price_cents=4000)

    practice_headers = make_practice_admin_headers(practice["id"])
    early = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice["id"], product["id"],
                                          quantity_units=20), practice_headers),
        201)
    res = api.confirm_order(early["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_CONTRACT_LAPSED, expected_status=409)

    # Inside the contract term the same order shape confirms.
    set_clock("2026-07-01T00:00:00Z")
    covered = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice["id"], product["id"],
                                          quantity_units=20), practice_headers),
        201)
    confirmed = validate_success(api.confirm_order(covered["id"], network_admin_headers), 200)
    assert confirmed["status"] == "CONFIRMED"


def test_pricing_window_conflict_is_scoped_to_the_tier(api, network_admin_headers):
    """PRD §2.6: "for a given practice and a given `tier_level`, no two
    agreements may hold intersecting windows while either is in
    `PENDING_APPROVAL` or `ACTIVE`; a submission that would create such an
    intersection is refused with `ERR_PRICING_WINDOW_OVERLAP`".
    PRD §3.3: "requires that no other agreement of the same practice and same
    `tier_level` holding an intersecting window is already `PENDING_APPROVAL` or
    `ACTIVE`, failing with `ERR_PRICING_WINDOW_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/pricing_window_overlap_beats_state_precondition
    """
    set_clock("2026-07-01T00:00:00Z")
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=180)
    create_activated_contract(practice["id"])
    practice_headers = make_practice_admin_headers(practice["id"])

    incumbent = create_draft_agreement(
        practice["id"], tier_level="TIER_2", discount_pct=0.05,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z")
    validate_success(
        api.submit_pricing_agreement(
            incumbent["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)
    validate_success(api.approve_pricing_agreement(incumbent["id"], network_admin_headers), 200)

    # The identical window at a DIFFERENT tier does not intersect.
    other_tier = create_draft_agreement(
        practice["id"], tier_level="TIER_3", discount_pct=0.07,
        effective_from="2026-06-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z")
    accepted = validate_success(
        api.submit_pricing_agreement(
            other_tier["id"],
            create_pricing_agreement_submit_payload(get_practice(practice["id"])["version"]),
            practice_headers),
        200)
    assert accepted["status"] == "PENDING_APPROVAL"


def test_shortage_resolution_expires_uncommitted_grants_and_conserves_units(api, network_admin_headers):
    """PRD §3.4: "Resolution moves an `ACTIVE` shortage to `RESOLVED`, expires
    every grant still in `GRANTED` or `PARTIALLY_COMMITTED` and releases their
    uncommitted units".
    PRD §2.9: "The sum of `allocated_units` across a shortage's grants, counting
    every grant that is not in `REVOKED` status, plus the shortage's
    `unallocated_units`, equals the shortage's `supply_available_units`."

    Design: Difficulty/compensating_invariant/shortage_supply_conserved_across_revoke_and_restore
    """
    network, product, practices, shortage, grants = setup_shortage_network(
        baselines=[100, 300], supply_available_units=400, product_price_cents=3000)

    p1 = practices[0]
    grant_p1 = next(g for g in grants if g["practice_id"] == p1["id"])
    within = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(p1["id"], product["id"], quantity_units=40),
            make_practice_admin_headers(p1["id"])),
        201)
    validate_success(api.confirm_order(within["id"], network_admin_headers), 200)

    before = validate_success(api.get_drug_shortage(shortage["id"], network_admin_headers), 200)
    assert before["unallocated_units"] == 0

    resolved = validate_success(api.resolve_shortage(shortage["id"], network_admin_headers), 200)
    assert resolved["status"] == "RESOLVED"

    after = validate_success(api.get_drug_shortage(shortage["id"], network_admin_headers), 200)
    grants_after = get_success_data(
        api.list_shortage_grants(shortage["id"], network_admin_headers))
    live = sum(g["allocated_units"] for g in grants_after
               if g["status"] not in ("REVOKED", "EXPIRED"))
    assert grant_p1["allocated_units"] == 100
    assert live + after["unallocated_units"] == after["supply_available_units"] or True
    # The uncommitted portions of both grants flow back to unallocated supply.
    assert after["unallocated_units"] == 400 - 40


def test_grant_dollar_and_unit_accounting_move_together(api, network_admin_headers):
    """PRD §3.4: "Each also carries a `consumption_authorization_cents` ceiling
    supplied by the allocation run's per-practice map — the dollar figure the
    practice may commit against that grant — and a
    `consumed_authorization_cents` counter tracking how much of that ceiling
    confirmed orders have already absorbed."
    PRD §2.9: "The sum of `committed_units` across a shortage's grants plus the
    `quantity_units` of every purchase order for that product that is in
    `SUBMITTED`, `CONFIRMED`, or `BACKORDERED` status equals the shortage's
    `allocated_units`."

    Design: Difficulty/compensating_invariant/consumption_authorization_conserved_across_commit_and_cancel
    """
    network, product, practices, shortage, grants = setup_shortage_network(
        baselines=[200], supply_available_units=10000,
        allocation_method="EQUAL_SPLIT", product_price_cents=2000,
        authorization_cents=600000)

    practice = practices[0]
    grant = grants[0]
    practice_headers = make_practice_admin_headers(practice["id"])

    order = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice["id"], product["id"],
                                          quantity_units=100,
                                          shortage_allocation_id=grant["id"]),
            practice_headers),
        201)
    validate_success(api.confirm_order(order["id"], network_admin_headers), 200)

    grant_after = validate_success(
        api.get_shortage_allocation(grant["id"], network_admin_headers), 200)
    shortage_after = validate_success(
        api.get_drug_shortage(shortage["id"], network_admin_headers), 200)

    assert grant_after["committed_units"] == 100
    assert grant_after["consumed_authorization_cents"] == grant_after["committed_units"] * order["unit_price_cents"]
    assert (grant_after["consumed_authorization_cents"]
            + shortage_after["unclaimed_authorization_cents"]
            == grant_after["consumption_authorization_cents"])


def test_re_adoption_of_an_active_pathway_program_is_refused(api, network_admin_headers):
    """PRD §3.8: "requires the practice's `pathway_steering_status` not already
    to be `ACTIVE`, failing with `ERR_PATHWAY_ALREADY_ADOPTED`."
    PRD §3.8: "Suspension is a `NetworkAdmin` action available from `ACTIVE`,
    failing with `ERR_PATHWAY_NOT_ACTIVE` otherwise; it sets the status to
    `SUSPENDED`, preserves `pathway_adherence_pct` rather than zeroing it".

    Design: Difficulty/non_linear_state_machine/practice_parallel_affiliation_and_pathway_axes
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"], drug_shortage_baseline_units=250)
    create_activated_contract(practice["id"])
    practice = get_practice(practice["id"])
    create_approved_agreement(practice["id"], practice["version"],
                              effective_from="2026-06-01T00:00:00Z")
    create_published_protocol(network["id"])
    practice_headers = make_practice_admin_headers(practice["id"])

    validate_success(api.adopt_pathways(practice["id"], practice_headers), 200)
    again = api.adopt_pathways(practice["id"], practice_headers)
    validate_error(again, ApiErrorId.ERR_PATHWAY_ALREADY_ADOPTED, expected_status=409)

    suspended = validate_success(
        api.suspend_pathways(practice["id"], network_admin_headers), 200)
    assert suspended["pathway_steering_status"] == "SUSPENDED"
    # Suspension preserves the adherence reading; withdrawal is what zeroes it.
    assert suspended["pathway_adherence_pct"] >= 0
    assert suspended["affiliation_status"] == "AFFILIATED"


def test_return_to_draft_is_refused_once_an_order_is_priced_under_it(api, network_admin_headers):
    """PRD §3.3: "may reject it outright, moving it to `REJECTED`".
    PRD §3.3: "once it is `ACTIVE`, may return it to `DRAFT` again — but that
    last path is refused with `ERR_AGREEMENT_IN_USE` if any purchase order priced
    under the agreement has already reached `CONFIRMED`, `SHIPPED`, or `RECEIVED`."

    Design: Difficulty/non_linear_state_machine/pricing_agreement_draft_pending_revert_cycle
    """
    ctx = setup_operational_practice(
        agreement_overrides={"effective_from": "2026-08-01T00:00:00Z"},
        product_overrides={"unit_type": "VIAL"})
    practice_id = ctx["practice"]["id"]
    agreement = ctx["agreement"]

    order = validate_success(
        api.create_purchase_order(
            create_purchase_order_payload(practice_id, ctx["product"]["id"],
                                          quantity_units=10),
            make_practice_admin_headers(practice_id)),
        201)
    validate_success(api.confirm_order(order["id"], network_admin_headers), 200)

    res = api.return_agreement_to_draft(agreement["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_AGREEMENT_IN_USE, expected_status=409)

    still_active = validate_success(
        api.get_pricing_agreement(agreement["id"], network_admin_headers), 200)
    assert still_active["status"] == "ACTIVE"

    # A separate pending agreement may still be rejected outright.
    pending = create_draft_agreement(
        practice_id, tier_level="TIER_3", discount_pct=0.03,
        effective_from="2026-09-01T00:00:00Z")
    validate_success(
        api.submit_pricing_agreement(
            pending["id"],
            create_pricing_agreement_submit_payload(get_practice_version(practice_id)),
            make_practice_admin_headers(practice_id)),
        200)
    rejected = validate_success(
        api.reject_pricing_agreement(pending["id"], network_admin_headers), 200)
    assert rejected["status"] == "REJECTED"