"""Compensating invariants: the hearing+overturn cycle conserves the member's
credit balance; the consolidation+bill-skip pair conserves per-member annual
dues liability."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock,
    activate_policy_revision, activate_listing,
    issue_and_pay_citation, create_citation,
    create_dues_period, bill_dues_period,
    make_member_headers, make_panelist_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_citation_pay_then_waive_via_overturn_conserves_credit_balance(api):
    """PRD §3.5: "if the panel overturns, the citation transitions to `WAIVED`
    and no credit accrues, since nothing was paid".
    PRD §3.5: "A successful payment transitions the citation `OPEN` → `PAID`,
    credits the full `fine_amount_cents` to the member's balance, recomputes
    the member's `strikes_12m`".
    PRD §3.5: "the citation still counts" (never-suspended member paid
    citations count toward `strikes_12m`).

    Design: Difficulty/compensating_invariant/citation_pay_then_waive_via_overturn_conserves_credit_balance
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="CI1", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    violator = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    p1 = create_member(assoc["id"], member_nr="P1", full_name="Panel One")
    p2 = create_member(assoc["id"], member_nr="P2", full_name="Panel Two")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-CI1")
    activate_listing(assoc["id"], office["id"], listing)

    # C1 paid directly: balance += 30000, strikes += 1.
    c1 = issue_and_pay_citation(assoc["id"], violator["id"], rule_code="INACCURACY")
    # C2 heard and OVERTURNED: nothing accrues.
    c2 = create_citation(assoc["id"], violator["id"], rule_code="INACCURACY")
    validate_success(api.request_hearing(
        assoc["id"], c2["id"], make_member_headers(violator["id"])))
    panel = get_success_data(api.convene_hearing_panel(
        assoc["id"], "CITATION", c2["id"], STAFF))
    holder_id = panel["selected_member_ids"][0]
    ruler_id = panel["selected_member_ids"][1]
    validate_success(api.hold_hearing(
        assoc["id"], panel["id"], make_panelist_headers(holder_id)))
    validate_success(api.rule_panel(
        assoc["id"], panel["id"], "OVERTURN", make_panelist_headers(ruler_id)))

    c2_now = get_success_data(api.get_citation(assoc["id"], c2["id"], STAFF))
    assert c2_now["status"] == "WAIVED"
    member = get_success_data(api.get_member(assoc["id"], violator["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 30000, \
        "hearing+overturn cycle adds exactly 0; only the paid fine persists"
    assert member["strikes_12m"] == 1, "only the PAID citation counts"


def test_citation_waive_via_overturn_unflags_listing_without_credit(api):
    """PRD §3.5: "if the panel overturns, the citation transitions to `WAIVED`
    and no credit accrues, since nothing was paid". "All three branches run the
    listing unflag chain."

    Design: Difficulty/compensating_invariant/citation_pay_then_waive_via_overturn_conserves_credit_balance
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="CI1B", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    p1 = create_member(assoc["id"], member_nr="P1", full_name="Panel One")
    p2 = create_member(assoc["id"], member_nr="P2", full_name="Panel Two")
    p3 = create_member(assoc["id"], member_nr="P3", full_name="Panel Three")
    create_fine_schedule(assoc["id"], rule_code="LATE_STATUS", fine_amount_cents=25000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-CI1B")
    activate_listing(assoc["id"], office["id"], listing)
    # Late status change flags the listing and auto-cites the member.
    set_clock("2026-09-06T01:00:00Z")
    flagged = api.change_listing_status(
        assoc["id"], office["id"], listing["id"],
        {"to_status": "PENDING", "business_effective_at": "2026-09-03T00:00:00Z"},
        make_member_headers(broker["id"]))
    assert get_success_data(flagged)["accuracy_flag"] == "FLAGGED"
    cites = get_success_data(api.list_citations(
        assoc["id"], STAFF, params={"listing_id": listing["id"]}))
    auto_cit = cites[0]
    validate_success(api.request_hearing(
        assoc["id"], auto_cit["id"], make_member_headers(broker["id"])))
    panel = get_success_data(api.convene_hearing_panel(
        assoc["id"], "CITATION", auto_cit["id"], STAFF))
    holder_id = panel["selected_member_ids"][0]
    ruler_id = panel["selected_member_ids"][1]
    validate_success(api.hold_hearing(
        assoc["id"], panel["id"], make_panelist_headers(holder_id)))
    validate_success(api.rule_panel(
        assoc["id"], panel["id"], "OVERTURN", make_panelist_headers(ruler_id)))
    cit_now = get_success_data(api.get_citation(assoc["id"], auto_cit["id"], STAFF))
    assert cit_now["status"] == "WAIVED"
    listing_now = get_success_data(
        api.get_listing(assoc["id"], office["id"], listing["id"], STAFF))
    assert listing_now["accuracy_flag"] == "CLEAN", "overturn runs the unflag chain"
    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 0, "nothing was paid, no credit"
    assert member["strikes_12m"] == 0


def test_consolidation_execute_then_recognition_conserves_invoice_total(api):
    """PRD §3.2: "when a member's `association_id` was re-pointed by an
    executed consolidation, the member is billed by the surviving association's
    period at the survivor's `amount_cents` — but if the member already holds
    any invoice, in any status, for the same calendar year from the absorbed
    association, the survivor's billing skips that member entirely, so no
    member is double-billed for a year."
    PRD §3.10: "invoices stay with their member — who now belongs to the
    survivor".

    Design: Difficulty/compensating_invariant/consolidation_execute_then_recognition_conserves_invoice_total
    """
    set_clock("2026-09-01T00:00:00Z")
    survivor = create_association(association_code="AS2", membership_dues_cents=120000)
    absorbed = create_association(association_code="AA2", membership_dues_cents=90000,
                                  late_fee_tier1_cents=4000, late_fee_tier2_cents=12000)
    mx = create_member(absorbed["id"], member_nr="MX", full_name="Member X")
    event = get_success_data(api.create_consolidation(
        survivor["id"], {"absorbed_association_id": absorbed["id"],
                         "effective_at": "2027-02-01T00:00:00Z"}, STAFF))
    a_period = create_dues_period(
        absorbed["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-01-31T00:00:00Z", grace_end_date="2027-03-02T00:00:00Z",
        amount_cents=90000)
    set_clock("2027-01-10T00:00:00Z")
    bill_dues_period(absorbed["id"], a_period)
    s_period = create_dues_period(
        survivor["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-02-28T00:00:00Z", grace_end_date="2027-03-30T00:00:00Z",
        amount_cents=120000)
    set_clock("2027-02-01T00:00:00Z")
    validate_success(api.execute_consolidation(survivor["id"], event["id"], STAFF))
    bill_dues_period(survivor["id"], s_period)
    mx_invoices = get_success_data(api.list_dues_invoices_flat(
        STAFF, params={"member_id": mx["id"]}))
    assert len(mx_invoices) == 1, \
        "survivor's bill skips the re-pointed member who already holds a same-year invoice"
    total_due = sum(inv["amount_due_cents"] for inv in mx_invoices)
    assert total_due == 90000, \
        "exactly one annual liability survives consolidation (no double-billing)"


def test_consolidation_repointed_member_without_prior_invoice_billed_by_survivor(api):
    """PRD §3.2: "when a member's `association_id` was re-pointed by an
    executed consolidation, the member is billed by the surviving association's
    period at the survivor's `amount_cents`".

    Design: Difficulty/compensating_invariant/consolidation_execute_then_recognition_conserves_invoice_total
    """
    set_clock("2026-09-01T00:00:00Z")
    survivor = create_association(association_code="AS2B", membership_dues_cents=120000)
    absorbed = create_association(association_code="AA2B", membership_dues_cents=90000,
                                  late_fee_tier1_cents=4000, late_fee_tier2_cents=12000)
    mx = create_member(absorbed["id"], member_nr="MX", full_name="Member X")
    event = get_success_data(api.create_consolidation(
        survivor["id"], {"absorbed_association_id": absorbed["id"],
                         "effective_at": "2027-02-01T00:00:00Z"}, STAFF))
    s_period = create_dues_period(
        survivor["id"], year=2027, period_start_date="2026-12-01T00:00:00Z",
        due_date="2027-02-28T00:00:00Z", grace_end_date="2027-03-30T00:00:00Z",
        amount_cents=120000)
    set_clock("2027-02-01T00:00:00Z")
    validate_success(api.execute_consolidation(survivor["id"], event["id"], STAFF))
    bill_dues_period(survivor["id"], s_period)
    mx_invoices = get_success_data(api.list_dues_invoices_flat(
        STAFF, params={"member_id": mx["id"]}))
    assert len(mx_invoices) == 1
    assert mx_invoices[0]["dues_period_id"] == s_period["id"], \
        "re-pointed member with no prior same-year invoice is billed by the survivor"
    assert mx_invoices[0]["base_amount_cents"] == 120000
