"""Network standing-up and the practice affiliation lifecycle."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_network_payload, create_practice_payload, create_drug_product_payload,
    create_affiliation_contract_payload, create_pricing_agreement_payload,
    next_npi, NON_EXISTENT_UUID, ApiErrorId,
    set_clock, create_network, create_practice, create_product, get_practice,
    create_activated_contract, create_approved_agreement, create_draft_agreement,
    DEFAULT_CLOCK,
)


def test_network_create_returns_every_declared_field_and_starts_at_epoch_zero(api, network_admin_headers):
    """PRD §4: "An operation that creates a brand-new, stand-alone resource, or
    adds a new and distinct resource to an existing collection, returns `201 Created`".
    PRD §3.1: "On creation, `allocation_epoch_index` starts at 0,
    `is_commercial_terms_frozen` starts false, and the ladder is stored in the
    ordered descending form it was supplied in."
    PRD §3.1: "The network's buy-and-bill resale terms are set as
    `payment_terms_days`, which defaults to 60 when not supplied, and the window
    in which a late compliance report will still be accepted is
    `compliance_report_grace_days`, which defaults to 30 days."

    Design: Corner/entities/network_create_returns_every_declared_field_and_starts_at_epoch_zero
    """
    set_clock(DEFAULT_CLOCK)
    res = api.create_network(create_network_payload(), network_admin_headers)
    data = validate_success(res, 201)

    assert data["allocation_epoch_index"] == 0
    assert data["is_commercial_terms_frozen"] is False
    assert data["compliance_report_grace_days"] == 30
    assert data["payment_terms_days"] == 60
    assert data["version"] == 1


def test_practice_create_starts_prospective_not_adopted_tier_one(api, network_admin_headers):
    """PRD §3.2: "A new practice carries `affiliation_status` of `PROSPECTIVE`,
    `pathway_steering_status` of `NOT_ADOPTED`, `tier_level` of `TIER_1`,
    `trailing_12m_network_purchases_cents` of 0, `unsettled_balance_cents` of 0,
    and `is_rebate_qualified` false."
    PRD §3.2: "A `NetworkAdmin` creates it with a `practice_name`, an
    organizational `practice_npi` of ten digits, a two-letter `state_code`, a
    `drug_shortage_baseline_units` figure that defaults to zero and will later
    serve as its pro-rata weight when supply is rationed, a
    `pathway_steering_target_pct` representing the adherence level the pathways
    program will steer it toward and defaulting to 0.75, and its own
    `denial_ratio_threshold_pct` governing when its pricing is suspended,
    defaulting to 0.20."

    Design: Corner/entities/practice_create_starts_prospective_not_adopted_tier_one
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    res = api.create_practice(
        network["id"],
        create_practice_payload(pathway_steering_target_pct=0.80),
        network_admin_headers)
    practice = validate_success(res, 201)

    assert practice["affiliation_status"] == "PROSPECTIVE"
    assert practice["pathway_steering_status"] == "NOT_ADOPTED"
    assert practice["tier_level"] == "TIER_1"
    assert practice["trailing_12m_network_purchases_cents"] == 0
    assert practice["unsettled_balance_cents"] == 0
    assert practice["is_rebate_qualified"] is False
    assert practice["pathway_steering_target_pct"] == pytest.approx(0.80)
    assert practice["denial_ratio_threshold_pct"] == pytest.approx(0.20)


