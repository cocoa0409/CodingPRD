"""The attribute review cycle and the weighted data-quality score."""

from test_helpers import (
    ApiErrorId,
    attach_source_document,
    create_attribute_claim,
    create_property,
    get_property,
    get_success_data,
    propose_and_verify,
    propose_value,
    verify,
    setup_completeness_divergence_property,
    setup_provider_org,
    setup_subscriber_org,
    setup_two_attribute_completeness_property,
    setup_active_contract,
    set_logical_clock,
    validate_error,
    validate_success,
)


def test_completeness_provisional_variant_scores_stale_sourced_claims_softly(api):
    """PRD §3.4: "Under `PROVISIONAL`, a `VERIFIED` attribute whose source is missing or stale scores 0.6, the `WEIGHT_VERIFIED_UNSOURCED` weight."

    Design: Difficulty/dual_variant_calc/completeness_provisional_vs_final_on_property
    """
    set_logical_clock("2026-03-01T00:00:00Z")
    provider = setup_provider_org()
    fixture = setup_completeness_divergence_property(provider)
    snapshot = get_property(fixture["property_id"], provider["creator_headers"])
    # three verified attributes: 1.0 + 0.6 + 0.6 of 3, less 0.1 per stale source.
    assert snapshot["completeness_pct"] == 73.13
    assert snapshot["stale_source_count"] == 2
    assert snapshot["attribute_verified_count"] == 3


def test_completeness_final_variant_scores_stale_sourced_claims_at_zero(api):
    """PRD §3.4: "Under `FINAL`, that same unevidenced claim scores 0.0 — once a record is published, a claim with no fresh evidence behind it is worth nothing."

    Design: Difficulty/dual_variant_calc/completeness_provisional_vs_final_on_property
    """
    set_logical_clock("2026-03-01T00:00:00Z")
    provider = setup_provider_org()
    fixture = setup_completeness_divergence_property(provider)
    before = get_property(fixture["property_id"], provider["creator_headers"])
    after = validate_success(
        api.finalize_property(fixture["property_id"], provider["creator_headers"]), 200
    )
    assert before["completeness_pct"] == 73.13
    assert after["completeness_pct"] == 33.13
    assert round(before["completeness_pct"] - after["completeness_pct"], 2) == 40.00
    assert after["research_status"] == "VERIFIED"
    assert after["attribute_verified_count"] == 3
    assert after["stale_source_count"] == 2


def test_completeness_canonical_fixture_matches_the_published_literals(api):
    """PRD §3.4: "On the canonical fixture of a two-attribute property in which one verified attribute rests on a fresh deed and the other verified attribute rests on a source that is 243 days old, with no other sources present, the provisional score is 79.90 and the final score is 49.90 — the published value is exactly 30.00 points lower on identical rows."

    Design: Difficulty/dual_variant_calc/completeness_provisional_vs_final_on_property
    """
    set_logical_clock("2026-03-01T00:00:00Z")
    provider = setup_provider_org()
    fixture = setup_two_attribute_completeness_property(provider)
    provisional = get_property(fixture["property_id"], provider["creator_headers"])
    assert provisional["completeness_pct"] == 79.90
    final = validate_success(
        api.finalize_property(fixture["property_id"], provider["creator_headers"]), 200
    )
    assert final["completeness_pct"] == 49.90
    assert round(provisional["completeness_pct"] - final["completeness_pct"], 2) == 30.00


