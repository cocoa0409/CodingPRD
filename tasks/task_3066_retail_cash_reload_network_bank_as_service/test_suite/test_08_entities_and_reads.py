"""Entity creation, retrieval, listing and the loss-allocation waterfall."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, validate_paginated,
    get_success_data, set_clock, setup_network, create_sponsor, create_program,
    create_brand, create_agreement, create_location, create_account,
    create_loss_allocation, setup_settled_load, get_program, get_sponsor,
    get_agreement, make_program_manager_headers, OFFICER, ADMIN,
    NON_EXISTENT_UUID,
)


def test_bank_sponsor_create_returns_every_declared_field():
    """PRD §3.1: "A newly registered sponsor reports `active_program_count` of 0,
    `oversight_reviews_completed` of 0, and `is_capacity_exhausted` false."
    PRD §3.1: "an optional `oversight_tier` that is either `TIER_1` or `TIER_2`
    and defaults to `TIER_2` when omitted".

    Design: Corner/entities/bank_sponsor_create_returns_every_declared_field
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_bank_sponsor(
        {"legal_name": "Cedar Trust Bank", "charter_state_code": "UT",
         "sponsorship_capacity_programs": 10,
         "regulator_exam_due_at": "2027-03-01T00:00:00Z"},
        ADMIN)
    bank = validate_success(resp, 201)
    assert bank["legal_name"] == "Cedar Trust Bank"
    assert bank["charter_state_code"] == "UT"
    assert bank["oversight_tier"] == "TIER_2"
    assert bank["active_program_count"] == 0
    assert bank["oversight_reviews_completed"] == 0
    assert bank["is_capacity_exhausted"] is False
    assert bank["version"] == 1


def test_program_get_round_trips_stored_configuration():
    """PRD §3.1: "A fresh program opens with `compliance_posture` of `OPEN`, a
    `posture_breach_count` of 0, a `posture_score` of 0.00, and an
    `open_aml_alert_count` of 0."
    PRD §2.5: "Every entity in this system — `BankSponsor`, `Program`,
    `BrandPartner`, `RetailerAgreement`, `ReloadLocation`, `CardAccount`,
    `LoadTransaction`, `AmlAlert`, `DisputeCase`, `LossAllocation`,
    `SettlementBatch` and `FloatWindow` — carries the full set of
    system-managed properties."

    Design: Corner/entities/program_get_round_trips_stored_configuration
    """
    set_clock("2026-09-01T00:00:00Z")
    bank = create_sponsor(oversight_tier="TIER_1")
    program = create_program(bank["id"], name="Harbor Reload Program",
                             program_type="OWN_BANK_PROGRAM",
                             settlement_cycle="WEEKLY",
                             oversight_review_due_at="2026-12-15T00:00:00Z")
    fetched = get_program(program["id"])
    assert fetched["name"] == "Harbor Reload Program"
    assert fetched["program_type"] == "OWN_BANK_PROGRAM"
    assert fetched["settlement_cycle"] == "WEEKLY"
    assert fetched["compliance_posture"] == "OPEN"
    assert fetched["posture_score"] == pytest.approx(0.00, abs=0.01)
    assert fetched["open_aml_alert_count"] == 0
    assert fetched["is_oversight_overdue"] is False