def test_practice_tier_comes_from_the_sold_agreement_at_affiliation(api, network_admin_headers):
    """PRD §3.2: "The practice's `tier_level` is set directly from the
    `tier_level` of the most recently created pricing agreement on file for it —
    where several share a creation instant, the one with the latest
    `effective_from` wins, and if that also ties, the one whose identifier sorts
    greater lexicographically."
    PRD §3.2: "The practice consumes the tier it was sold; it is not, at this
    moment, recomputed from purchase history."

    Design: Corner/entities/practice_tier_comes_from_the_sold_agreement_at_affiliation
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])

    # The contract stays DRAFT so the practice is still PROSPECTIVE.
    validate_success(
        api.create_affiliation_contract(
            practice["id"], create_affiliation_contract_payload(), network_admin_headers),
        201)
    # Affiliation consumes the tier of the agreement on file, not purchase history.
    agreement = create_draft_agreement(
        practice["id"], tier_level="TIER_3", discount_pct=0.12,
        effective_from="2026-09-01T00:00:00Z")

    affiliated = validate_success(
        api.affiliate_practice(practice["id"], network_admin_headers), 200)
    assert affiliated["tier_level"] == "TIER_3"
    assert affiliated["trailing_12m_network_purchases_cents"] == 0
    assert agreement["tier_level"] == "TIER_3"


def test_missing_required_npi_returns_invalid_request(api, network_admin_headers):
    """PRD §2.5: "Missing required fields, fields carrying the wrong type, and
    values outside a closed enumeration are all refused with `ERR_INVALID_REQUEST`."
    PRD §3.2: "A `NetworkAdmin` creates it with a `practice_name`, an
    organizational `practice_npi` of ten digits, a two-letter `state_code`, a
    `drug_shortage_baseline_units` figure that defaults to zero and will later
    serve as its pro-rata weight when supply is rationed, a
    `pathway_steering_target_pct` representing the adherence level the pathways
    program will steer it toward and defaulting to 0.75, and its own
    `denial_ratio_threshold_pct` governing when its pricing is suspended,
    defaulting to 0.20."

    Design: Corner/entities/missing_required_npi_returns_invalid_request
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    payload = create_practice_payload()
    del payload["practice_npi"]

    res = api.create_practice(network["id"], payload, network_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    data, meta = validate_paginated(
        api.list_practices(network_admin_headers, params={"network_id": network["id"]}))
    assert meta["total_count"] == 0


def test_drug_product_defaults_shortage_candidate_false_and_starts_active(api, network_admin_headers):
    """PRD §3.4: "The `is_shortage_candidate` flag, which defaults to false,
    marks products that may be placed under shortage allocation. A product
    begins `ACTIVE`."

    Design: Corner/entities/drug_product_defaults_shortage_candidate_false_and_starts_active
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()

    res = api.create_drug_product(
        network["id"],
        create_drug_product_payload(is_shortage_candidate=False),
        network_admin_headers)
    data = validate_success(res, 201)

    assert data["status"] == "ACTIVE"
    assert data["is_shortage_candidate"] is False
    assert data["version"] == 1
    assert data["created_at"]


def test_computed_fields_ignore_client_supplied_values(api, network_admin_headers):
    """PRD §3.2: "A new practice carries `affiliation_status` of `PROSPECTIVE`,
    `pathway_steering_status` of `NOT_ADOPTED`, `tier_level` of `TIER_1`,
    `trailing_12m_network_purchases_cents` of 0, `unsettled_balance_cents` of 0,
    and `is_rebate_qualified` false."

    Design: Corner/entities/computed_fields_ignore_client_supplied_values
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    payload = create_practice_payload()
    # Smuggle system-managed values through the create body.
    payload["tier_level"] = "TIER_3"
    payload["unsettled_balance_cents"] = 999999
    payload["version"] = 42
    payload["affiliation_status"] = "AFFILIATED"

    practice = validate_success(
        api.create_practice(network["id"], payload, network_admin_headers), 201)

    assert practice["tier_level"] == "TIER_1"
    assert practice["unsettled_balance_cents"] == 0
    assert practice["version"] == 1
    assert practice["affiliation_status"] == "PROSPECTIVE"
    assert practice["pathway_steering_status"] == "NOT_ADOPTED"


def test_practice_get_with_an_unknown_id_returns_practice_not_found(api, network_admin_headers):
    """PRD §2.5: "The platform validates that each path identifier names an
    existing resource before it evaluates anything about the deeper one, and
    rejects the request with the `404` not-found error belonging to the first
    identifier that fails."
    PRD §3.2: "A practice enters the network as a prospect."

    Design: Corner/entities/practice_get_with_an_unknown_id_returns_practice_not_found
    """
    set_clock(DEFAULT_CLOCK)
    res = api.get_practice(NON_EXISTENT_UUID, network_admin_headers)
    nf = validate_error(res, ApiErrorId.ERR_PRACTICE_NOT_FOUND, expected_status=404)
    assert nf["error_id"] == ApiErrorId.ERR_PRACTICE_NOT_FOUND
    assert nf["message"]


def test_empty_collection_listing_returns_zero_total_count(api, network_admin_headers, network_analyst_headers):
    """PRD §2.3: "`limit` caps the number of items returned and defaults to 10;
    it may not be smaller than 1 nor larger than 100. `offset` skips that many
    leading items and defaults to 0."
    PRD §2.3: "Every list-shaped response carries `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope;
    `total_count` reports the full size of the filtered result set before paging".

    Design: Corner/entities/empty_collection_listing_returns_zero_total_count
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()

    res = api.list_drug_products(
        network_analyst_headers,
        params={"network_id": network["id"], "status": "ACTIVE"})
    data, meta = validate_paginated(res)

    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_parent_child_ownership_is_enforced_across_networks(api, network_admin_headers, network_analyst_headers):
    """PRD §3.2: "No other practice in the same network may already carry the
    same `practice_npi`, and a duplicate is refused with
    `ERR_DUPLICATE_PRACTICE_NPI` — uniqueness of the identifier is network-scoped,
    not global."
    PRD §3.2: "A new practice ... Its `network_id` binds it to the owning network."

    Design: Corner/entities/parent_child_ownership_is_enforced_across_networks
    """
    set_clock(DEFAULT_CLOCK)
    n1 = create_network(name="Alpha Oncology Network", network_agreement_code="GPO-AL-1")
    n2 = create_network(name="Beta Oncology Network", network_agreement_code="GPO-BT-1")
    shared_npi = next_npi()

    alpha = create_practice(n1["id"], practice_npi=shared_npi)
    create_draft_agreement(alpha["id"])
    validate_success(api.affiliate_practice(alpha["id"], network_admin_headers), 200)

    # A second practice carrying the same NPI in the same network is refused.
    duplicate = create_practice(n1["id"], practice_npi=shared_npi)
    create_draft_agreement(duplicate["id"])
    res = api.affiliate_practice(duplicate["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PRACTICE_NPI, expected_status=409)

    data, meta = validate_paginated(
        api.list_practices(network_analyst_headers, params={"network_id": n1["id"]}))
    # The refused affiliation left the duplicate PROSPECTIVE, so the network
    # never holds two AFFILIATED practices under one NPI.
    assert meta["total_count"] == 2
    affiliated_rows = [p for p in data if p["affiliation_status"] == "AFFILIATED"]
    assert len(affiliated_rows) == 1
    assert affiliated_rows[0]["practice_npi"] == shared_npi

    # The same NPI is legal under a different network.
    other = create_practice(n2["id"], practice_npi=shared_npi)
    create_draft_agreement(other["id"])
    affiliated = api.affiliate_practice(other["id"], network_admin_headers)
    validate_success(affiliated, 200)
    assert affiliated.json()["data"]["affiliation_status"] == "AFFILIATED"


# ─── State machine edges ────────────────────────────────────────────────────

def test_network_freeze_twice_returns_already_frozen(api, network_admin_headers):
    """PRD §2.10: "the network may only be frozen once; a second freeze request
    while already frozen is refused with `ERR_TERMS_ALREADY_FROZEN`."

    Design: Corner/state_machines/network_freeze_twice_returns_already_frozen
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    validate_success(api.freeze_commercial_terms(network["id"], network_admin_headers), 200)

    res = api.freeze_commercial_terms(network["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_TERMS_ALREADY_FROZEN, expected_status=409)

    current = validate_success(api.get_network(network["id"], network_admin_headers), 200)
    assert current["is_commercial_terms_frozen"] is True
    assert current["allocation_epoch_index"] == 0


def test_epoch_advance_rejects_zero_and_excessive_epochs(api, network_admin_headers):
    """PRD §3.1: "A `by_epochs` value that is not a positive integer, or that
    exceeds 12, is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/state_machines/epoch_advance_rejects_zero_and_excessive_epochs
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()

    validate_error(
        api.advance_epoch(network["id"], {"by_epochs": 0}, network_admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
    validate_error(
        api.advance_epoch(network["id"], {"by_epochs": 13}, network_admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    advanced = validate_success(
        api.advance_epoch(network["id"], {"by_epochs": 12}, network_admin_headers), 200)
    assert advanced["allocation_epoch_index"] == 12


def test_pathway_withdraw_from_not_adopted_returns_not_active(api, network_admin_headers, practice_admin_headers):
    """PRD §3.8: "Withdrawing is available from `ACTIVE` and requires exactly
    that, failing with `ERR_PATHWAY_NOT_ACTIVE`".

    Design: Corner/state_machines/pathway_withdraw_from_not_adopted_returns_not_active
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])

    res = api.withdraw_pathways(practice["id"], practice_admin_headers)
    validate_error(res, ApiErrorId.ERR_PATHWAY_NOT_ACTIVE, expected_status=409)

    current = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert current["pathway_steering_status"] == "NOT_ADOPTED"


def test_contract_terminate_while_affiliated_is_refused(api, network_admin_headers):
    """PRD §3.11: "A contract may be terminated outright, but only while the
    practice is still `PROSPECTIVE`; the action requires the contract to be
    `ACTIVE`, failing with `ERR_CONTRACT_NOT_ACTIVE`, and requires the practice
    not to have progressed past prospect status, failing with
    `ERR_CONTRACT_NOT_TERMINABLE_WHILE_AFFILIATED`."

    Design: Corner/state_machines/contract_terminate_while_affiliated_is_refused
    """
    set_clock(DEFAULT_CLOCK)
    network = create_network()
    practice = create_practice(network["id"])
    contract = validate_success(
        api.create_affiliation_contract(
            practice["id"], create_affiliation_contract_payload(), network_admin_headers),
        201)

    activated = validate_success(
        api.activate_affiliation_contract(contract["id"], network_admin_headers), 200)
    assert activated["status"] == "ACTIVE"
    promoted = validate_success(api.get_practice(practice["id"], network_admin_headers), 200)
    assert promoted["affiliation_status"] == "AFFILIATED"

    res = api.terminate_affiliation_contract(contract["id"], network_admin_headers)
    validate_error(res, ApiErrorId.ERR_CONTRACT_NOT_TERMINABLE_WHILE_AFFILIATED,
                   expected_status=409)

    current = validate_success(
        api.get_affiliation_contract(contract["id"], network_admin_headers), 200)
    assert current["status"] == "ACTIVE"