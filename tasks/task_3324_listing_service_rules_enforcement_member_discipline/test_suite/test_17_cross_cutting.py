"""Cross-cutting layers: the listing status-change audit trail, compensation
stripping at feed sync, and immediate read-after-write consistency."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock,
    activate_policy_revision, activate_listing, change_status,
    create_citation, pay_citation,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_listing_status_changes_audit_trail_completeness(api):
    """PRD §3.4: "Every status change appends a `StatusChange` audit record
    capturing the `listing_id`, the `from_status`, the `to_status`, the
    supplied `business_effective_at`, and the `recorded_at` logical instant at
    which the change was entered; the listing's `status_changed_at` is
    refreshed to the same instant."
    PRD §3.4: "For status changes other than those into `PENDING` or `SOLD`,
    `late_by_hours` is 0 and no audit fires."

    Design: Corner/cross_cutting_layers/listing_status_changes_audit_trail_completeness
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="L1")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-L1")
    set_clock("2026-09-02T00:00:00Z")
    activate_listing(assoc["id"], office["id"], listing)
    change_status(assoc["id"], office["id"], listing, "PENDING",
                  "2026-09-02T01:00:00Z")
    change_status(assoc["id"], office["id"], listing, "SOLD",
                  "2026-09-02T02:00:00Z")
    changes = get_success_data(api.list_listing_status_changes(
        assoc["id"], office["id"], listing["id"], STAFF))
    assert len(changes) == 3
    transitions = [(c["from_status"], c["to_status"]) for c in changes]
    assert transitions == [("DRAFT", "ACTIVE"), ("ACTIVE", "PENDING"),
                           ("PENDING", "SOLD")]
    for c in changes:
        assert c["late_by_hours"] == 0
        assert c["auto_citation_id"] is None


def test_comp_off_strips_offer_comp_from_sync(api):
    """PRD §3.9: "When the governing `ACTIVE` policy revision's
    `comp_display_mode` is `COMP_DISPLAY_OFF`, `offer_comp_cents` is stripped
    from both variants at sync time even when the licensee's allowlist names
    it; the same strip applies on every sync after such a revision activates."

    Design: Corner/cross_cutting_layers/comp_off_strips_offer_comp_from_sync
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="L2")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-L2", offer_comp_cents=300000)
    activate_listing(assoc["id"], office["id"], listing)
    lic = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "StripP", "scope": "IDX", "display_ruleset_version": 1,
         "listing_field_allowlist": ["offer_comp_cents", "property_address"]}, STAFF))
    validate_success(api.activate_data_license(assoc["id"], lic["id"], STAFF))
    sync_on = get_success_data(api.sync_feed(assoc["id"], lic["id"], STAFF))
    assert sync_on["comp_fields_stripped"] is False, \
        "COMP_DISPLAY_ON: allowlisted comp field preserved"
    assoc_now = get_success_data(api.get_association(assoc["id"], STAFF))
    activate_policy_revision(assoc["id"], assoc_now["version"], revision_code="R2",
                             effective_at="2026-09-10T00:00:00Z",
                             comp_display_mode="COMP_DISPLAY_OFF",
                             activate_now="2026-09-10T00:00:00Z")
    sync_off = get_success_data(api.sync_feed(assoc["id"], lic["id"], STAFF))
    assert sync_off["comp_fields_stripped"] is True, \
        "COMP_DISPLAY_OFF: offer_comp_cents stripped despite allowlist"


def test_immediate_consistency_mutation_visible_in_same_response(api):
    """PRD §3.5: "A successful payment transitions the citation `OPEN` →
    `PAID`, credits the full `fine_amount_cents` to the member's balance,
    recomputes the member's `strikes_12m`".
    PRD §3.5: "the citation still counts" (a paid citation with no later
    reinstatement counts toward `strikes_12m`).

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response
    """
    assoc = create_association(association_code="K1", sanction_credit_cap_cents=200000)
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    cit = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    paid = validate_success(api.pay_citation(
        assoc["id"], cit["id"], 30000, make_member_headers(mv["id"])))
    assert paid["status"] == "PAID", "mutation response itself shows the transition"
    member = get_success_data(api.get_member(assoc["id"], mv["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 30000
    assert member["strikes_12m"] == 1, "immediate re-read: credit and strikes visible"
