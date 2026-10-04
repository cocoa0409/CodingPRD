"""Enforcement cascades, sale subordination and listing interval occupancy."""

from test_helpers import (
    ApiErrorId,
    create_property,
    create_sale_transaction,
    ensure_researching,
    get_property,
    get_success_data,
    open_enforcement_case,
    set_logical_clock,
    setup_active_contract,
    setup_listing_licensed_brokerage,
    setup_provider_org,
    setup_subscriber_org,
    validate_error,
    validate_success,
)


def test_litigation_escalation_cascades_from_case_to_organization_to_contract(api):
    """PRD §3.7: "A successful escalation cascades in three directions. The case itself moves to `ESCALATED` and records `escalated_at` as the logical clock."

    PRD §3.7: "And the respondent `Organization` is suspended: its `status` becomes `SUSPENDED`, which gates every seat of that organization from recording usage, while every one of its licensing contracts that currently holds `ACTIVE` or `GRACE` is driven to `TERMINATED` with every seat on those contracts revoked by setting `access_revoked` to true."

    Design: Difficulty/transitive_cascade/litigation_escalation_cascade_to_contract_seat_and_billed_fee
    """
    set_logical_clock("2026-05-15T00:00:00Z")
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    provider = setup_provider_org(
        org_name="Harborline Data Services", service_tier="ENTERPRISE", with_officer=True,
    )
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, seat_count=3, index_tier="TIER_1",
        term_start="2026-05-01T00:00:00Z", term_end="2027-05-01T00:00:00Z",
        audit_intensity="ENHANCED", last_usage_cycle="2026-05-01T00:00:00Z",
    )
    case = open_enforcement_case(
        subscriber["org"]["id"], active["contract"]["id"], provider["officer_headers"],
        finding_cents=60_000_000, fee_rate_pct=1.25,
    )
    assert case["penalty_cents"] == 75_000_000
    assert case["status"] == "OPEN"

    escalated = validate_success(
        api.escalate_case(case["id"], provider["officer_headers"]), 200
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalated_at"] == "2026-05-15T00:00:00Z"

    org = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert org["status"] == "SUSPENDED"

    contract = get_success_data(
        api.get_contract(active["contract"]["id"], active["admin_headers"])
    )
    assert contract["status"] == "TERMINATED"
    seat = get_success_data(api.get_seat(active["seat"]["id"], active["admin_headers"]))
    assert seat["access_revoked"] is True


def test_litigation_escalation_succeeds_at_exactly_the_penalty_floor(api):
    """PRD §3.7: "The same computation decides whether the case is eligible for escalation: the case is escalatable when its `penalty_cents` is at least 75,000,000 cents, the `LITIGATION_PENALTY_THRESHOLD_CENTS` constant, and that floor is inclusive — a penalty exactly equal to the threshold is escalatable."

    Design: Difficulty/transitive_cascade/litigation_escalation_cascade_to_contract_seat_and_billed_fee
    """
    set_logical_clock("2026-05-15T00:00:00Z")
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    provider = setup_provider_org(
        org_name="Harborline Data Services", service_tier="ENTERPRISE", with_officer=True,
    )
    active = setup_active_contract(
        subscriber, annual_fee_cents=100_000, seat_count=3, index_tier="TIER_1",
        term_start="2026-05-01T00:00:00Z", term_end="2027-05-01T00:00:00Z",
        audit_intensity="ENHANCED", last_usage_cycle="2026-05-01T00:00:00Z",
    )
    case = open_enforcement_case(
        subscriber["org"]["id"], active["contract"]["id"], provider["officer_headers"],
        finding_cents=60_000_000, fee_rate_pct=1.25,
    )
    escalate_resp = api.escalate_case(case["id"], provider["officer_headers"])
    validate_success(escalate_resp, 200)

    litigation = get_success_data(
        api.list_escalations(case["id"], provider["officer_headers"])
    )
    assert isinstance(litigation, list) and len(litigation) >= 1
    assert litigation[0]["case_type"] == "LITIGATION"
    assert litigation[0]["escalated_from_case_id"] == case["id"]

    # A seat of the suspended organization can no longer record usage.
    blocked = api.create_usage_event(
        active["seat"]["id"],
        {"market": "TX-DALLAS", "event_type": "API_QUERY", "record_count": 4,
         "distinguishing_ip": "203.0.113.7", "occurred_at": "2026-05-16T09:00:00Z"},
        active["occupant_headers"],
    )
    assert blocked.status_code >= 400


def test_source_decay_cascade_flips_staleness_then_completeness_then_posture(api):
    """PRD §3.11: "Property staleness is re-aged first: `stale_source_count` is recomputed for every property by counting the sources whose `obtained_at` is strictly more than 180 days before the current logical clock, and for every property whose stale-source count changed, `completeness_pct` and `land_posture` are recomputed under the `PROVISIONAL` variant."

    PRD §3.4: "It is `OPEN` when no unverified attribute burden and no stale-source burden is present, `RESTRICTED` when the property has been placed under a market escalation while it was still `DRAFT` or `RESEARCHING`"

    Design: Difficulty/transitive_cascade/source_decay_cascade_to_completeness_and_land_posture
    """
    set_logical_clock("2026-02-25T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    pid = prop["id"]
    ch, vh = provider["creator_headers"], provider["verifier_headers"]
    from test_helpers import attach_source_document, create_attribute_claim, propose_and_verify

    sd = attach_source_document(
        pid, ch, source_type="DEED", source_name="Dallas County Clerk",
        contact_method="RECORDS_REQUEST", obtained_at="2025-09-10T00:00:00Z",
    )
    first = create_attribute_claim(pid, sd["id"], ch, field_name="tenant_name")
    propose_and_verify(pid, first["id"], "Harborline Logistics Inc", ch, vh)
    second = create_attribute_claim(pid, sd["id"], ch, field_name="occupancy_pct")
    propose_and_verify(pid, second["id"], "92", ch, vh)
    before = validate_success(api.finalize_property(pid, ch), 200)
    assert before["stale_source_count"] == 0
    assert before["completeness_pct"] == 100.0

    set_logical_clock("2026-03-10T00:00:00Z")
    validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    after = get_property(pid, ch)
    assert after["stale_source_count"] == 1
    assert after["land_posture"] == "RESTRICTED"


def test_freshness_boundary_is_strict_at_exactly_one_hundred_eighty_days(api):
    """PRD §2.9: "Freshness is a strict inequality against the logical clock. A source obtained exactly 180 days before the clock still counts as fresh; only a source obtained strictly more than 180 days before the clock is stale."

    Design: Difficulty/transitive_cascade/source_decay_cascade_to_completeness_and_land_posture
    """
    set_logical_clock("2026-02-25T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    from test_helpers import attach_source_document

    # 2026-02-25 minus 180 days is exactly 2025-08-29.
    attach_source_document(
        prop["id"], provider["creator_headers"], source_type="DEED",
        source_name="Dallas County Clerk", contact_method="RECORDS_REQUEST",
        obtained_at="2025-08-29T00:00:00Z",
    )
    at_boundary = get_property(prop["id"], provider["creator_headers"])
    assert at_boundary["stale_source_count"] == 0

    set_logical_clock("2026-02-26T00:00:00Z")
    validate_success(
        api.run_research_cycle({"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}), 200
    )
    past_boundary = get_property(prop["id"], provider["creator_headers"])
    assert past_boundary["stale_source_count"] == 1


def test_restricted_posture_refuses_a_new_source_document(api):
    """PRD §3.7: "Every property whose `market` lies in the named array and whose `research_status` is `DRAFT` or `RESEARCHING` has its `land_posture` set to `RESTRICTED`, which immediately closes its evidence ledger to new source documents and blocks further attribute proposals."

    PRD §3.3: "Attaching evidence to a `RESTRICTED` property is refused with `ERR_PROPERTY_RESTRICTED` (HTTP 409)"

    Design: Difficulty/transitive_cascade/source_decay_cascade_to_completeness_and_land_posture
    """
    set_logical_clock("2026-06-01T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    prop = create_property(provider["creator_headers"])
    get_success_data(api.start_research(prop["id"], provider["creator_headers"]))
    validate_success(
        api.report_market_escalations(
            {"markets": ["TX-DALLAS"], "reason_code": "SOURCE_INTEGRITY_REVIEW"},
            provider["officer_headers"],
        ),
        200,
    )
    assert get_property(prop["id"], provider["creator_headers"])["land_posture"] == "RESTRICTED"
    resp = api.create_source_document(
        prop["id"],
        {"source_type": "DEED", "source_name": "Dallas County Clerk",
         "contact_method": "RECORDS_REQUEST", "obtained_at": "2026-05-01T00:00:00Z"},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_RESTRICTED)
    assert resp.status_code == 409


def test_subordination_past_its_deadline_is_refused(api):
    """PRD §3.7: "The logical clock must be strictly before the transaction's `subordination_deadline`, or the request is refused with `ERR_SUBORDINATION_DEADLINE_PASSED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/licensed_market_occupancy_share_caps_a_second_contract
    """
    set_logical_clock("2026-05-01T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    prop = create_property(provider["creator_headers"])
    ensure_researching(prop["id"], provider["creator_headers"])
    # close_date + 10 days lands 2026-04-25, which the clock at 2026-05-01 has passed.
    tx = create_sale_transaction(
        prop["id"], provider["creator_headers"], close_date="2026-04-15T00:00:00Z",
        gross_sale_price_cents=5_000_000,
    )
    assert tx["subordination_deadline"] == "2026-04-25T00:00:00Z"
    active = setup_active_contract(
        subscriber, annual_fee_cents=400_000, product="GLOBAL_ALL",
        licensed_markets=["TX-DALLAS", "TX-HOUSTON"],
    )
    case = open_enforcement_case(
        subscriber["org"]["id"], active["contract"]["id"], provider["officer_headers"],
        finding_cents=20_000_000, fee_rate_pct=1.25,
    )
    resp = api.subordinate_transaction(
        tx["id"],
        {"subordinating_case_id": case["id"],
         "expected_transaction_version": get_success_data(
             api.get_sale_transaction(tx["id"], provider["officer_headers"])
         )["version"]},
        provider["officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SUBORDINATION_DEADLINE_PASSED)
    assert resp.status_code == 409


def test_subordination_deadline_instant_is_inclusive(api):
    """PRD §3.7: "The logical clock must be strictly before the transaction's `subordination_deadline`, or the request is refused with `ERR_SUBORDINATION_DEADLINE_PASSED` (HTTP 409)."

    PRD §3.3: "On creation the server derives `subordination_deadline` as exactly ten days after the `close_date`"

    Design: Difficulty/resource_temporal_overlap/licensed_market_occupancy_share_caps_a_second_contract
    """
    set_logical_clock("2026-04-25T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    prop = create_property(provider["creator_headers"])
    ensure_researching(prop["id"], provider["creator_headers"])
    tx = create_sale_transaction(
        prop["id"], provider["creator_headers"], close_date="2026-04-15T00:00:00Z",
        gross_sale_price_cents=5_000_000,
    )
    assert tx["subordination_deadline"] == "2026-04-25T00:00:00Z"
    active = setup_active_contract(subscriber, annual_fee_cents=400_000, product="GLOBAL_ALL",
                                   licensed_markets=["TX-DALLAS", "TX-HOUSTON"])
    case = open_enforcement_case(
        subscriber["org"]["id"], active["contract"]["id"], provider["officer_headers"],
        finding_cents=20_000_000, fee_rate_pct=1.25,
    )
    resp = api.subordinate_transaction(
        tx["id"],
        {"subordinating_case_id": case["id"],
         "expected_transaction_version": get_success_data(
             api.get_sale_transaction(tx["id"], provider["officer_headers"])
         )["version"]},
        provider["officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SUBORDINATION_DEADLINE_PASSED)
    assert resp.status_code == 409


def test_second_listing_publication_collides_with_the_live_availability_interval(api):
    """PRD §3.8: "No other `PUBLISHED` listing of the same property may hold an availability interval overlapping the interval from `published_at` to `expires_at`, or the request is refused with `ERR_LISTING_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/listing_availability_intervals_collide_on_the_same_property
    """
    set_logical_clock("2026-06-01T00:00:00Z")
    brokerage = setup_listing_licensed_brokerage(markets=["TX-DALLAS"])
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    from test_helpers import create_listing

    first = create_listing(
        prop["id"], brokerage["org"]["id"], brokerage["publisher_headers"],
        monthly_rent_psf=34.0, available_sqft=42_000, duration_days=90,
    )
    published = validate_success(
        api.publish_listing(first["id"], brokerage["publisher_headers"]), 200
    )
    assert published["status"] == "PUBLISHED"
    assert published["published_at"] == "2026-06-01T00:00:00Z"
    assert published["expires_at"] == "2026-08-30T00:00:00Z"

    second = create_listing(
        prop["id"], brokerage["org"]["id"], brokerage["publisher_headers"],
        monthly_rent_psf=36.5, available_sqft=18_000, duration_days=92,
    )
    resp = api.publish_listing(second["id"], brokerage["publisher_headers"])
    validate_error(resp, ApiErrorId.ERR_LISTING_OVERLAP)
    assert resp.status_code == 409
    assert get_success_data(
        api.get_listing(second["id"], brokerage["publisher_headers"])
    )["status"] == "DRAFT"


def test_withdrawal_releases_the_interval_for_a_later_publication(api):
    """PRD §3.8: "Withdrawal releases the property's availability interval so a later publication can claim it: a `BrokerPublisher` moving a listing from `PUBLISHED` to `WITHDRAWN` requires only that the listing currently hold `PUBLISHED`, or the request is refused with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/listing_availability_intervals_collide_on_the_same_property
    """
    set_logical_clock("2026-06-01T00:00:00Z")
    brokerage = setup_listing_licensed_brokerage(markets=["TX-DALLAS"])
    provider = setup_provider_org()
    prop = create_property(provider["creator_headers"])
    from test_helpers import create_listing

    first = create_listing(
        prop["id"], brokerage["org"]["id"], brokerage["publisher_headers"],
        monthly_rent_psf=34.0, available_sqft=42_000, duration_days=90,
    )
    validate_success(api.publish_listing(first["id"], brokerage["publisher_headers"]), 200)
    second = create_listing(
        prop["id"], brokerage["org"]["id"], brokerage["publisher_headers"],
        monthly_rent_psf=36.5, available_sqft=18_000, duration_days=92,
    )
    validate_error(
        api.publish_listing(second["id"], brokerage["publisher_headers"]),
        ApiErrorId.ERR_LISTING_OVERLAP,
    )
    withdrawn = validate_success(
        api.withdraw_listing(first["id"], brokerage["publisher_headers"]), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"
    republished = validate_success(
        api.publish_listing(second["id"], brokerage["publisher_headers"]), 200
    )
    assert republished["status"] == "PUBLISHED"


def test_research_analyst_cannot_escalate_an_enforcement_case_returns_unauthorized(api):
    """PRD §2.1: "A request whose acting role is not permitted for the operation being attempted is rejected with `ERR_UNAUTHORIZED` and carries HTTP status 403."

    Design: Corner/rbac/research_analyst_cannot_escalate_an_enforcement_case_returns_unauthorized
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    subscriber = setup_subscriber_org(
        org_name="Cedar Point Capital Partners", service_tier="MID_MARKET",
    )
    provider = setup_provider_org(
        org_name="Harborline Data Services", service_tier="ENTERPRISE", with_officer=True,
    )
    active = setup_active_contract(subscriber, annual_fee_cents=200_000, seat_count=3,
                                   audit_intensity="ENHANCED")
    case = open_enforcement_case(
        subscriber["org"]["id"], active["contract"]["id"], provider["officer_headers"],
        finding_cents=60_000_000, fee_rate_pct=1.25,
    )
    assert case["penalty_cents"] == 75_000_000
    resp = api.escalate_case(case["id"], provider["creator_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    assert resp.status_code == 403
    unchanged = get_success_data(api.get_enforcement_case(case["id"], provider["officer_headers"]))
    assert unchanged["status"] == "OPEN"
    org = get_success_data(api.get_organization(
        subscriber["org"]["id"], {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"}
    ))
    assert org["status"] == "ACTIVE"