"""Calculation rules: the 24-hour clear-cooperation boundary, the empty fine
schedule lookup rejection, feed-projection scope variants, ethics sanction
tiers, and the 365-day half-open strikes window."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock,
    activate_policy_revision, activate_listing, change_status,
    create_citation, issue_and_pay_citation, pay_citation,
    setup_ethics_case_decided,
    make_member_headers, make_panelist_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_clear_coop_24h_boundary_timely_vs_late(api):
    """PRD §3.3: "when `public_marketing_at` is set and the activation instant
    is later than exactly 24 hours after `public_marketing_at`, the listing is
    in violation of the clear-cooperation obligation and the server
    automatically creates a citation with `rule_code` `CLEAR_COOP` and `source`
    `AUTO_LATE_LISTING` against the `listing_member_id`, referencing the
    listing. The deadline boundary is inclusive: activation at exactly the
    deadline instant is timely, and activation one second after it is late."

    Design: Corner/calculations/clear_coop_24h_boundary_timely_vs_late
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="C1")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="CLEAR_COOP", fine_amount_cents=40000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-02T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    la = create_listing(assoc["id"], office["id"], broker["id"], mls_number="MLS-CC1",
                        public_marketing_at="2026-09-10T00:00:00Z")
    lb = create_listing(assoc["id"], office["id"], broker["id"], mls_number="MLS-CC2",
                        public_marketing_at="2026-09-10T00:00:00Z")
    # Activate exactly at the deadline (public_marketing_at + 24h): timely.
    set_clock("2026-09-11T00:00:00Z")
    activate_listing(assoc["id"], office["id"], la)
    cites_a = get_success_data(api.list_citations(
        assoc["id"], STAFF, params={"listing_id": la["id"]}))
    assert cites_a == [], "activation exactly at the 24h deadline is timely"
    # One second after the deadline: late, auto-citation CLEAR_COOP.
    set_clock("2026-09-11T00:00:01Z")
    activate_listing(assoc["id"], office["id"], lb)
    cites_b = get_success_data(api.list_citations(
        assoc["id"], STAFF, params={"listing_id": lb["id"]}))
    assert len(cites_b) == 1
    assert cites_b[0]["rule_code"] == "CLEAR_COOP"
    assert cites_b[0]["source"] == "AUTO_LATE_LISTING"
    assert cites_b[0]["fine_amount_cents"] == 40000
    assert cites_b[0]["member_id"] == broker["id"]