def test_completeness_of_a_single_verified_claim_is_one_hundred(api):
    """PRD §3.4: "A `VERIFIED` attribute whose named source document exists on the property and was obtained within the freshness window — that is, at most 180 days, the `SOURCE_FRESHNESS_DAYS` constant, before the logical clock — contributes 1.0, the `WEIGHT_VERIFIED_SOURCED` weight."

    Design: Corner/calculations/completion_and_verification_round_half_up_at_two_decimals
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(
        prop["id"], provider["creator_headers"], source_type="DEED",
        source_name="Dallas County Clerk", contact_method="RECORDS_REQUEST",
        obtained_at="2026-08-25T00:00:00Z",
    )
    att = create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="tenant_name"
    )
    propose_and_verify(
        prop["id"], att["id"], "Harborline Logistics Inc",
        provider["creator_headers"], provider["verifier_headers"],
    )
    snapshot = get_property(prop["id"], provider["creator_headers"])
    assert snapshot["completeness_pct"] == 100.0
    assert snapshot["attribute_verified_count"] == 1


def test_completeness_halves_when_an_unevidenced_claim_joins_the_set(api):
    """PRD §3.4: "The base score is one hundred multiplied by the numerator sum, divided by the count of attributes in the scoring set."

    PRD §3.4: "Every attribute in any other state contributes 0.0, the `WEIGHT_UNVERIFIED` weight."

    Design: Corner/calculations/completion_and_verification_round_half_up_at_two_decimals
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(
        prop["id"], provider["creator_headers"], source_type="DEED",
        source_name="Dallas County Clerk", contact_method="RECORDS_REQUEST",
        obtained_at="2026-08-25T00:00:00Z",
    )
    first = create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="tenant_name"
    )
    propose_and_verify(
        prop["id"], first["id"], "Harborline Logistics Inc",
        provider["creator_headers"], provider["verifier_headers"],
    )
    assert get_property(prop["id"], provider["creator_headers"])["completeness_pct"] == 100.0

    create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="occupancy_pct"
    )
    snapshot = get_property(prop["id"], provider["creator_headers"])
    assert snapshot["attribute_total_count"] == 2
    assert snapshot["completeness_pct"] == 50.0


def test_attribute_rejection_returns_the_claim_to_none(api):
    """PRD §3.2: "A rejection requires only that the attribute be `PENDING` — a rejection of anything else is refused with `ERR_INVALID_STATE` (HTTP 409) — and it accepts an optional `reason` recording why the candidate was turned down, clears `proposed_value` back to null while setting `proposed_status` to `NONE`."

    Design: Difficulty/non_linear_state_machine/property_attribute_cycle_none_pending_verified_verified_none
    """
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(prop["id"], provider["creator_headers"])
    att = create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="tenant_name"
    )
    pending = validate_success(
        propose_value(prop["id"], att["id"], "Harborline Logistics Inc",
                      provider["creator_headers"]), 200
    )
    assert pending["proposed_status"] == "PENDING"

    rejected = validate_success(
        api.reject_attribute(att["id"], provider["verifier_headers"], {"reason": "unverified"}),
        200,
    )
    assert rejected["proposed_status"] == "NONE"
    assert rejected["proposed_value"] is None


def test_attribute_cycle_reopens_a_verified_claim(api):
    """PRD §3.2: "A fresh proposal submitted against an attribute already in `VERIFIED` sets `proposed_status` back to `NONE` and clears `proposed_value` to null, and the parent property's `attribute_verified_count` and `completeness_pct` are recomputed under the `PROVISIONAL` variant so that the championed value no longer counts as verified while a new candidate is in flight."

    Design: Difficulty/non_linear_state_machine/property_attribute_cycle_none_pending_verified_verified_none
    """
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(prop["id"], provider["creator_headers"])
    att = create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="tenant_name"
    )
    verified = propose_and_verify(
        prop["id"], att["id"], "Harborline Logistics Inc",
        provider["creator_headers"], provider["verifier_headers"],
    )
    assert verified["proposed_status"] == "VERIFIED"
    assert verified["revision_index"] == 2

    reopened = validate_success(
        propose_value(prop["id"], att["id"], "Harborline Freight LLC",
                      provider["creator_headers"]), 200
    )
    assert reopened["proposed_status"] != "VERIFIED"
    assert reopened["value"] == "Harborline Logistics Inc"