def test_programs_list_paginates_and_filters_by_sponsor():
    """PRD §2.3: "`total_count` is the number of rows matching the query before
    pagination is applied, and `has_more` is true when further rows remain beyond
    the returned page."
    PRD §4: "List programs, optionally filtered by sponsor bank".

    Design: Corner/entities/programs_list_paginates_and_filters_by_sponsor
    """
    set_clock("2026-09-01T00:00:00Z")
    bank_a = create_sponsor(legal_name="Cedar Trust Bank")
    bank_b = create_sponsor(legal_name="Granite National Bank", charter_state_code="OH")
    create_program(bank_a["id"], name="Harbor One")
    create_program(bank_a["id"], name="Harbor Two")
    create_program(bank_b["id"], name="Granite One")
    resp = api_client.list_programs(ADMIN, {"sponsor_bank_id": bank_a["id"],
                                            "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert all(row["sponsor_bank_id"] == bank_a["id"] for row in data)


def test_program_not_found_for_unknown_uuid():
    """PRD §2.4: "the server resolves them left to right and rejects the request
    with `ERR_ENTITY_NOT_FOUND` (HTTP 404) at the first identifier that does not
    correspond to a stored row".

    Design: Corner/entities/program_not_found_for_unknown_uuid
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ENTITY_NOT_FOUND, 404)


def test_brand_partner_required_fields_enforced():
    """PRD §3.2: "onboards a third-party brand by submitting a `BrandPartner`
    payload naming the `program_id` it sits under, the `brand_name`, and a
    `services_scope` drawn as a subset of `CARD_ISSUANCE`, `LEDGERING`,
    `COMPLIANCE_OVERSIGHT` and `DISPUTE_HANDLING`."
    PRD §5: `ERR_INVALID_REQUEST` | 400.

    Design: Corner/entities/brand_partner_required_fields_enforced
    """
    net = setup_network()
    program = get_program(net["program"]["id"])
    resp = api_client.create_brand_partner(
        {"program_id": net["program"]["id"], "brand_name": "No Scope Brand",
         "expected_program_version": program["version"]},
        OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    # omitting card_issuance_enabled is accepted and defaulted to true
    created = get_success_data(api_client.create_brand_partner(
        {"program_id": net["program"]["id"], "brand_name": "Defaulted Brand",
         "services_scope": ["LEDGERING"], "ledgering_enabled": True,
         "expected_program_version": program["version"]},
        OFFICER))
    assert created["card_issuance_enabled"] is True
    assert created["compliance_oversight_enabled"] is False


def test_brand_partner_computed_fields_ignore_client_input():
    """PRD §3.2: "The new brand starts in `PENDING_ONBOARDING` with a
    `suspension_source` of `NONE`."
    PRD §3.2: "The `onboarding_checklist_complete` flag is a derived readiness
    signal: it is true exactly when every element of the declared `services_scope`
    has its enabling flag set true."

    Design: Corner/entities/brand_partner_computed_fields_ignore_client_input
    """
    net = setup_network()
    program = get_program(net["program"]["id"])
    created = get_success_data(api_client.create_brand_partner(
        {"program_id": net["program"]["id"], "brand_name": "Pushy Brand",
         "services_scope": ["CARD_ISSUANCE", "LEDGERING", "COMPLIANCE_OVERSIGHT", "DISPUTE_HANDLING"],
         "card_issuance_enabled": True, "ledgering_enabled": True,
         "compliance_oversight_enabled": True,
         "partner_status": "ACTIVE",
         "expected_program_version": program["version"]},
        OFFICER))
    assert created["partner_status"] == "PENDING_ONBOARDING"
    assert created["suspension_source"] == "NONE"
    assert created["open_dispute_count"] == 0
    assert created["onboarding_checklist_complete"] is True


def test_float_window_zero_amount_is_refused():
    """PRD §3.8: "the `float_amount_cents` of cash, which must be at least 1".
    PRD §5: `ERR_INVALID_REQUEST` | 400.

    Design: Corner/entities/float_window_type_constraints_reject_bad_enum_and_zero_amount
    """
    net = setup_network()
    resp = api_client.create_float_window(
        {"reload_location_id": net["location"]["id"],
         "window_start_at": "2026-09-01T14:00:00Z",
         "window_end_at": "2026-09-01T15:00:00Z",
         "armored_carrier": "Loomis",
         "float_amount_cents": 0,
         "buffer_minutes": 120},
        net["pm_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_bank_sponsor_capacity_counter_is_derived():
    """PRD §3.1: "The act of creating the program also advances its sponsor: the
    sponsor's `active_program_count` increases by one and its
    `is_capacity_exhausted` flag is recomputed, becoming true once the count
    reaches the bank's `sponsorship_capacity_programs`."

    Design: Corner/entities/bank_sponsor_capacity_counter_is_derived
    """
    set_clock("2026-09-01T00:00:00Z")
    bank = create_sponsor(sponsorship_capacity_programs=2)
    create_program(bank["id"], name="Harbor One")
    create_program(bank["id"], name="Harbor Two")
    sponsor = get_sponsor(bank["id"])
    assert sponsor["active_program_count"] == 2
    assert sponsor["is_capacity_exhausted"] is True
    assert sponsor["oversight_reviews_completed"] == 0


def test_reload_location_requires_a_valid_parent_agreement():
    """PRD §2.4: "Identifiers supplied in the request body — a sponsor named by a
    program, an account named by a load, an agreement named by a location — are
    resolved separately, and an unresolvable body reference is rejected with
    `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/reload_location_requires_valid_parent_agreement
    """
    net = setup_network()
    resp = api_client.create_reload_location(
        {"retailer_agreement_id": NON_EXISTENT_UUID, "location_code": "QM-999",
         "state_code": "TX", "register_count": 1},
        net["pm_headers"])
    validate_error(resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND, 404)


def test_loss_allocation_split_applies_the_bank_percentage_to_the_remainder():
    """PRD §3.8: "First the retailer's layer is capped at the lesser of the total
    loss and the cited agreement's `per_transaction_limit_cents` ... What remains
    after the retailer's share is allocated next to the bank at a percentage that
    depends on the program type: 15 percent for a `BAAS_PROGRAM_MANAGER` program".
    PRD §3.8: "the program share is the remainder minus the bank share."

    Design: Corner/calculations/loss_allocation_split_applies_bank_percentage
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    load = setup_settled_load(net, principal_cents=12000)
    allocation = create_loss_allocation(net["program"], load, net["agreement"],
                                        total_loss_cents=18000)
    assert allocation["retailer_share_cents"] == 15000
    assert allocation["bank_share_cents"] == 450
    assert allocation["program_share_cents"] == 2550
    assert (allocation["retailer_share_cents"] + allocation["program_share_cents"]
            + allocation["bank_share_cents"]) == 18000
    assert allocation["allocation_status"] == "DRAFT"


def test_own_bank_program_takes_no_bank_loss_slice():
    """PRD §3.8: "15 percent for a `BAAS_PROGRAM_MANAGER` program, and zero percent
    for an `OWN_BANK_PROGRAM`, so a bank-run program never takes a loss slice."

    Design: Corner/calculations/loss_allocation_split_applies_bank_percentage
    """
    net = setup_network(clock="2026-09-01T00:00:00Z",
                        program_overrides={"program_type": "OWN_BANK_PROGRAM"})
    load = setup_settled_load(net, principal_cents=12000)
    allocation = create_loss_allocation(net["program"], load, net["agreement"],
                                        total_loss_cents=18000)
    assert allocation["bank_share_cents"] == 0
    assert allocation["retailer_share_cents"] == 15000
    assert allocation["program_share_cents"] == 3000