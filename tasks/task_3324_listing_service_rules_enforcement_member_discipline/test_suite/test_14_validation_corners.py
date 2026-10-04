"""Validation corner rules: existence priority, tender exactness, the
arbitration 180-day window, the empty policy-revision selector, uniqueness,
and fine-schedule retirement."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, create_dues_period, bill_dues_period, set_clock,
    activate_policy_revision, activate_listing, change_status,
    create_citation, get_member_invoice,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_not_found_beats_member_suspended_priority(api):
    """PRD §2.7: "(3) existence — path resources and left-to-right nesting, `ERR_NOT_FOUND`; (4) the association consolidation gate — mutations under a `MERGED` association rejected with `ERR_ASSOCIATION_MERGED`; (5) optimistic concurrency — `ERR_STALE_VERSION` on the two guarded endpoints; (6) source-state legality — `ERR_INVALID_STATE`; (7) the member disciplinary and segregation-of-duties gate — `ERR_MEMBER_SUSPENDED`, `ERR_SCREENING_CONFLICT`, `ERR_APPEAL_CONFLICT`, `ERR_PANEL_SOLE_ACTOR`".
    PRD §2.7: "When a request violates more than one rule, the rejection is determined by a fixed priority order, evaluated from first to last".

    Design: Corner/validations/not_found_beats_member_suspended_priority
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="V1")
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    office = create_office(assoc["id"], mv["id"], office_code="O1")
    listing = create_listing(assoc["id"], office["id"], mv["id"], mls_number="MLS-V1")
    period = create_dues_period(
        assoc["id"], year=2026, period_start_date="2026-09-01T00:00:00Z",
        due_date="2026-09-05T00:00:00Z", grace_end_date="2026-09-10T00:00:00Z",
        amount_cents=100000)
    bill_dues_period(assoc["id"], period)
    set_clock("2026-09-11T00:00:00Z")
    validate_success(api.reconcile_dues_period(assoc["id"], period["id"], STAFF))
    # Activate under a bogus office id while the member is suspended.
    resp = api.activate_listing(
        assoc["id"], NON_EXISTENT_UUID, listing["id"], make_member_headers(mv["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_tender_mismatch_on_invoice_and_citation_pay(api):
    """PRD §3.2: "the request carries `tender_cents`, which must equal the
    invoice's `amount_due_cents` exactly — any other amount is rejected with
    `ERR_TENDER_MISMATCH` (HTTP 409)."
    PRD §3.5: "the member tenders `tender_cents`, which must equal the
    `fine_amount_cents` minus the portion covered by their sanction-credit
    balance — credits auto-apply up to the smaller of the fine and the balance,
    and the member tenders only the remainder; any other tender is rejected
    with `ERR_TENDER_MISMATCH`."

    Design: Corner/validations/tender_mismatch_on_invoice_and_citation_pay
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="V2", sanction_credit_cap_cents=200000)
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    cit = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    period = create_dues_period(
        assoc["id"], year=2026, period_start_date="2026-09-01T00:00:00Z",
        due_date="2026-09-30T00:00:00Z", grace_end_date="2026-10-10T00:00:00Z",
        amount_cents=100000)
    bill_dues_period(assoc["id"], period)
    invoice = get_member_invoice(assoc["id"], period["id"], mv["id"])
    resp = api.pay_dues_invoice(assoc["id"], invoice["id"], 99999,
                                make_member_headers(mv["id"]))
    validate_error(resp, ApiErrorId.ERR_TENDER_MISMATCH)
    invoice_now = get_success_data(
        api.get_dues_invoice(assoc["id"], invoice["id"], STAFF))
    assert invoice_now["status"] == "PENDING"
    resp = api.pay_citation(assoc["id"], cit["id"], 30001,
                            make_member_headers(mv["id"]))
    validate_error(resp, ApiErrorId.ERR_TENDER_MISMATCH)
    cit_now = get_success_data(api.get_citation(assoc["id"], cit["id"], STAFF))
    assert cit_now["status"] == "OPEN"
    member = get_success_data(api.get_member(assoc["id"], mv["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 0, "no credit accrued"


def test_arbitration_filing_window_180d_boundary(api):
    """PRD §3.7: "The listing must be `SOLD`, and the filing window is 180 days
    from the listing's closing date; a filing after the window is rejected with
    `ERR_ARBITRATION_WINDOW_CLOSED`. Filing stamps `filed_at` and transitions
    the case `FILED` → `MEDIATION_OFFERED` automatically."

    Design: Corner/validations/arbitration_filing_window_180d_boundary
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="V3")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    ml = create_member(assoc["id"], member_nr="ML", full_name="Lister")
    mr = create_member(assoc["id"], member_nr="MR", full_name="Responder")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    set_clock("2026-09-05T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], ml["id"], mls_number="MLS-V3")
    activate_listing(assoc["id"], office["id"], listing)
    change_status(assoc["id"], office["id"], listing, "PENDING",
                  "2026-09-05T00:30:00Z")
    # Closing instant: 2026-09-05T01:00:00Z.
    change_status(assoc["id"], office["id"], listing, "SOLD",
                  "2026-09-05T01:00:00Z")
    # Closing + 180 days = 2027-03-04T01:00:00Z -> allowed.
    set_clock("2027-03-04T01:00:00Z")
    ok = validate_success(api.create_arbitration_case(
        assoc["id"],
        {"respondent_member_id": mr["id"], "listing_id": listing["id"],
         "claim_amount_cents": 500000},
        make_member_headers(ml["id"])), expected_status=201)
    assert ok["status"] == "MEDIATION_OFFERED"
    # Closing + 181 days -> rejected.
    set_clock("2027-03-05T01:00:00Z")
    resp = api.create_arbitration_case(
        assoc["id"],
        {"respondent_member_id": mr["id"], "listing_id": listing["id"],
         "claim_amount_cents": 600000},
        make_member_headers(ml["id"]))
    validate_error(resp, ApiErrorId.ERR_ARBITRATION_WINDOW_CLOSED)


def test_no_policy_revision_blocks_activation(api):
    """PRD §3.3: "If no such revision exists, activation is rejected with
    `ERR_POLICY_REVISION_MISSING`."

    Design: Corner/validations/no_policy_revision_blocks_activation
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="V4")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-V4")
    resp = api.activate_listing(
        assoc["id"], office["id"], listing["id"], make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_POLICY_REVISION_MISSING)
    listing_now = get_success_data(
        api.get_listing(assoc["id"], office["id"], listing["id"], STAFF))
    assert listing_now["status"] == "DRAFT"


def test_duplicate_mls_number_and_member_nr_rejected(api):
    """PRD §3.1: "Members are registered into an association by staff with an
    association-scoped `member_nr` (unique within the association; a collision
    is rejected with `ERR_DUPLICATE_RESOURCE`)".
    PRD §3.3: "a globally unique `mls_number`".
    PRD §2.7: "(12) structural and uniqueness rules — `ERR_DUPLICATE_RESOURCE`".

    Design: Corner/validations/duplicate_mls_number_and_member_nr_rejected
    """
    assoc = create_association(association_code="V5")
    broker = create_member(assoc["id"], member_nr="DUP", full_name="First")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    create_listing(assoc["id"], office["id"], broker["id"], mls_number="DUPN")
    resp = api.create_member(assoc["id"], {"member_nr": "DUP", "full_name": "Second"},
                             STAFF)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)
    resp = api.create_listing(
        assoc["id"], office["id"],
        {"listing_member_id": broker["id"], "mls_number": "DUPN",
         "property_address": "6 Dup Dr", "list_price_cents": 21000000},
        make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_retire_last_fine_schedule_row_rejected(api):
    """PRD §3.5: "A schedule row may be retired by staff, transitioning it
    `ACTIVE` → `RETIRED`, but retiring the last remaining `ACTIVE` row for an
    association and rule code is forbidden and rejected with
    `ERR_LAST_FINE_SCHEDULE`."

    Design: Corner/validations/retire_last_fine_schedule_row_rejected
    """
    assoc = create_association(association_code="V6")
    s1 = create_fine_schedule(assoc["id"], rule_code="LATE_STATUS",
                              fine_amount_cents=25000,
                              effective_from="2026-01-01T00:00:00Z",
                              effective_to="2026-12-31T00:00:00Z")
    resp = api.retire_fine_schedule(assoc["id"], s1["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_LAST_FINE_SCHEDULE)
    # Adding an adjacent successor row permits the retirement.
    create_fine_schedule(assoc["id"], rule_code="LATE_STATUS", fine_amount_cents=26000,
                         effective_from="2026-12-31T00:00:00Z")
    retired = validate_success(api.retire_fine_schedule(assoc["id"], s1["id"], STAFF))
    assert retired["status"] == "RETIRED"