def test_verification_twice_on_a_verified_attribute_returns_invalid_state(api):
    """PRD §3.2: "Moving an attribute from `PENDING` to `VERIFIED` requires that it be `PENDING` — anything else is refused with `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/verification_twice_on_a_verified_attribute_returns_invalid_state
    """
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(prop["id"], provider["creator_headers"])
    att = create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="tenant_name"
    )
    verified = propose_and_verify(
        prop["id"], att["id"], "Harborline Logistics Inc",
        provider["creator_headers"], provider["verifier_headers"],
    )
    resp = api.verify_attribute(att["id"], provider["verifier_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    unchanged = get_success_data(api.get_attribute(att["id"], provider["creator_headers"]))
    assert unchanged["revision_index"] == verified["revision_index"]
    assert unchanged["value"] == "Harborline Logistics Inc"


def test_third_party_attribute_without_approval_returns_third_party_unlicensed(api):
    """PRD §2.10: "when the claim derives from a `THIRD_PARTY_LICENSED` source, `from_third_party` must be true and `third_party_approved` must also be true, or the request is refused with `ERR_THIRD_PARTY_UNLICENSED` (HTTP 409)."

    PRD §2.10: "Both flags default to false, so a caller that says nothing about provenance gets a first-party claim and pays no licensing gate."

    Design: Corner/validations/third_party_attribute_without_approval_returns_third_party_unlicensed
    """
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(
        prop["id"], provider["creator_headers"], source_type="THIRD_PARTY_FEED",
        source_name="Aggregated regional feed", contact_method="FEED_IMPORT",
        obtained_at="2026-08-20T00:00:00Z",
    )
    # The request says nothing about provenance, but the claim derives from a
    # THIRD_PARTY_LICENSED source, so the licensing gate applies and refuses it.
    resp = api.create_attribute(
        prop["id"],
        {"source_document_id": sd["id"], "field_name": "tenant_name", "value": "",
         "attribute_market": "TX-DALLAS"},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_THIRD_PARTY_UNLICENSED)
    assert resp.status_code == 409

    # Saying explicitly that the claim is third-party-derived, without approval,
    # is refused the same way.
    resp2 = api.create_attribute(
        prop["id"],
        {"source_document_id": sd["id"], "field_name": "tenant_name", "value": "",
         "attribute_market": "TX-DALLAS", "from_third_party": True,
         "third_party_approved": False},
        provider["creator_headers"],
    )
    validate_error(resp2, ApiErrorId.ERR_THIRD_PARTY_UNLICENSED)
    assert resp2.status_code == 409


def test_attribute_bound_to_a_foreign_source_document_returns_source_mismatch(api):
    """PRD §2.10: "The named `source_document_id` must belong to the same property as the attribute, or the request is refused with `ERR_ATTRIBUTE_SOURCE_MISMATCH` (HTTP 422)."

    Design: Corner/errors/attribute_bound_to_a_foreign_source_document_returns_source_mismatch
    """
    provider = setup_provider_org()
    one = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    two = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="5000 Maple Ave",
        property_type="OFFICE", rentable_sqft=90_000, classification="CLASS_B",
    )
    foreign = attach_source_document(one["id"], provider["creator_headers"])
    resp = api.create_attribute(
        two["id"],
        {"source_document_id": foreign["id"], "field_name": "tenant_name", "value": "",
         "attribute_market": "TX-DALLAS"},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ATTRIBUTE_SOURCE_MISMATCH)
    assert resp.status_code == 422


def test_seat_user_cannot_propose_a_property_attribute_returns_unauthorized(api):
    """PRD §2.1: "A request whose acting role is not permitted for the operation being attempted is rejected with `ERR_UNAUTHORIZED` and carries HTTP status 403."

    Design: Corner/rbac/seat_user_cannot_propose_a_property_attribute_returns_unauthorized
    """
    provider = setup_provider_org()
    subscriber = setup_subscriber_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(prop["id"], provider["creator_headers"])
    att = create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="tenant_name"
    )
    resp = propose_value(prop["id"], att["id"], "Leaked Tenant Name",
                         subscriber["seat_user_headers"][0])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    unchanged = get_success_data(api.get_attribute(att["id"], provider["creator_headers"]))
    assert unchanged["proposed_status"] == "NONE"


