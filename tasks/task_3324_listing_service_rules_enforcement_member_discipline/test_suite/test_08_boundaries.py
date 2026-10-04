"""Boundary precision: the 48-hour status-change lateness boundary and the
sanction-credit cap boundary (exactly at the cap allowed, one cent over
rejected)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock,
    activate_policy_revision, activate_listing, change_status,
    issue_and_pay_citation, seed_credit,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_status_change_48h_boundary_exact(api):
    """PRD §3.4: "The boundary is exact: recording precisely 48 hours after the
    business event is timely; 48 hours and one second floors to 48 whole hours
    and is still timely; 49 whole hours yields `late_by_hours` of 1 and is
    late."
    PRD §3.4: "When `late_by_hours` is greater than zero, the server
    automatically creates a citation with `rule_code` `LATE_STATUS` and
    `source` `AUTO_LATE_STATUS` against the listing member — its id is stored
    on the status change as `auto_citation_id` — and sets the listing's
    `accuracy_flag` to `FLAGGED`."

    Design: Difficulty/boundary_precision_check/status_change_48h_boundary_exact
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="BP1", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="LATE_STATUS", fine_amount_cents=25000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    la = create_listing(assoc["id"], office["id"], broker["id"], mls_number="MLS-B48A")
    activate_listing(assoc["id"], office["id"], la)
    lb = create_listing(assoc["id"], office["id"], broker["id"], mls_number="MLS-B49A")
    activate_listing(assoc["id"], office["id"], lb)

    # Listing A: exactly 48h00m after the business event -> timely.
    set_clock("2026-09-05T00:00:00Z")
    updated_a = change_status(assoc["id"], office["id"], la, "PENDING",
                              "2026-09-03T00:00:00Z")
    assert updated_a["accuracy_flag"] == "CLEAN"
    cites_a = get_success_data(api.list_citations(
        assoc["id"], STAFF, params={"listing_id": la["id"]}))
    assert cites_a == [], "exactly 48h is timely; no citation"
    changes_a = get_success_data(api.list_listing_status_changes(
        assoc["id"], office["id"], la["id"], STAFF))
    pa = [c for c in changes_a if c["to_status"] == "PENDING"][0]
    assert pa["late_by_hours"] == 0
    assert pa["auto_citation_id"] is None

    # Listing B: 49h00m after the business event -> late_by_hours 1.
    set_clock("2026-09-05T01:00:00Z")
    updated_b = change_status(assoc["id"], office["id"], lb, "PENDING",
                              "2026-09-03T00:00:00Z")
    assert updated_b["accuracy_flag"] == "FLAGGED"
    changes_b = get_success_data(api.list_listing_status_changes(
        assoc["id"], office["id"], lb["id"], STAFF))
    pb = [c for c in changes_b if c["to_status"] == "PENDING"][0]
    assert pb["late_by_hours"] == 1
    assert pb["auto_citation_id"] is not None


def test_status_change_48h_plus_one_second_still_timely(api):
    """PRD §3.4: "The boundary is exact: recording precisely 48 hours after the
    business event is timely; 48 hours and one second floors to 48 whole hours
    and is still timely; 49 whole hours yields `late_by_hours` of 1 and is
    late."

    Design: Difficulty/boundary_precision_check/status_change_48h_boundary_exact
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="BP1C", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="LATE_STATUS", fine_amount_cents=25000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-B48S")
    activate_listing(assoc["id"], office["id"], listing)
    set_clock("2026-09-05T00:00:01Z")
    updated = change_status(assoc["id"], office["id"], listing, "PENDING",
                            "2026-09-03T00:00:00Z")
    assert updated["accuracy_flag"] == "CLEAN", \
        "48h00m01s floors to 48 whole hours -> still timely"
    cites = get_success_data(api.list_citations(
        assoc["id"], STAFF, params={"listing_id": listing["id"]}))
    assert cites == []


def test_credit_cap_exactly_at_cap_allowed_one_cent_over_rejected(api):
    """PRD §3.5: "A member holding a `PAID` citation may additionally top up
    their own credit balance through that citation by donating `amount_cents`
    — an external settlement credit with no fine linkage. The donation is
    allowed only when the citation is `PAID` (only settled fines yield stable
    credits) and only when the resulting balance stays at or below the
    association cap; landing exactly at the cap is permitted, exceeding it is
    `ERR_CREDIT_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/credit_cap_exactly_at_cap_allowed_one_cent_over_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="BP2", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    cit = issue_and_pay_citation(assoc["id"], broker["id"], rule_code="INACCURACY")
    seed_credit(assoc["id"], broker["id"], 150000, note="seed to 180000")
    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 180000

    # Donating the exact remaining headroom lands AT the cap -> allowed.
    resp = api.donate_credit(assoc["id"], cit["id"], 20000,
                             make_member_headers(broker["id"]))
    validate_success(resp)
    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 200000

    # One cent over the cap is rejected; balance unchanged.
    resp = api.donate_credit(assoc["id"], cit["id"], 1,
                             make_member_headers(broker["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_CAP_EXCEEDED)
    member = get_success_data(api.get_member(assoc["id"], broker["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 200000


def test_credit_cap_overflow_on_citation_pay_rejected_before_state_change(api):
    """PRD §3.5: "Before any state change, the server checks that crediting
    the fine amount to the member's `sanction_credit_balance_cents` would not
    exceed the association's `sanction_credit_cap_cents`; on overflow the
    payment is rejected with `ERR_CREDIT_CAP_EXCEEDED` and nothing changes."

    Design: Difficulty/boundary_precision_check/credit_cap_exactly_at_cap_allowed_one_cent_over_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="BP2B", sanction_credit_cap_cents=200000)
    member = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    seed_credit(assoc["id"], member["id"], 190000, note="seed near cap")
    from test_helpers import create_citation
    cit = create_citation(assoc["id"], member["id"], rule_code="INACCURACY")
    # Crediting 30000 would push balance to 220000 > 200000 -> rejected.
    # Tender after auto-applied credits: 30000 - min(30000, 190000) = 0.
    resp = api.pay_citation(assoc["id"], cit["id"], 0,
                            make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_CREDIT_CAP_EXCEEDED)
    cit_now = get_success_data(api.get_citation(assoc["id"], cit["id"], STAFF))
    assert cit_now["status"] == "OPEN", "cap check runs before any state change"
    member_now = get_success_data(api.get_member(assoc["id"], member["id"], STAFF))
    assert member_now["sanction_credit_balance_cents"] == 190000