def test_citation_fine_lookup_empty_set_rejected(api):
    """PRD §3.5: "At citation creation the server finds the single `ACTIVE` row
    covering the citation's `assessed_at`; if none exists, creation is rejected
    with `ERR_NO_FINE_SCHEDULE`."

    Design: Corner/calculations/citation_fine_lookup_empty_set_rejected
    """
    assoc = create_association(association_code="C2")
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    resp = api.create_citation(
        assoc["id"], {"member_id": mv["id"], "rule_code": "INACCURACY"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_NO_FINE_SCHEDULE)


def test_feed_sync_projection_variant_divergence_idx_vs_backoffice(api):
    """PRD §3.9: "For `IDX` and `VOW` scopes, only listings in `ACTIVE` or `PENDING` are included and only allowlisted fields are projected; `VOW` additionally always appends `office_id`."
    PRD §3.9: "For `BACKOFFICE` scope, listings in every status except `DRAFT` — that is, `ACTIVE`, `PENDING`, `SOLD`, `WITHDRAWN`, `EXPIRED`, and `CANCELLED` — are included with all fields."
    PRD §3.9: "A successful sync sets `feed_sync_state` to `CURRENT` and reports the `projected_listing_count`, whether `comp_fields_stripped` occurred, and the resulting `feed_sync_state`."

    Design: Corner/calculations/feed_sync_projection_variant_divergence_idx_vs_backoffice
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="C3")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    l1 = create_listing(assoc["id"], office["id"], broker["id"], mls_number="MLS-F1")
    activate_listing(assoc["id"], office["id"], l1)
    l2 = create_listing(assoc["id"], office["id"], broker["id"], mls_number="MLS-F2")
    activate_listing(assoc["id"], office["id"], l2)
    change_status(assoc["id"], office["id"], l2, "PENDING", "2026-09-02T01:00:00Z")
    change_status(assoc["id"], office["id"], l2, "SOLD", "2026-09-02T02:00:00Z")
    li = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "IdxP", "scope": "IDX", "display_ruleset_version": 1,
         "listing_field_allowlist": ["property_address"]}, STAFF))
    lb = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "BackP", "scope": "BACKOFFICE", "display_ruleset_version": 1,
         "listing_field_allowlist": ["property_address"]}, STAFF))
    validate_success(api.activate_data_license(assoc["id"], li["id"], STAFF))
    validate_success(api.activate_data_license(assoc["id"], lb["id"], STAFF))
    sync_idx = get_success_data(api.sync_feed(assoc["id"], li["id"], STAFF))
    assert sync_idx["projected_listing_count"] == 1, \
        "IDX variant projects only ACTIVE/PENDING listings (the SOLD one is excluded)"
    assert sync_idx["comp_fields_stripped"] is False
    assert sync_idx["feed_sync_state"] == "CURRENT"
    sync_bo = get_success_data(api.sync_feed(assoc["id"], lb["id"], STAFF))
    assert sync_bo["projected_listing_count"] == 2, \
        "BACKOFFICE variant projects every non-DRAFT status (ACTIVE + SOLD)"
    assert sync_bo["feed_sync_state"] == "CURRENT"


def test_ethics_sanction_tiers_by_live_strikes(api):
    """PRD §3.6: "An upholding decision sets the case's `sanction_cents` from the respondent's live `strikes_12m` read at the ruling instant — after the panel's decision is recorded but before the case transitions, and independently of any citation branch that a different panel might be ruling on: 50000 cents when the respondent has no strikes, 100000 cents at one strike, 250000 cents at two, and 500000 cents at three or more. The sanction is applied as a fine-only ledger entry and never feeds the respondent's credit balance. If the respondent's `strikes_12m` is at least 3 after the sanction, the respondent is suspended".

    Design: Corner/calculations/ethics_sanction_tiers_by_live_strikes
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx0 = setup_ethics_case_decided(respondent_strikes=0)
    get_success_data(api.rule_panel(
        ctx0["assoc"]["id"], ctx0["panel"]["id"], "UPHOLD",
        make_panelist_headers(ctx0["ruler_id"])))
    case0 = get_success_data(
        api.get_ethics_case(ctx0["assoc"]["id"], ctx0["case"]["id"], STAFF))
    assert case0["status"] == "DECIDED"
    assert case0["sanction_cents"] == 50000, "0-strike tier"

    ctx1 = setup_ethics_case_decided(respondent_strikes=1)
    get_success_data(api.rule_panel(
        ctx1["assoc"]["id"], ctx1["panel"]["id"], "UPHOLD",
        make_panelist_headers(ctx1["ruler_id"])))
    case1 = get_success_data(
        api.get_ethics_case(ctx1["assoc"]["id"], ctx1["case"]["id"], STAFF))
    assert case1["status"] == "DECIDED"
    assert case1["sanction_cents"] == 100000, "1-strike tier"
    respondent = get_success_data(
        api.get_member(ctx1["assoc"]["id"], ctx1["respondent"]["id"], STAFF))
    assert respondent["membership_state"] == "ACTIVE", \
        "strikes_12m == 1 < 3: no ethics-driven suspension"
    assert respondent["sanction_credit_balance_cents"] == 30000, \
        "ethics sanction never feeds the credit balance (only the paid citation did)"


def test_strikes_365d_half_open_window(api):
    """PRD §3.5: "its `assessed_at` falls within the trailing 365 days — the
    window is half-open, excluding the instant exactly 365 days ago and
    including now".

    Design: Corner/calculations/strikes_365d_half_open_window
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="C5", sanction_credit_cap_cents=200000)
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    set_clock("2026-09-02T00:00:00Z")
    c_old = issue_and_pay_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    # c_new is assessed one day later so that only c_old sits exactly on the
    # excluded 365-day boundary at the final checkpoint.
    set_clock("2026-09-03T00:00:00Z")
    c_new = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    # At 2027-09-01, c_old is 364 days old -> included.
    set_clock("2027-09-01T00:00:00Z")
    pay_citation(assoc["id"], c_new)
    member = get_success_data(api.get_member(assoc["id"], mv["id"], STAFF))
    assert member["strikes_12m"] == 2, \
        "citation assessed 364 days ago is inside the half-open window"
    # At 2027-09-02, c_old is exactly 365 days old -> excluded.
    c_new2 = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    set_clock("2027-09-02T00:00:00Z")
    pay_citation(assoc["id"], c_new2)
    member = get_success_data(api.get_member(assoc["id"], mv["id"], STAFF))
    assert member["strikes_12m"] == 2, \
        "citation assessed exactly 365 days ago is excluded; the two newer ones count"
