"""The holding decision chain, terminal lockdown, and the access-control rules.

The propose/approve separation is what makes the sale chain a loop rather than a
one-way door, and the terminal states of the offering machine are genuinely
closed. The credential and role rules are pinned by the same request being
distinguishable only by its error identifier.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_investor_headers, make_issuer_ops_headers,
    TEST_USERS, BLANK_ROLE_HEADERS, NO_HEADERS, NON_EXISTENT_UUID,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, create_insurance_policy, create_holding_decision_payload,
    file_appraisal, file_verified_authentication, file_verified_provenance,
    file_circular, allocate_offering, create_custody_record, receive_custody,
    bind_policy, get_offering, get_artwork, offering_version,
    setup_filed_offering, setup_held_offering, setup_held_offering_with_policy,
    setup_closed_offering_with_distribution, approve_decision, reject_decision,
)

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
PROPOSER = "ops-desk-11"
APPROVER = "ops-desk-12"
OFFICER = "officer-reyes"


def _raise_sell_decision(offering_id, proposed_gross_cents=120_000_000):
    return validate_success(api_client.create_holding_decision(
        offering_id,
        create_holding_decision_payload(decision_type="SELL",
                                        proposed_gross_cents=proposed_gross_cents),
        make_issuer_ops_headers(PROPOSER)), 201)


# ── The revision round ───────────────────────────────────────────────────────

def test_approve_reject_revise_round_returns_the_decision_to_pending(api):
    """PRD 3.8: "A rejected decision is not necessarily dead: the operations desk may
    revise it by supplying a new `proposed_gross_cents`, which returns it to `PENDING`
    and replaces the proposed figure, leaving the offering in `ALLOCATED`. That closes
    the loop by which a proposal can be approved, overturned, revised, and approved
    again."

    Design: Difficulty/non_linear_state_machine/holding_decision_revision_round_cycles_back_to_pending
    """
    artwork, offering, investor, sub, custody = setup_held_offering()
    set_clock("2027-06-30T00:00:00Z")

    decision = _raise_sell_decision(offering["id"])
    validate_success(approve_decision(decision["id"], offering["id"],
                                      as_user_id=APPROVER), 200)
    assert get_offering(offering["id"])["status"] == "SALE_PENDING"

    validate_success(reject_decision(decision["id"], offering["id"],
                                     as_user_id=OFFICER), 200)
    assert get_offering(offering["id"])["status"] == "ALLOCATED"

    revised = validate_success(api_client.revise_decision(
        decision["id"], {"proposed_gross_cents": 130_000_000},
        make_issuer_ops_headers(PROPOSER)), 200)
    assert revised["status"] == "PENDING"
    assert revised["proposed_gross_cents"] == 130_000_000
    assert get_offering(offering["id"])["status"] == "ALLOCATED"


def test_the_revision_loop_can_be_traversed_more_than_once(api):
    """PRD 3.8: "A `HOLD` decision ... cycles the offering back to `ALLOCATED`" and PRD
    3.8: "That closes the loop by which a proposal can be approved, overturned, revised,
    and approved again."

    Design: Difficulty/non_linear_state_machine/holding_decision_revision_round_cycles_back_to_pending
    """
    artwork, offering, investor, sub, custody = setup_held_offering()
    set_clock("2027-06-30T00:00:00Z")
    decision = _raise_sell_decision(offering["id"])
    validate_success(approve_decision(decision["id"], offering["id"],
                                      as_user_id=APPROVER), 200)
    validate_success(reject_decision(decision["id"], offering["id"],
                                     as_user_id=OFFICER), 200)
    validate_success(api_client.revise_decision(
        decision["id"], {"proposed_gross_cents": 130_000_000},
        make_issuer_ops_headers(PROPOSER)), 200)

    # Re-approving at the same clock succeeds, proving the loop is traversable
    # more than once.
    reapproved = validate_success(approve_decision(
        decision["id"], offering["id"], as_user_id=APPROVER), 200)
    assert reapproved["status"] == "APPROVED"
    assert get_offering(offering["id"])["status"] == "SALE_PENDING"


def test_re_approval_is_refused_when_the_officer_proposed_the_decision(api):
    """PRD 3.8: "the acting officer's `X-User-ID` must differ from the
    `created_by_user_id` recorded when the decision was raised. That last rule is the
    propose/approve separation: the desk that raises a sale may not also approve it."

    Design: Difficulty/non_linear_state_machine/holding_decision_revision_round_cycles_back_to_pending
    """
    artwork, offering, investor, sub, custody = setup_held_offering()
    set_clock("2027-06-30T00:00:00Z")
    decision = _raise_sell_decision(offering["id"])
    validate_success(approve_decision(decision["id"], offering["id"],
                                      as_user_id=APPROVER), 200)
    validate_success(reject_decision(decision["id"], offering["id"],
                                     as_user_id=OFFICER), 200)
    validate_success(api_client.revise_decision(
        decision["id"], {"proposed_gross_cents": 130_000_000},
        make_issuer_ops_headers(PROPOSER)), 200)

    res = approve_decision(decision["id"], offering["id"], as_user_id=PROPOSER)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert validate_success(
        api_client.get_holding_decision(decision["id"], ISSUER), 200)["status"] == "PENDING"


# ── Idempotency of approval ──────────────────────────────────────────────────

def test_approving_an_already_approved_decision_is_refused(api):
    """PRD 3.8: "It requires `decision_type` to be `SELL` with the decision still
    `PENDING`".

    Design: Corner/state_machines/approving_the_same_holding_decision_twice_returns_invalid_state
    """
    artwork, offering, investor, sub, custody = setup_held_offering()
    set_clock("2027-06-30T00:00:00Z")
    decision = _raise_sell_decision(offering["id"])
    validate_success(approve_decision(decision["id"], offering["id"],
                                      as_user_id=APPROVER), 200)

    res = approve_decision(decision["id"], offering["id"], as_user_id=APPROVER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_a_second_approval_does_not_double_advance_the_offering(api):
    """PRD 3.8: "Approval sets the decision to `APPROVED`, moves the offering to
    `SALE_PENDING`, and moves the artwork to `SALE_PENDING` with it."  A refused second
    approval must not repeat that side effect.

    Design: Corner/state_machines/approving_the_same_holding_decision_twice_returns_invalid_state
    """
    artwork, offering, investor, sub, custody = setup_held_offering()
    set_clock("2027-06-30T00:00:00Z")
    decision = _raise_sell_decision(offering["id"])
    validate_success(approve_decision(decision["id"], offering["id"],
                                      as_user_id=APPROVER), 200)
    version_after_first = offering_version(offering["id"])

    approve_decision(decision["id"], offering["id"], as_user_id=APPROVER)

    assert validate_success(
        api_client.get_holding_decision(decision["id"], ISSUER), 200)["status"] == "APPROVED"
    assert get_offering(offering["id"])["status"] == "SALE_PENDING"
    assert offering_version(offering["id"]) == version_after_first


# ── Terminal lockdown ────────────────────────────────────────────────────────

def test_a_closed_offering_refuses_a_further_holding_decision(api):
    """PRD 3.8: "the offering reaches terminal `CLOSED`, the artwork reaches terminal
    `SOLD`, and a `Distribution` is created against the offering in status
    `CALCULATED`."

    Design: Corner/state_machines/closed_offering_is_locked_against_a_second_holding_decision
    """
    artwork, offering, decision, distribution, account = setup_closed_offering_with_distribution()
    assert offering["status"] == "CLOSED"

    res = api_client.create_holding_decision(
        offering["id"], {"decision_type": "HOLD"}, ISSUER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_the_refused_decision_on_a_closed_offering_creates_nothing(api):
    """PRD 3.8: "the offering reaches terminal `CLOSED`, the artwork reaches terminal
    `SOLD`" — a terminal state has no outgoing transition, so the refused request must
    leave the decision list untouched.

    Design: Corner/state_machines/closed_offering_is_locked_against_a_second_holding_decision
    """
    artwork, offering, decision, distribution, account = setup_closed_offering_with_distribution()
    api_client.create_holding_decision(offering["id"], {"decision_type": "HOLD"}, ISSUER)

    assert get_offering(offering["id"])["status"] == "CLOSED"
    assert get_artwork(artwork["id"])["status"] == "SOLD"
    decisions = get_success_data(
        api_client.list_holding_decisions(offering["id"], ISSUER))
    assert len(decisions) == 1
    assert decisions[0]["id"] == decision["id"]


# ── Credential presence ──────────────────────────────────────────────────────

def test_a_blank_role_header_is_rejected_as_unauthenticated(api):
    """PRD 2.1: "A request that arrives without either header, or with a blank value for
    either, is refused with `ERR_UNAUTHENTICATED` and HTTP 401."

    Design: Corner/errors/a_blank_role_header_is_rejected_as_unauthenticated_not_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.create_artwork({
        "title": "Untitled Probe", "artist_id": NON_EXISTENT_UUID,
        "creation_year": 1970, "medium": "PAINTING",
        "acquisition_cost_cents": 1_000_000, "reserve_price_cents": 2_000_000,
    }, BLANK_ROLE_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_a_missing_credential_pair_is_rejected_as_unauthenticated(api):
    """PRD 2.4: "1. Credential presence — both `X-User-ID` and `X-User-Role` supplied
    and non-blank. Failure: `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/a_blank_role_header_is_rejected_as_unauthenticated_not_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    res = api_client.create_artist(
        {"legal_name": "Probe", "attribution_status": "CONFIRMED",
         "nationality_country_code": "US"}, NO_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
    assert get_success_data(api_client.list_artists(ISSUER)) == []


# ── Role boundary: the holder may not bind ───────────────────────────────────

def test_an_investor_cannot_bind_an_insurance_policy(api):
    """PRD 2.1: "A well-formed request whose acting role is not permitted for the
    operation produces `ERR_UNAUTHORIZED` (HTTP 403), and that permission failure is
    reported before any business check is evaluated."

    Design: Corner/errors/a_holder_role_cannot_bind_an_insurance_policy
    """
    set_clock("2026-08-01T00:00:00Z")
    artwork = _authenticated_work_with_appraisal()
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=5_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investor = create_investor(email="investor@x.com", legal_name="Talia Bruun")
    create_screened_subscription(offering["id"], investor["id"], requested_shares=8000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)
    custody = create_custody_record(offering["id"])
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)
    policy = create_insurance_policy(offering["id"], coverage_cents=90_000_000)

    res = api_client.bind_policy(policy["id"], {}, make_investor_headers(investor["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
    assert validate_success(
        api_client.get_insurance_policy(policy["id"], ISSUER), 200)["status"] == "PENDING"


def test_the_same_bind_succeeds_for_the_operations_desk(api):
    """PRD 2.1: "`IssuerOps` is the issuer's operations desk — acquisition, asset
    reports, appraisals, offering creation, custody administration, insurance, cost
    lots, fee accrual, and the propose step of the sale decision chain."

    Design: Corner/errors/a_holder_role_cannot_bind_an_insurance_policy
    """
    set_clock("2026-08-01T00:00:00Z")
    artwork = _authenticated_work_with_appraisal()
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=5_000,
                               liquidity_ratio_bps=1_000, hold_period_days=176)
    investor = create_investor(email="investor2@x.com", legal_name="Talia Bruun")
    create_screened_subscription(offering["id"], investor["id"], requested_shares=8000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)
    custody = create_custody_record(offering["id"])
    set_clock("2027-01-05T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)
    policy = create_insurance_policy(offering["id"], coverage_cents=90_000_000)

    validate_success(bind_policy(policy["id"]), 200)
    assert validate_success(
        api_client.get_insurance_policy(policy["id"], ISSUER), 200)["status"] == "FORCE"


# ── Role boundary: screening is the officer's act ────────────────────────────

def test_an_investor_cannot_screen_its_own_subscription(api):
    """PRD 2.1: "`ComplianceOfficer` owns investor protection: screening, suitability
    revocation, qualification filing, allocation, waitlist movement, offering
    abandonment and withdrawal".

    Design: Corner/rbac/an_investor_cannot_screen_its_own_subscription
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor(email="selfscreen@x.com", legal_name="Boris Kalema")
    sub = get_success_data(api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": investor["id"],
         "requested_shares": 500},
        make_investor_headers(investor["id"])))

    res = api_client.screen_subscription(sub["id"], {"outcome": "VERIFIED"},
                                         make_investor_headers(investor["id"]))
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_the_screen_succeeds_for_the_compliance_officer(api):
    """PRD 3.4: "A `VERIFIED` outcome on a received subscription is the ordinary route
    to admission" and PRD 2.8: "A successful screen sets `suitability_status` to
    `APPROVED`".

    Design: Corner/rbac/an_investor_cannot_screen_its_own_subscription
    """
    set_clock("2026-09-01T00:00:00Z")
    artwork, offering = setup_filed_offering(start_clock="2026-09-01T00:00:00Z")
    investor = create_investor(email="selfscreen2@x.com", legal_name="Boris Kalema")
    sub = get_success_data(api_client.create_subscription(
        {"offering_id": offering["id"], "investor_id": investor["id"],
         "requested_shares": 500},
        make_investor_headers(investor["id"])))

    validate_success(api_client.screen_subscription(
        sub["id"], {"outcome": "VERIFIED"}, COMPLIANCE), 200)

    after = validate_success(api_client.get_subscription(sub["id"], COMPLIANCE), 200)
    assert after["status"] == "SUBSCRIBED"
    inv = validate_success(api_client.get_investor(investor["id"], ISSUER), 200)
    assert inv["suitability_status"] == "APPROVED"


