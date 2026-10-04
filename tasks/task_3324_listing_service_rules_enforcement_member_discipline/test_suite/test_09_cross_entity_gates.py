"""Cross-entity state dependencies: listing activation gated on the member's
membership state; arbitration filing gated on the listing being SOLD."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_dues_period, bill_dues_period, set_clock,
    activate_policy_revision, activate_listing, change_status,
    pay_invoice, get_member_invoice,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_listing_activation_gated_by_member_membership_state(api):
    """PRD §3.3: "the listing member must be `ACTIVE` with `mls_access_state`
    `ENABLED`, otherwise the activation is rejected with
    `ERR_MEMBER_SUSPENDED`; the office must be `ACTIVE`".
    PRD §3.1: "when the member named by an office's `broker_member_id`
    transitions from `ACTIVE` to `SUSPENDED`, the office transitions to
    `SUSPENDED` as well".

    Design: Difficulty/cross_entity_state_dependency/listing_activation_gated_by_member_membership_state
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="XS1")
    broker = create_member(assoc["id"], member_nr="MB2", full_name="Broker Two")
    agent = create_member(assoc["id"], member_nr="MA", full_name="Agent")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    listing = create_listing(assoc["id"], office["id"], agent["id"],
                             mls_number="MLS-XS1")
    period = create_dues_period(
        assoc["id"], year=2026, period_start_date="2026-09-01T00:00:00Z",
        due_date="2026-09-10T00:00:00Z", grace_end_date="2026-09-20T00:00:00Z",
        amount_cents=120000)
    set_clock("2026-09-05T00:00:00Z")
    bill_dues_period(assoc["id"], period)
    # Broker pays; agent stays delinquent.
    broker_invoice = get_member_invoice(assoc["id"], period["id"], broker["id"])
    pay_invoice(assoc["id"], broker_invoice)
    set_clock("2026-09-21T00:00:00Z")
    validate_success(api.reconcile_dues_period(assoc["id"], period["id"], STAFF))

    agent_now = get_success_data(api.get_member(assoc["id"], agent["id"], STAFF))
    assert agent_now["membership_state"] == "SUSPENDED"
    office_now = get_success_data(api.get_office(assoc["id"], office["id"], STAFF))
    assert office_now["status"] == "ACTIVE", \
        "non-broker suspension does NOT suspend the office"

    resp = api.activate_listing(
        assoc["id"], office["id"], listing["id"], make_member_headers(agent["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)
    listing_now = get_success_data(
        api.get_listing(assoc["id"], office["id"], listing["id"], STAFF))
    assert listing_now["status"] == "DRAFT"


def test_listing_status_change_gated_by_member_membership_state(api):
    """PRD §3.4: "The same member-identity and member-standing gates as
    activation apply: the actor must be the `listing_member_id`, and the
    listing member must be `ACTIVE` and `ENABLED` (`ERR_MEMBER_SUSPENDED`
    otherwise)."
    PRD §3.2: "Either way, suspension disables the member's `mls_access_state`
    (it becomes `DISABLED`), blocks every listing of that member in `DRAFT`,
    `ACTIVE`, or `PENDING` from activation and status-change transitions".

    Design: Difficulty/cross_entity_state_dependency/listing_activation_gated_by_member_membership_state
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="XS1B")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-XS1B")
    activate_listing(assoc["id"], office["id"], listing)
    period = create_dues_period(
        assoc["id"], year=2026, period_start_date="2026-09-01T00:00:00Z",
        due_date="2026-09-10T00:00:00Z", grace_end_date="2026-09-20T00:00:00Z",
        amount_cents=120000)
    set_clock("2026-09-05T00:00:00Z")
    bill_dues_period(assoc["id"], period)
    set_clock("2026-09-21T00:00:00Z")
    validate_success(api.reconcile_dues_period(assoc["id"], period["id"], STAFF))
    resp = api.change_listing_status(
        assoc["id"], office["id"], listing["id"],
        {"to_status": "PENDING", "business_effective_at": "2026-09-21T00:00:00Z"},
        make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)


def test_arbitration_filing_gated_by_listing_sold_state(api):
    """PRD §3.7: "The listing must be `SOLD`, and the filing window is 180 days
    from the listing's closing date; a filing after the window is rejected with
    `ERR_ARBITRATION_WINDOW_CLOSED`."
    PRD §2.7: "(6) source-state legality — `ERR_INVALID_STATE`".

    Design: Difficulty/cross_entity_state_dependency/arbitration_filing_gated_by_listing_sold_state
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="XS2")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    ml = create_member(assoc["id"], member_nr="ML", full_name="Lister")
    mr = create_member(assoc["id"], member_nr="MR", full_name="Responder")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], ml["id"],
                             mls_number="MLS-XS2")
    activate_listing(assoc["id"], office["id"], listing)
    resp = api.create_arbitration_case(
        assoc["id"],
        {"respondent_member_id": mr["id"], "listing_id": listing["id"],
         "claim_amount_cents": 500000},
        make_member_headers(ml["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    cases = get_success_data(api.list_arbitration_cases(
        assoc["id"], STAFF, params={"listing_id": listing["id"]}))
    assert cases == []


def test_arbitration_filing_on_sold_listing_succeeds(api):
    """PRD §3.7: "The listing must be `SOLD`, and the filing window is 180 days
    from the listing's closing date". "Filing stamps `filed_at` and transitions
    the case `FILED` → `MEDIATION_OFFERED` automatically."

    Design: Difficulty/cross_entity_state_dependency/arbitration_filing_gated_by_listing_sold_state
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="XS2B")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    ml = create_member(assoc["id"], member_nr="ML", full_name="Lister")
    mr = create_member(assoc["id"], member_nr="MR", full_name="Responder")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], ml["id"],
                             mls_number="MLS-XS2B")
    activate_listing(assoc["id"], office["id"], listing)
    change_status(assoc["id"], office["id"], listing, "PENDING",
                  "2026-09-02T01:00:00Z")
    change_status(assoc["id"], office["id"], listing, "SOLD",
                  "2026-09-02T02:00:00Z")
    resp = api.create_arbitration_case(
        assoc["id"],
        {"respondent_member_id": mr["id"], "listing_id": listing["id"],
         "claim_amount_cents": 500000},
        make_member_headers(ml["id"]))
    case = validate_success(resp, expected_status=201)
    assert case["status"] == "MEDIATION_OFFERED"
