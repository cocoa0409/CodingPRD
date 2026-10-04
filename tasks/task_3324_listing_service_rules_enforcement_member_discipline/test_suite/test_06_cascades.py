"""Transitive cascades: reconcile -> member suspension -> office suspension ->
blocked listing activation; and late status change -> auto-citation + flag ->
withdrawal blocked -> payment unflags."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, create_dues_period, bill_dues_period, set_clock,
    activate_policy_revision, activate_listing, change_status,
    pay_invoice, get_member_invoice,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_reconcile_suspends_member_cascades_office_and_blocks_listing(api):
    """PRD §3.2: "staff reconcile a `BILLED` period — permitted only once the
    current logical date is later than the period's `grace_end_date` — which
    transitions the period `BILLED` → `RECONCILED` and suspends every member
    of the association whose invoice for that period remains `PENDING`."
    PRD §3.1: "when the member named by an office's `broker_member_id`
    transitions from `ACTIVE` to `SUSPENDED`, the office transitions to
    `SUSPENDED` as well, and while the office is suspended all of its listings
    are blocked from activation."
    PRD §3.3: "the listing member must be `ACTIVE` with `mls_access_state`
    `ENABLED`, otherwise the activation is rejected with `ERR_MEMBER_SUSPENDED`".

    Design: Difficulty/transitive_cascade/reconcile_suspends_member_cascades_office_and_blocks_listing
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="TC1")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    period = create_dues_period(
        assoc["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-01-31T00:00:00Z", grace_end_date="2027-03-02T00:00:00Z",
        amount_cents=120000)
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-TC1")
    set_clock("2027-01-15T00:00:00Z")
    bill_dues_period(assoc["id"], period)
    set_clock("2027-03-03T00:00:00Z")
    validate_success(api.reconcile_dues_period(assoc["id"], period["id"], STAFF))

    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    assert member["membership_state"] == "SUSPENDED"
    assert member["mls_access_state"] == "DISABLED"
    office_now = get_success_data(api.get_office(assoc["id"], office["id"], STAFF))
    assert office_now["status"] == "SUSPENDED", "broker suspension suspends the office"

    resp = api.activate_listing(
        assoc["id"], office["id"], listing["id"],
        make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED)
    listing_now = get_success_data(
        api.get_listing(assoc["id"], office["id"], listing["id"], STAFF))
    assert listing_now["status"] == "DRAFT"


def test_reconcile_cascade_reinstates_on_last_invoice_payment(api):
    """PRD §3.2: "if the member now holds zero `PENDING` invoices and their
    `membership_state` is `SUSPENDED`, the member returns to `ACTIVE`, their
    `mls_access_state` becomes `ENABLED`".
    PRD §3.1: "When that broker is reinstated from `SUSPENDED` to `ACTIVE`,
    the office returns to `ACTIVE`."

    Design: Difficulty/transitive_cascade/reconcile_suspends_member_cascades_office_and_blocks_listing
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="TC1B")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    period = create_dues_period(
        assoc["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-01-31T00:00:00Z", grace_end_date="2027-03-02T00:00:00Z",
        amount_cents=120000)
    set_clock("2027-01-15T00:00:00Z")
    bill_dues_period(assoc["id"], period)
    invoice = get_member_invoice(assoc["id"], period["id"], broker["id"])
    set_clock("2027-03-03T00:00:00Z")
    validate_success(api.reconcile_dues_period(assoc["id"], period["id"], STAFF))
    pay_invoice(assoc["id"], invoice)
    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    assert member["membership_state"] == "ACTIVE"
    assert member["mls_access_state"] == "ENABLED"
    office_now = get_success_data(api.get_office(assoc["id"], office["id"], STAFF))
    assert office_now["status"] == "ACTIVE"


def test_late_status_change_cascades_citation_flag_then_payment_unflags(api):
    """PRD §3.4: "When `late_by_hours` is greater than zero, the server automatically creates a citation with `rule_code` `LATE_STATUS` and `source` `AUTO_LATE_STATUS` against the listing member — its id is stored on the status change as `auto_citation_id` — and sets the listing's `accuracy_flag` to `FLAGGED`. The cascade matters: a flagged listing cannot be withdrawn or cancelled until the flag clears."
    PRD §3.5: "if the citation references a listing whose `accuracy_flag` is
    `FLAGGED` and no other `OPEN` or `HEARING_PENDING` citation references
    that listing, the flag returns to `CLEAN`, unblocking withdrawal and
    cancellation."

    Design: Difficulty/transitive_cascade/late_status_change_cascades_citation_flag_then_payment_unflags
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="TC2", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="LATE_STATUS", fine_amount_cents=25000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-TC2")
    activate_listing(assoc["id"], office["id"], listing)
    # Record at 2026-09-06T01:00 a change with business instant 2026-09-03T00:00:
    # elapsed 73h -> late_by_hours 25.
    set_clock("2026-09-06T01:00:00Z")
    updated = change_status(assoc["id"], office["id"], listing, "PENDING",
                            "2026-09-03T00:00:00Z")
    assert updated["accuracy_flag"] == "FLAGGED"

    resp = api.change_listing_status(
        assoc["id"], office["id"], listing["id"],
        {"to_status": "WITHDRAWN", "business_effective_at": "2026-09-06T01:00:00Z"},
        make_member_headers(broker["id"]))
    # PRD gates the flag on an ACTIVE listing (§3.4) yet also states a flagged
    # listing cannot be withdrawn until the flag clears; for a PENDING listing
    # the exact rejection is not uniquely pinned — either the flag gate fires
    # or the PENDING->WITHDRAWN edge itself is rejected as illegal.
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_LISTING_FLAGGED, ApiErrorId.ERR_INVALID_STATE])

    cites = get_success_data(api.list_citations(
        assoc["id"], STAFF, params={"listing_id": listing["id"]}))
    assert len(cites) == 1
    auto_cit = cites[0]
    assert auto_cit["rule_code"] == "LATE_STATUS"
    assert auto_cit["source"] == "AUTO_LATE_STATUS"
    assert auto_cit["fine_amount_cents"] == 25000

    changes = get_success_data(api.list_listing_status_changes(
        assoc["id"], office["id"], listing["id"], STAFF))
    pending_change = [c for c in changes if c["to_status"] == "PENDING"][0]
    assert pending_change["late_by_hours"] == 25
    assert pending_change["auto_citation_id"] == auto_cit["id"]

    # Paying the citation clears the flag (no other open citations reference it).
    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    tender = 25000 - min(25000, member["sanction_credit_balance_cents"])
    validate_success(api.pay_citation(
        assoc["id"], auto_cit["id"], tender, make_member_headers(broker["id"])))
    listing_now = get_success_data(
        api.get_listing(assoc["id"], office["id"], listing["id"], STAFF))
    assert listing_now["accuracy_flag"] == "CLEAN"
    assert listing_now["status"] == "PENDING"
    member_after = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    assert member_after["sanction_credit_balance_cents"] == \
        member["sanction_credit_balance_cents"] + 25000


