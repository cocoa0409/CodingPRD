"""State machine lifecycle rules: terminal lockdown, double-action rejection,
broker suspension/reinstatement cascade, initial states, and the 20-day
hearing-request window boundary."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_association, create_member, create_office, create_listing,
    create_fine_schedule, create_dues_period, bill_dues_period, set_clock,
    activate_policy_revision, activate_listing,
    create_citation, pay_citation, get_member_invoice, pay_invoice,
    make_member_headers, make_panelist_headers, TEST_USERS, api_client,
)

STAFF = TEST_USERS["staff_headers"]


def test_citation_pay_twice_returns_invalid_state(api):
    """PRD §3.5: "a second request once `hearing_requested` is already true —
    like any action attempted on an entity that is not in a legal source state
    for it, such as paying an already-`PAID` citation or invoice, or ruling on
    an already-`DECIDED` panel — is rejected with `ERR_INVALID_STATE`."
    PRD §3.5: "A successful payment transitions the citation `OPEN` → `PAID`,
    credits the full `fine_amount_cents` to the member's balance".

    Design: Corner/state_machines/citation_pay_twice_returns_invalid_state
    """
    assoc = create_association(association_code="S1", sanction_credit_cap_cents=200000)
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    cit = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    validate_success(api.pay_citation(
        assoc["id"], cit["id"], 30000, make_member_headers(mv["id"])))
    resp = api.pay_citation(
        assoc["id"], cit["id"], 30000, make_member_headers(mv["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    member = get_success_data(api.get_member(assoc["id"], mv["id"], STAFF))
    assert member["sanction_credit_balance_cents"] == 30000, "no double accrual"


def test_terminated_member_is_terminal_no_reinstatement(api):
    """PRD §3.2: "A member who has been `SUSPENDED` for at least 90 consecutive days — measured from the `grace_end_date` of the dues period whose lapse triggered the suspension — may be terminated by staff. Termination transitions the member to `TERMINATED`, keeps `mls_access_state` at `DISABLED`".
    PRD §3.5: "a second request once `hearing_requested` is already true — like any action attempted on an entity that is not in a legal source state for it, such as paying an already-`PAID` citation or invoice, or ruling on an already-`DECIDED` panel — is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminated_member_is_terminal_no_reinstatement
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="S2")
    mt = create_member(assoc["id"], member_nr="MT", full_name="Term")
    period = create_dues_period(
        assoc["id"], year=2026, period_start_date="2026-09-01T00:00:00Z",
        due_date="2026-09-05T00:00:00Z", grace_end_date="2026-09-10T00:00:00Z",
        amount_cents=100000)
    bill_dues_period(assoc["id"], period)
    set_clock("2026-09-11T00:00:00Z")
    validate_success(api.reconcile_dues_period(assoc["id"], period["id"], STAFF))
    set_clock("2026-12-15T00:00:00Z")
    terminated = validate_success(
        api.terminate_member(assoc["id"], mt["id"], STAFF))
    assert terminated["membership_state"] == "TERMINATED"
    resp = api.terminate_member(assoc["id"], mt["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_office_broker_suspension_cascades_and_reinstatement_restores(api):
    """PRD §3.1: "Offices and their brokers are coupled through suspension: when the member named by an office's `broker_member_id` transitions from `ACTIVE` to `SUSPENDED`, the office transitions to `SUSPENDED` as well, and while the office is suspended all of its listings are blocked from activation. When that broker is reinstated from `SUSPENDED` to `ACTIVE`, the office returns to `ACTIVE`."

    Design: Corner/state_machines/office_broker_suspension_cascades_and_reinstatement_restores
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="S3")
    mb = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    ma = create_member(assoc["id"], member_nr="MA", full_name="Agent")
    office = create_office(assoc["id"], mb["id"], office_code="O1")
    period = create_dues_period(
        assoc["id"], year=2026, period_start_date="2026-09-01T00:00:00Z",
        due_date="2026-09-05T00:00:00Z", grace_end_date="2026-09-10T00:00:00Z",
        amount_cents=100000)
    bill_dues_period(assoc["id"], period)
    set_clock("2026-09-11T00:00:00Z")
    validate_success(api.reconcile_dues_period(assoc["id"], period["id"], STAFF))
    # Both members suspended; office suspended via broker link.
    office_now = get_success_data(api.get_office(assoc["id"], office["id"], STAFF))
    assert office_now["status"] == "SUSPENDED"
    # Paying the non-broker agent's invoice leaves the office suspended.
    ma_invoice = get_member_invoice(assoc["id"], period["id"], ma["id"])
    pay_invoice(assoc["id"], ma_invoice)
    office_mid = get_success_data(api.get_office(assoc["id"], office["id"], STAFF))
    assert office_mid["status"] == "SUSPENDED"
    # Paying the broker's invoice restores member AND office.
    mb_invoice = get_member_invoice(assoc["id"], period["id"], mb["id"])
    pay_invoice(assoc["id"], mb_invoice)
    office_end = get_success_data(api.get_office(assoc["id"], office["id"], STAFF))
    assert office_end["status"] == "ACTIVE"
    mb_now = get_success_data(api.get_member(assoc["id"], mb["id"], STAFF))
    assert mb_now["membership_state"] == "ACTIVE"
    assert mb_now["mls_access_state"] == "ENABLED"


def test_initial_states_on_create(api):
    """PRD §3.3: "The listing is created in status `DRAFT` with
    `accuracy_flag` `CLEAN`."
    PRD §3.9: "A license opens in status `PENDING` with `feed_sync_state`
    `STALE`."
    PRD §3.8: "otherwise the first three, in ranked order, become the panel's
    `selected_member_ids`, and `convene_at` stamps the selection snapshot."

    Design: Corner/state_machines/initial_states_on_create
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="S4")
    mb = create_member(assoc["id"], member_nr="MB", full_name="Broker")
    for i in range(3):
        create_member(assoc["id"], member_nr=f"P{i+1}", full_name=f"P{i+1}")
    office = create_office(assoc["id"], mb["id"], office_code="O1")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    listing = create_listing(assoc["id"], office["id"], mb["id"], mls_number="MLS-S4")
    assert listing["status"] == "DRAFT"
    assert listing["accuracy_flag"] == "CLEAN"
    lic = get_success_data(api.create_data_license(
        assoc["id"],
        {"licensee_name": "InitPortal", "scope": "IDX", "display_ruleset_version": 0,
         "listing_field_allowlist": ["property_address"]},
        STAFF))
    assert lic["status"] == "PENDING"
    assert lic["feed_sync_state"] == "STALE"
    cit = create_citation(assoc["id"], mb["id"], rule_code="INACCURACY")
    validate_success(api.request_hearing(
        assoc["id"], cit["id"], make_member_headers(mb["id"])))
    panel = get_success_data(api.convene_hearing_panel(
        assoc["id"], "CITATION", cit["id"], STAFF))
    assert panel["status"] == "CONVENED"
    assert len(panel["selected_member_ids"]) == 3


def test_hearing_window_boundary_day20_allowed_day21_rejected(api):
    """PRD §3.5: "The cited member may request a hearing within 20 days of the
    citation's `assessed_at`; a request after that window is rejected with
    `ERR_HEARING_WINDOW_CLOSED`".
    PRD §3.5: "Requesting a hearing transitions the citation `OPEN` →
    `HEARING_PENDING` and sets `hearing_requested` to true."

    Design: Corner/state_machines/hearing_window_boundary_day20_allowed_day21_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    assoc = create_association(association_code="S5")
    mv = create_member(assoc["id"], member_nr="MV", full_name="Violator")
    create_fine_schedule(assoc["id"], rule_code="INACCURACY", fine_amount_cents=30000)
    set_clock("2026-09-02T00:00:00Z")
    ca = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    cb = create_citation(assoc["id"], mv["id"], rule_code="INACCURACY")
    # Day 20 after assessment (inclusive boundary) succeeds.
    set_clock("2026-09-22T00:00:00Z")
    heard = validate_success(api.request_hearing(
        assoc["id"], ca["id"], make_member_headers(mv["id"])))
    assert heard["status"] == "HEARING_PENDING"
    assert heard["hearing_requested"] is True
    # Day 21 is rejected.
    set_clock("2026-09-23T00:00:00Z")
    resp = api.request_hearing(assoc["id"], cb["id"], make_member_headers(mv["id"]))
    validate_error(resp, ApiErrorId.ERR_HEARING_WINDOW_CLOSED)
