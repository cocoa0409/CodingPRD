"""Entity-level rules: creation defaults, required fields, computed-field
rejection, immutability, scope/existence, cross-association references, enums,
and pagination envelope."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock,
    create_association_payload, create_member_payload, create_office_payload,
    create_listing_payload, create_citation_payload, create_fine_schedule_payload,
    make_member_headers, TEST_USERS,
    assert_association, assert_consolidation_event,
    api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_association_create_persists_fields_and_defaults(api):
    """PRD §3.1: "An `AssociationStaff` operator charters an association by supplying its globally unique `association_code` (for example `NOR`), its legal `name`, the annual `membership_dues_cents`, the two flat late-fee tiers `late_fee_tier1_cents` and `late_fee_tier2_cents`, and optionally `sanction_credit_cap_cents` — the ceiling on any member's sanction-credit balance, which defaults to 200000 cents when omitted. A new association begins with `consolidation_state` `ACTIVE` and `consolidated_into_id` null."

    Design: Corner/entities/association_create_persists_fields_and_defaults
    """
    payload = create_association_payload(association_code="E1", name="Ent Assoc",
                                         membership_dues_cents=100000)
    payload.pop("sanction_credit_cap_cents")
    resp = api.create_association(payload, STAFF)
    data = validate_success(resp, expected_status=201)
    assert_association(data)
    assert data["consolidation_state"] == "ACTIVE"
    assert data["consolidated_into_id"] is None
    assert data["version"] == 1
    assert data["sanction_credit_cap_cents"] == 200000
    # Re-read confirms persistence
    fetched = validate_success(api.get_association(data["id"], STAFF))
    assert fetched["sanction_credit_cap_cents"] == 200000
    assert fetched["consolidation_state"] == "ACTIVE"


def test_member_create_missing_required_member_nr_returns_invalid_request(api):
    """PRD §3.1: "Members are registered into an association by staff with an
    association-scoped `member_nr` (unique within the association; a collision
    is rejected with `ERR_DUPLICATE_RESOURCE`) and the member's `full_name`."
    PRD §2.7: "A malformed payload, missing required field, invalid enum value,
    or out-of-range value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/member_create_missing_required_member_nr_returns_invalid_request
    """
    assoc = create_association(association_code="E2")
    resp = api.create_member(assoc["id"], {"full_name": "No Number"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_consolidation_event_immutable_no_version_field(api):
    """PRD §2.4: "`ConsolidationEvent` is the exception: it carries only `id`
    and `created_at`; both `updated_at` and `version` are absent from it."
    PRD §3.10: "Scheduling transitions the event to `SCHEDULED` and moves the
    absorbed association's `consolidation_state` from `ACTIVE` to `MERGING`".

    Design: Corner/entities/consolidation_event_immutable_no_version_field
    """
    survivor = create_association(association_code="E4S")
    absorbed = create_association(association_code="E4A", membership_dues_cents=90000,
                                  late_fee_tier1_cents=4000, late_fee_tier2_cents=12000)
    resp = api.create_consolidation(
        survivor["id"],
        {"absorbed_association_id": absorbed["id"],
         "effective_at": "2027-01-01T00:00:00Z"},
        STAFF)
    event = validate_success(resp, expected_status=201)
    assert_consolidation_event(event)
    assert event["status"] == "SCHEDULED"


def test_listing_get_not_found_wrong_office_scope(api):
    """PRD §2.7: "A resource that exists but is nested under the wrong parent
    scope is rejected with `ERR_NOT_FOUND` (HTTP 404), not `ERR_FORBIDDEN`."

    Design: Corner/entities/listing_get_not_found_wrong_office_scope
    """
    assoc = create_association(association_code="E5")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    o1 = create_office(assoc["id"], broker["id"], office_code="O1")
    o2 = create_office(assoc["id"], broker["id"], office_code="O2")
    listing = create_listing(assoc["id"], o1["id"], broker["id"], mls_number="MLS-E5")
    resp = api.get_listing(assoc["id"], o2["id"], listing["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_cross_association_member_fk_rejected_on_citation(api):
    """PRD §3.5: "The cited member must belong to the citing association, else
    `ERR_CROSS_ASSOCIATION_REFERENCE`."

    Design: Corner/entities/cross_association_member_fk_rejected_on_citation
    """
    assoc_a = create_association(association_code="E6A")
    assoc_b = create_association(association_code="E6B", membership_dues_cents=90000,
                                 late_fee_tier1_cents=4000, late_fee_tier2_cents=12000)
    member_b = create_member(assoc_b["id"], member_nr="MB2", full_name="Bee Member")
    create_fine_schedule(assoc_a["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    resp = api.create_citation(
        assoc_a["id"],
        create_citation_payload(member_b["id"], rule_code="INACCURACY"),
        STAFF)
    validate_error(resp, ApiErrorId.ERR_CROSS_ASSOCIATION_REFERENCE)


def test_listing_enum_status_rejects_invalid_value(api):
    """PRD §3.4: "The member responsible requests a status change by naming the
    target `to_status` and supplying `business_effective_at`".
    PRD §2.7: "A malformed payload, missing required field, invalid enum value,
    or out-of-range value is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/listing_enum_status_rejects_invalid_value
    """
    assoc = create_association(association_code="E7")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    listing = create_listing(assoc["id"], office["id"], broker["id"], mls_number="MLS-E7")
    resp = api.change_listing_status(
        assoc["id"], office["id"], listing["id"],
        {"to_status": "ARCHIVED", "business_effective_at": "2026-09-01T00:00:00Z"},
        make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_members_list_pagination_envelope(api):
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset`
    defaults to 0. Results are sorted by `created_at` ascending. The `meta`
    block of a list response carries `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/members_list_pagination_envelope
    """
    assoc = create_association(association_code="E8")
    for i in range(3):
        create_member(assoc["id"], member_nr=f"P{i+1}", full_name=f"Member {i+1}")
    resp = api.list_members(assoc["id"], STAFF, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
