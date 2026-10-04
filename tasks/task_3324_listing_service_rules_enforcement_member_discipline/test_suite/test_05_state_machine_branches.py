"""Non-linear state machines: the listing WITHDRAWN -> ACTIVE cycle with
policy re-selection, and the citation hearing fork (PAID / ESCALATED /
WAIVED)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, set_clock, activate_policy_revision,
    activate_listing, change_status,
    setup_active_listing, setup_citation_hearing_held,
    make_member_headers, make_panelist_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_listing_withdrawn_reactivation_cycle_with_policy_reselection(api):
    """PRD §3.3: "On reactivation from `WITHDRAWN`, the selector runs again and
    a fresh `policy_revision_id` is chosen — but the clear-cooperation audit
    does not run again, because the original `public_marketing_at` was already
    consumed by the first activation."
    PRD §3.10: "every other `ACTIVE` revision of the same association with an
    earlier `effective_at` transitions to `SUPERSEDED` — the newest-effective
    revision wins."

    Design: Difficulty/non_linear_state_machine/listing_withdrawn_reactivation_cycle_with_policy_reselection
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="NL1")
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    r1 = activate_policy_revision(
        assoc["id"], assoc["version"], revision_code="R1",
        effective_at="2026-09-01T00:00:00Z", activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-CYC")
    first = activate_listing(assoc["id"], office["id"], listing)
    assert first["policy_revision_id"] == r1["id"]
    change_status(assoc["id"], office["id"], first, "WITHDRAWN",
                  "2026-09-02T00:00:00Z")
    # Second revision activates later; R1 becomes SUPERSEDED.
    assoc_now = get_success_data(api.get_association(assoc["id"], STAFF))
    r2 = activate_policy_revision(
        assoc["id"], assoc_now["version"], revision_code="R2",
        effective_at="2026-09-06T00:00:00Z", activate_now="2026-09-06T00:00:00Z")
    second = activate_listing(assoc["id"], office["id"], listing)
    assert second["status"] == "ACTIVE"
    assert second["policy_revision_id"] == r2["id"], \
        "selector re-runs at reactivation and binds the newest ACTIVE revision"
    assert second["policy_revision_id"] != first["policy_revision_id"]


def test_listing_reactivation_from_withdrawn_preserves_active_state(api):
    """PRD §3.3: "Activation — by the listing's own member — transitions the
    listing from `DRAFT` (or from `WITHDRAWN`, on reactivation) to `ACTIVE`."
    PRD §3.4: "Withdrawal is reversible — the listing may later be reactivated
    under the activation rules — while `CANCELLED` and `SOLD` are terminal."

    Design: Difficulty/non_linear_state_machine/listing_withdrawn_reactivation_cycle_with_policy_reselection
    """
    ctx = setup_active_listing()
    assoc, office, listing = ctx["assoc"], ctx["office"], ctx["listing"]
    withdrawn = change_status(assoc["id"], office["id"], listing, "WITHDRAWN",
                              current_business_time(api))
    assert withdrawn["status"] == "WITHDRAWN"
    reactivated = activate_listing(assoc["id"], office["id"], listing)
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["policy_revision_id"] == ctx["revision"]["id"], \
        "no newer revision exists, so the same revision governs reactivation"


def current_business_time(api):
    return get_success_data(api.advance_day(STAFF, days=0))["now_iso8601"]


def _setup_three_paid_strikes(api):
    """Association with violator MV carrying three paid citations
    (strikes_12m == 3) plus a fourth citation with a hearing held."""
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="NL2", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    violator = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    p1 = create_member(assoc["id"], member_nr="P1", full_name="Panel One")
    p2 = create_member(assoc["id"], member_nr="P2", full_name="Panel Two")
    office = create_office(assoc["id"], broker["id"], office_code="O1")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    activate_policy_revision(assoc["id"], assoc["version"], revision_code="R1",
                             effective_at="2026-09-01T00:00:00Z",
                             activate_now="2026-09-02T00:00:00Z")
    listing = create_listing(assoc["id"], office["id"], broker["id"],
                             mls_number="MLS-B1")
    activate_listing(assoc["id"], office["id"], listing)
    for _ in range(3):
        from test_helpers import issue_and_pay_citation
        issue_and_pay_citation(assoc["id"], violator["id"], rule_code="INACCURACY")
    member = get_success_data(api.get_member(assoc["id"], violator["id"], STAFF))
    assert member["strikes_12m"] == 3, f"setup: expected 3 strikes, got {member['strikes_12m']}"
    hearing = setup_citation_hearing_held(
        assoc["id"], violator["id"],
        [broker["id"], p1["id"], p2["id"]],
        rule_code="INACCURACY", listing_id=listing["id"])
    return {"assoc": assoc, "broker": broker, "violator": violator,
            "listing": listing, "hearing": hearing}


def test_citation_hearing_branching_escalation_fork(api):
    """PRD §3.5: "if the panel upholds, the branch depends on the member's live `strikes_12m` at the ruling instant — below 3 strikes the citation transitions to `PAID` with the same credit accrual (cap check included; on overflow the ruling itself is rejected with `ERR_CREDIT_CAP_EXCEEDED` and the citation stays `HEARING_PENDING`), strikes recompute, and unflag chain as a direct payment, while at 3 or more strikes the citation transitions to `ESCALATED` instead, no credit accrues, and the case is marked as handed off to the association's professional-standards process — no ethics case is auto-created."

    Design: Difficulty/non_linear_state_machine/citation_hearing_branching_escalation_fork
    """
    ctx = _setup_three_paid_strikes(api)
    assoc, violator, hearing = ctx["assoc"], ctx["violator"], ctx["hearing"]
    balance_before = get_success_data(
        api.get_member(assoc["id"], violator["id"], STAFF))["sanction_credit_balance_cents"]
    get_success_data(api.rule_panel(
        assoc["id"], hearing["panel"]["id"], "UPHOLD",
        make_panelist_headers(hearing["ruler_id"])))
    citation = get_success_data(
        api.get_citation(assoc["id"], hearing["citation"]["id"], STAFF))
    assert citation["status"] == "ESCALATED", \
        "UPHOLD with live strikes_12m == 3 routes to ESCALATED, not PAID"
    member = get_success_data(api.get_member(assoc["id"], violator["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == balance_before == 90000, \
        "ESCALATED accrues no credit; balance stays at 3 x 30000"


def test_citation_hearing_uphold_below_three_strikes_pays(api):
    """PRD §3.5: "below 3 strikes the citation transitions to `PAID` with the
    same credit accrual (cap check included; on overflow the ruling itself is
    rejected with `ERR_CREDIT_CAP_EXCEEDED` and the citation stays
    `HEARING_PENDING`), strikes recompute, and unflag chain as a direct
    payment, while at 3 or more strikes the citation transitions to
    `ESCALATED` instead".

    Design: Difficulty/non_linear_state_machine/citation_hearing_branching_escalation_fork
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="NL3", sanction_credit_cap_cents=200000)
    broker = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    violator = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    p1 = create_member(assoc["id"], member_nr="P1", full_name="Panel One")
    p2 = create_member(assoc["id"], member_nr="P2", full_name="Panel Two")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    hearing = setup_citation_hearing_held(
        assoc["id"], violator["id"],
        [broker["id"], p1["id"], p2["id"]],
        rule_code="INACCURACY")
    get_success_data(api.rule_panel(
        assoc["id"], hearing["panel"]["id"], "UPHOLD",
        make_panelist_headers(hearing["ruler_id"])))
    citation = get_success_data(
        api.get_citation(assoc["id"], hearing["citation"]["id"], STAFF))
    assert citation["status"] == "PAID", \
        "UPHOLD with live strikes_12m < 3 transitions to PAID"
    member = get_success_data(api.get_member(assoc["id"], violator["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 30000
    assert member["strikes_12m"] == 1