def test_all_three_attribute_state_transitions_produce_provisional_recomputation(api):
    """PRD §3.2: "Both `attribute_verified_count` and `completeness_pct` are then recomputed under the `PROVISIONAL` variant."

    PRD §3.2: "The parent property's `attribute_verified_count` and `completeness_pct` are recomputed under the `PROVISIONAL` variant, exactly as on the verification branch."

    Design: Difficulty/dual_variant_calc/completeness_provisional_vs_final_on_property
    """
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    sd = attach_source_document(
        prop["id"], provider["creator_headers"], obtained_at="2026-08-25T00:00:00Z"
    )
    att = create_attribute_claim(
        prop["id"], sd["id"], provider["creator_headers"], field_name="tenant_name"
    )
    after_create = get_property(prop["id"], provider["creator_headers"])
    assert after_create["attribute_total_count"] == 1
    assert after_create["attribute_verified_count"] == 0
    assert after_create["completeness_pct"] == 0.0

    propose_value(prop["id"], att["id"], "Harborline Logistics Inc",
                  provider["creator_headers"])
    after_proposal = get_property(prop["id"], provider["creator_headers"])
    assert after_proposal["completeness_pct"] == 0.0

    # The candidate is already PENDING, so the verification branch closes the
    # cycle directly; a second proposal against a PENDING attribute would be
    # refused with ERR_INVALID_STATE by PRD 3.2.
    validate_success(verify(att["id"], provider["verifier_headers"]), 200)
    after_verify = get_property(prop["id"], provider["creator_headers"])
    assert after_verify["attribute_verified_count"] == 1
    assert after_verify["completeness_pct"] == 100.0


def test_attribute_recompute_advances_the_parent_property_version(api):
    """PRD §3.4: "Every recomputation of those counters, of `land_posture`, or of `completeness_pct` is a mutation that refreshes the property's `updated_at` and advances its `version`, which is why the optimistic-concurrency guard of §2.13 remains meaningful across a busy research session."

    Design: Corner/calculations/completion_and_verification_round_half_up_at_two_decimals
    """
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    start_version = prop["version"]
    sd = attach_source_document(prop["id"], provider["creator_headers"])
    create_attribute_claim(prop["id"], sd["id"], provider["creator_headers"],
                           field_name="tenant_name")
    after = get_property(prop["id"], provider["creator_headers"])
    assert after["version"] > start_version
    assert after["updated_at"] >= prop["updated_at"]

def test_contract_lapse_scan_fires_grace_then_lapsed_in_one_cycle(api):
    """PRD §3.11: "A contract that is still `GRACE` when the logical clock has reached or passed its `term_end` is then driven onward to `LAPSED`, its `renewal_decision` is set to `FAILED`, and every seat on it is revoked by setting `access_revoked` to true."

    Design: Corner/state_machines/contract_lapse_scan_fires_grace_then_lapsed_in_one_cycle
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org()
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, seat_count=5,
        term_start="2025-09-10T00:00:00Z", term_end="2026-09-10T00:00:00Z",
        renewal_notice_days=31, last_usage_cycle="2026-08-15T00:00:00Z",
    )
    set_logical_clock("2026-09-15T00:00:00Z")
    cycle = validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    contract = get_success_data(
        api.get_contract(active["contract"]["id"], active["admin_headers"])
    )
    seat = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    org = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert contract["status"] == "LAPSED"
    assert contract["renewal_decision"] == "FAILED"
    assert seat["access_revoked"] is True
    assert seat["overage_fee_cents"] == 0
    assert org["active_contract_count"] == 0
    assert cycle["lapsed_contracts"] >= 1


def test_organization_create_ignores_a_client_supplied_status(api):
    """PRD §2.8: "A newly created organization is `ACTIVE` and both of its aggregate counters begin at zero."

    PRD §2.8: "The `status` of an organization is `ACTIVE` or `SUSPENDED`, and `SUSPENDED` is a gate rather than a label: a suspended organization's seats can no longer record usage."

    Design: Corner/entities/organization_create_with_a_client_supplied_status_extra_field_input_ignored
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    created = validate_success(
        api.create_organization(
            {"legal_name": "Rogue Status LLC", "org_type": "SUBSCRIBER",
             "home_market": "TX-DALLAS", "status": "SUSPENDED"},
            {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"},
        ),
        201,
    )
    assert created["status"] == "ACTIVE"
    assert created["authorized_market_count"] == 0
    assert created["active_contract_count"] == 0
