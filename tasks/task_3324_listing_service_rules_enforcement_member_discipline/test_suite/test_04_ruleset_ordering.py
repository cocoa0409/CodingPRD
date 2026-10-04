"""Ruleset-version evaluation order: pinned before license audit; the same
license passes at ruleset 1 and fails the audit after a second revision bumps
the ruleset to 2."""
from test_helpers import (
    validate_success, get_success_data,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock, activate_policy_revision,
    activate_listing,
    make_member_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_ruleset_version_order_pinned_before_license_audit(api):
    """PRD §3.9: "An association's current display-ruleset version is defined as the count of its policy revisions in status `ACTIVE` or `SUPERSEDED`."
    PRD §3.9: "This definition sits atop a circular-looking dependency — the ruleset version feeds license compliance, a license audit can create a citation, citation payment changes strikes — so the evaluation order is pinned: first count revisions, then evaluate the license check, then issue any citation; strikes never feed back into the ruleset version."
    PRD §3.9: "when it finds a violation — the allowlist contains
    `offer_comp_cents` while the governing revision suppresses compensation
    display, or the license's `display_ruleset_version` has drifted from the
    association's current ruleset version — the license transitions `ACTIVE` →
    `SUSPENDED` and the server automatically creates a citation with
    `rule_code` `FEED_ABUSE` and `source` `STAFF` against a deterministically
    chosen member: the `broker_member_id` of the office owning the
    association's most recently activated `ACTIVE` listing".

    Design: Difficulty/combinatorial_formula/ruleset_version_order_pinned_before_license_audit
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="CC", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    create_fine_schedule(assoc["id"], rule_code="FEED_ABUSE", fine_amount_cents=25000)
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    r1 = activate_policy_revision(
        assoc["id"], assoc["version"], revision_code="R1",
        effective_at="2026-09-01T00:00:00Z", comp_display_mode="COMP_DISPLAY_ON")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-C1")
    activate_listing(assoc["id"], office["id"], listing)
    license_ = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "PortalX", "scope": "IDX", "display_ruleset_version": 1,
         "listing_field_allowlist": ["property_address"]},
        STAFF))
    validate_success(api.activate_data_license(assoc["id"], license_["id"], STAFF))
    # Second revision bumps ruleset_version to 2.
    assoc_now = get_success_data(api.get_association(assoc["id"], STAFF))
    r2 = activate_policy_revision(
        assoc["id"], assoc_now["version"], revision_code="R2",
        effective_at="2026-09-10T00:00:00Z", comp_display_mode="COMP_DISPLAY_OFF",
        activate_now="2026-09-10T00:00:00Z")
    audit = get_success_data(api.audit_feed(assoc["id"], license_["id"], STAFF))
    assert audit["violation_found"] is True, \
        "ruleset drift (license pinned at 1, ruleset now 2) alone suspends"
    assert audit["auto_citation_id"] is not None
    lic = get_success_data(api.get_data_license(assoc["id"], license_["id"], STAFF))
    assert lic["status"] == "SUSPENDED"
    citation = get_success_data(
        api.get_citation(assoc["id"], audit["auto_citation_id"], STAFF))
    assert citation["rule_code"] == "FEED_ABUSE"
    assert citation["source"] == "STAFF"
    assert citation["member_id"] == broker["id"], \
        "deterministic selector: broker of the office owning the most recently activated ACTIVE listing"
    r1_now = get_success_data(api.get_policy_revision(assoc["id"], r1["id"], STAFF))
    r2_now = get_success_data(api.get_policy_revision(assoc["id"], r2["id"], STAFF))
    assert r1_now["status"] == "SUPERSEDED"
    assert r2_now["status"] == "ACTIVE"


def test_ruleset_version_counts_active_and_superseded_revisions(api):
    """PRD §3.9: "An association's current display-ruleset version is defined
    as the count of its policy revisions in status `ACTIVE` or `SUPERSEDED`."
    PRD §3.9: "Activating a license requires its `display_ruleset_version` to
    equal the association's current ruleset version; a mismatch is rejected
    with `ERR_RULESET_MISMATCH`."

    Design: Difficulty/combinatorial_formula/ruleset_version_order_pinned_before_license_audit
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="CC2")
    activate_policy_revision(
        assoc["id"], assoc["version"], revision_code="R1",
        effective_at="2026-09-01T00:00:00Z")
    assoc_now = get_success_data(api.get_association(assoc["id"], STAFF))
    activate_policy_revision(
        assoc["id"], assoc_now["version"], revision_code="R2",
        effective_at="2026-09-05T00:00:00Z", activate_now="2026-09-05T00:00:00Z")
    # ACTIVE + SUPERSEDED count == 2: a license pinned at 2 activates.
    lic_ok = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "PortalOk", "scope": "IDX", "display_ruleset_version": 2,
         "listing_field_allowlist": ["property_address"]},
        STAFF))
    resp = api.activate_data_license(assoc["id"], lic_ok["id"], STAFF)
    activated = validate_success(resp)
    assert activated["status"] == "ACTIVE"