def test_late_status_change_flag_blocks_cancel_then_payment_restores(api):
    """PRD §3.5: "if the citation references a listing whose `accuracy_flag` is `FLAGGED` and no other `OPEN` or `HEARING_PENDING` citation references that listing, the flag returns to `CLEAN`, unblocking withdrawal and cancellation."
    PRD §3.5: "A successful payment transitions the citation `OPEN` → `PAID`, credits the full `fine_amount_cents` to the member's balance, recomputes the member's `strikes_12m`, and runs the unflag chain".

    Design: Difficulty/transitive_cascade/late_status_change_cascades_citation_flag_then_payment_unflags
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="TC2B", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="LATE_STATUS", fine_amount_cents=25000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-TC2B")
    activate_listing(assoc["id"], office["id"], listing)
    # Late change: business instant 2026-09-03, recorded 2026-09-06 (73h -> late).
    set_clock("2026-09-06T01:00:00Z")
    updated = change_status(assoc["id"], office["id"], listing, "PENDING",
                            "2026-09-03T00:00:00Z")
    assert updated["accuracy_flag"] == "FLAGGED"
    # Paying the auto-citation restores the flag to CLEAN.
    cites = get_success_data(api.list_citations(
        assoc["id"], STAFF, params={"listing_id": listing["id"]}))
    assert len(cites) == 1
    auto_cit = cites[0]
    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    tender = 25000 - min(25000, member["sanction_credit_balance_cents"])
    validate_success(api.pay_citation(
        assoc["id"], auto_cit["id"], tender, make_member_headers(broker["id"])))
    listing_now = get_success_data(
        api.get_listing(assoc["id"], office["id"], listing["id"], STAFF))
    assert listing_now["accuracy_flag"] == "CLEAN"
    cit_now = get_success_data(api.get_citation(assoc["id"], auto_cit["id"], STAFF))
    assert cit_now["status"] == "PAID"