# ── The identity the Investor role carries ───────────────────────────────────

def test_the_investor_role_acts_as_its_own_entity_row(api):
    """PRD 2.1: "When `X-User-Role` is `Investor`, `X-User-ID` is the `id` of the
    acting `Investor` row itself."

    Design: Corner/rbac/role_identity_map_pins_the_investor_role_to_the_investor_entity
    """
    set_clock("2026-09-01T00:00:00Z")
    investor = create_investor(email="identity@x.com", legal_name="Sofia Marchesi")

    res = api_client.get_investor(investor["id"], make_investor_headers(investor["id"]))
    validate_success(res, 200)


def test_an_opaque_role_identity_is_never_compared_to_an_entity_row(api):
    """PRD 2.1: "For every other role the identity is opaque ... but never compares it
    to any entity's `id`."

    Design: Corner/rbac/role_identity_map_pins_the_investor_role_to_the_investor_entity
    """
    set_clock("2026-09-01T00:00:00Z")
    investor = create_investor(email="identity2@x.com", legal_name="Sofia Marchesi")

    # An opaque operator identity that resolves to no row is still accepted.
    rows = validate_success(api_client.list_investors(ISSUER), 200)
    assert isinstance(rows, list)
    assert any(row["id"] == investor["id"] for row in rows)


def test_an_investor_identity_that_resolves_to_no_row_is_refused_on_read(api):
    """PRD 2.4: "4. Existence — every path identifier and every body identifier resolves
    to a stored row of the expected entity type. Failure: `ERR_NOT_FOUND`."

    Design: Corner/rbac/role_identity_map_pins_the_investor_role_to_the_investor_entity
    """
    set_clock("2026-09-01T00:00:00Z")
    create_investor(email="identity3@x.com", legal_name="Sofia Marchesi")

    res = api_client.get_investor(NON_EXISTENT_UUID,
                                  make_investor_headers(NON_EXISTENT_UUID))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ── helpers ──────────────────────────────────────────────────────────────────

def _authenticated_work_with_appraisal():
    artist = create_artist(legal_name="Ines Calderon", attribution_status="CONFIRMED",
                           nationality_country_code="ES")
    artwork = create_artwork(artist["id"], title="Cuadro Rojo", creation_year=1963,
                             acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    return get_artwork(artwork["id"])