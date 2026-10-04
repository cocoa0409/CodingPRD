"""Endpoint corner rules: OCC on dues billing, office close gating, the license
cure window, and the compliance checkpoint listing expiry."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, create_dues_period, bill_dues_period, set_clock,
    activate_policy_revision, activate_listing, change_status,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_occ_stale_version_on_dues_bill(api):
    """PRD §2.6: "Billing a dues period requires `expected_dues_period_version`
    matching the period's current `version`. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412); billing mints one invoice per `ACTIVE`
    member and a stale view risks double-billing after a corrective period
    edit."

    Design: Corner/endpoints/occ_stale_version_on_dues_bill
    """
    assoc = create_association(association_code="EP1")
    period = create_dues_period(assoc["id"], year=2026,
                                period_start_date="2026-09-01T00:00:00Z",
                                due_date="2026-09-30T00:00:00Z",
                                grace_end_date="2026-10-10T00:00:00Z",
                                amount_cents=100000)
    bill_dues_period(assoc["id"], period)
    # Second bill attempt with the pre-bill version: stale.
    resp = api.bill_dues_period(assoc["id"], period["id"], period["version"], STAFF)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_office_close_blocked_by_open_listings(api):
    """PRD §3.1: "An office may be closed by staff only when none of its
    listings remain in `DRAFT`, `ACTIVE`, or `PENDING`; attempting closure with
    open listings is rejected with `ERR_OFFICE_HAS_OPEN_LISTINGS`; a successful
    closure transitions the office to `CLOSED`, which is terminal."

    Design: Corner/endpoints/office_close_blocked_by_open_listings
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="EP2")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-EP2")
    activate_listing(assoc["id"], office["id"], listing)
    resp = api.close_office(assoc["id"], office["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_OFFICE_HAS_OPEN_LISTINGS)
    change_status(assoc["id"], office["id"], listing, "CANCELLED",
                  "2026-09-02T01:00:00Z")
    closed = validate_success(api.close_office(assoc["id"], office["id"], STAFF))
    assert closed["status"] == "CLOSED"


def test_license_cure_window_30d_boundary(api):
    """PRD §3.9: "A suspended license may be cured: the cure must be submitted
    within 30 days of `last_audit_at` — later is rejected with
    `ERR_CURE_WINDOW_CLOSED` — and the same request logically re-runs the
    compliance check, which must now pass."

    Design: Corner/endpoints/license_cure_window_30d_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="EP3")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="FEED_ABUSE", fine_amount_cents=25000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-EP3")
    activate_listing(assoc["id"], office["id"], listing)
    lic = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "CureP", "scope": "IDX", "display_ruleset_version": 1,
         "listing_field_allowlist": ["property_address"]}, STAFF))
    validate_success(api.activate_data_license(assoc["id"], lic["id"], STAFF))
    # Second revision bumps the ruleset version to 2 -> license drifts.
    assoc_now = get_success_data(api.get_association(assoc["id"], STAFF))
    activate_policy_revision(assoc["id"], assoc_now["version"], revision_code="R2",
                             effective_at="2026-09-09T00:00:00Z",
                             activate_now="2026-09-09T00:00:00Z")
    set_clock("2026-09-10T00:00:00Z")
    audit = get_success_data(api.audit_feed(assoc["id"], lic["id"], STAFF))
    assert audit["violation_found"] is True
    lic_now = get_success_data(api.get_data_license(assoc["id"], lic["id"], STAFF))
    assert lic_now["status"] == "SUSPENDED"
    # 31 days after the audit: window closed.
    set_clock("2026-10-11T00:00:00Z")
    resp = api.cure_data_license(assoc["id"], lic["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_CLOSED)


def test_run_compliance_checkpoint_expires_stale_active_listing(api):
    """PRD §3.10: "The checkpoint expires every listing that has been `ACTIVE`
    for more than 365 days — each such listing transitions to `EXPIRED` with a
    status-change record whose `business_effective_at` is the checkpoint
    instant — and re-derives the license-compliance posture of the association.
    The response reports the `expired_listing_count`."

    Design: Corner/endpoints/run_compliance_checkpoint_expires_stale_active_listing
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="EP4")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-EP4")
    set_clock("2026-09-02T00:00:00Z")
    activate_listing(assoc["id"], office["id"], listing)
    # 366 days ACTIVE (> 365) at the checkpoint instant.
    set_clock("2027-09-03T00:00:00Z")
    result = validate_success(api.run_compliance_checkpoint(assoc["id"], STAFF))
    assert result["expired_listing_count"] == 1
    listing_now = get_success_data(
        api.get_listing(assoc["id"], office["id"], listing["id"], STAFF))
    assert listing_now["status"] == "EXPIRED"
    changes = get_success_data(api.list_listing_status_changes(
        assoc["id"], office["id"], listing["id"], STAFF))
    expiry = [c for c in changes if c["to_status"] == "EXPIRED"]
    assert len(expiry) == 1
    assert expiry[0]["from_status"] == "ACTIVE"
    assert expiry[0]["business_effective_at"] == "2027-09-03T00:00:00.000Z"
