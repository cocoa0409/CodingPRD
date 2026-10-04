"""NamedUser lifecycle: seat ledger conservation, invalid transitions,
terminal lockdown, deactivation blockers, and state-vs-capacity precedence."""
from test_helpers import (
    ApiErrorId,
    get_grant,
    get_org_version,
    get_success_data,
    get_user,
    make_named_user_headers,
    setup_base_chain,
    setup_with_user,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    accept_user,
    activate_grant,
    activate_org,
    create_published_item,
    invite_user,
    publish_item,
    set_clock,
    setup_grant,
    setup_org,
    setup_product,
)
from test_helpers.factories import create_credit_pool_payload
from test_helpers.test_users import TEST_USERS

BA_HEADERS = TEST_USERS["billing_admin_headers"]
LA_HEADERS = TEST_USERS["license_admin_headers"]


def _user_transition(api, user_id, target, headers):
    return api.transition_named_user(user_id, {"target_status": target}, headers)


def test_seat_consume_release_cycle_conserves_seats(api):
    """PRD section 3.6: "Acceptance consumes a seat: the home grant's
    `seats_in_use` is incremented by 1".
    PRD section 3.6: "Disable releases the seat (the home grant's
    `seats_in_use` decrements by 1)".
    PRD section 3.6: "Re-enabling moves a user from `DISABLED` back to
    `ACTIVE` at a `LicenseAdmin`'s request. The user must be `DISABLED` (else
    `ERR_USER_NOT_DISABLED`), the organization must be `ACTIVE`, and the home
    grant must be `ACTIVE`. Capacity is then kind-dependent: when the home
    grant is `NAMED_USER`-kind, a free seat is required (else
    `ERR_NO_SEATS_AVAILABLE`) — a hard cap."
    PRD section 3.6: "Deactivation releases the seat and revokes the user's
    API keys."

    Design: Difficulty/compensating_invariant/seat_consume_release_cycle_conserves_seats
    """
    base = setup_base_chain(grant_overrides={"seats_allocated": 2})
    org_id, grant_id = base["org"]["id"], base["grant"]["id"]
    user = invite_user(org_id, grant_id)

    get_success_data(_user_transition(api, user["id"], "ACTIVE", make_named_user_headers(user["id"])))
    assert get_grant(grant_id)["seats_in_use"] == 1

    get_success_data(_user_transition(api, user["id"], "DISABLED", LA_HEADERS))
    assert get_grant(grant_id)["seats_in_use"] == 0

    get_success_data(_user_transition(api, user["id"], "ACTIVE", LA_HEADERS))
    assert get_grant(grant_id)["seats_in_use"] == 1

    get_success_data(_user_transition(api, user["id"], "DEACTIVATED", LA_HEADERS))
    assert get_grant(grant_id)["seats_in_use"] == 0
    assert get_user(user["id"])["status"] == "DEACTIVATED"


def test_seat_ledger_independent_per_user(api):
    """PRD section 3.6: "Acceptance consumes a seat: the home grant's
    `seats_in_use` is incremented by 1, keeping the seat ledger synchronized
    with reality."
    PRD section 3.6: "Disable releases the seat (the home grant's
    `seats_in_use` decrements by 1)".

    Design: Difficulty/compensating_invariant/seat_consume_release_cycle_conserves_seats
    """
    base = setup_base_chain(grant_overrides={"seats_allocated": 3})
    org_id, grant_id = base["org"]["id"], base["grant"]["id"]
    u1 = accept_user(invite_user(org_id, grant_id, username="u1", email="u1@m.example")["id"])
    u2 = accept_user(invite_user(org_id, grant_id, username="u2", email="u2@m.example")["id"])
    assert get_grant(grant_id)["seats_in_use"] == 2
    get_success_data(_user_transition(api, u1["id"], "DISABLED", LA_HEADERS))
    assert get_grant(grant_id)["seats_in_use"] == 1


def test_user_disable_from_invited_rejected(api):
    """PRD section 3.6: "Disabling moves a user from `ACTIVE` to `DISABLED`,
    either at a `LicenseAdmin`'s request or through an organization suspension
    cascade; the user must be `ACTIVE` (else `ERR_USER_NOT_ACTIVE`)."

    Design: Corner/state_machines/user_disable_from_invited_rejected
    """
    base = setup_base_chain()
    user = invite_user(base["org"]["id"], base["grant"]["id"])
    resp = _user_transition(api, user["id"], "DISABLED", LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_USER_NOT_ACTIVE)
    assert get_grant(base["grant"]["id"])["seats_in_use"] == 0


def test_user_disable_from_invited_leaves_status(api):
    """PRD section 3.6: "Disabling moves a user from `ACTIVE` to `DISABLED`"
    and "The new user record starts in `INVITED` status."

    Design: Corner/state_machines/user_disable_from_invited_rejected
    """
    base = setup_base_chain()
    user = invite_user(base["org"]["id"], base["grant"]["id"])
    _user_transition(api, user["id"], "DISABLED", LA_HEADERS)
    assert get_user(user["id"])["status"] == "INVITED"


def test_deactivated_user_rejects_all_transitions(api):
    """PRD section 3.6: "Deactivation moves a user from `ACTIVE` to the
    terminal state `DEACTIVATED` at a `LicenseAdmin`'s request."
    PRD section 3.6: "Re-enabling moves a user from `DISABLED` back to
    `ACTIVE` at a `LicenseAdmin`'s request. The user must be `DISABLED` (else
    `ERR_USER_NOT_DISABLED`)".

    Design: Corner/state_machines/terminal_deactivated_user_rejects_all_transitions
    """
    base = setup_with_user()
    user = base["user"]
    get_success_data(_user_transition(api, user["id"], "DEACTIVATED", LA_HEADERS))

    resp = _user_transition(api, user["id"], "ACTIVE", LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_USER_NOT_DISABLED)
    resp = _user_transition(api, user["id"], "DISABLED", LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_USER_NOT_ACTIVE)
    assert get_user(user["id"])["status"] == "DEACTIVATED"


def test_deactivated_user_stays_terminal(api):
    """PRD section 3.6: "Deactivation moves a user from `ACTIVE` to the
    terminal state `DEACTIVATED`".

    Design: Corner/state_machines/terminal_deactivated_user_rejects_all_transitions
    """
    base = setup_with_user()
    user = base["user"]
    get_success_data(_user_transition(api, user["id"], "DEACTIVATED", LA_HEADERS))
    _user_transition(api, user["id"], "ACTIVE", LA_HEADERS)
    _user_transition(api, user["id"], "DISABLED", LA_HEADERS)
    _user_transition(api, user["id"], "DEACTIVATED", LA_HEADERS)
    assert get_user(user["id"])["status"] == "DEACTIVATED"


def test_deactivate_user_blocked_by_published_item(api):
    """PRD section 3.6: "The user must be `ACTIVE`, and the user must not own
    any ContentItem in `PUBLISHED` or `FLAGGED` status (else
    `ERR_USER_OWNS_PUBLISHED_CONTENT`) — published content must be retracted
    or rehomed first."

    Design: Corner/validations/deactivate_user_blocked_by_published_item
    """
    base = setup_with_user()
    user = base["user"]
    item = create_published_item(base["org"]["id"], user["id"], title="Blocker",
                                 item_kind="WEB_MAP")
    resp = _user_transition(api, user["id"], "DEACTIVATED", LA_HEADERS)
    validate_error(resp, ApiErrorId.ERR_USER_OWNS_PUBLISHED_CONTENT)

    get_success_data(api.transition_content_item(
        item["id"], {"target_status": "RETRACTED"}, make_named_user_headers(user["id"])))
    data = get_success_data(_user_transition(api, user["id"], "DEACTIVATED", LA_HEADERS))
    assert data["status"] == "DEACTIVATED"
    assert get_grant(base["grant"]["id"])["seats_in_use"] == 0


def test_deactivate_user_with_only_draft_items_succeeds(api):
    """PRD section 3.6: "the user must not own any ContentItem in `PUBLISHED`
    or `FLAGGED` status (else `ERR_USER_OWNS_PUBLISHED_CONTENT`)".

    Design: Corner/validations/deactivate_user_blocked_by_published_item
    """
    from test_helpers.fixtures import create_draft_item
    base = setup_with_user()
    user = base["user"]
    create_draft_item(base["org"]["id"], user["id"], title="Draft", item_kind="WEB_MAP")
    data = get_success_data(_user_transition(api, user["id"], "DEACTIVATED", LA_HEADERS))
    assert data["status"] == "DEACTIVATED"


def test_grant_state_check_precedes_seat_capacity_on_accept(api):
    """PRD section 2.10: "**State legality (priority 6).** The target entity
    must be in a state from which the requested transition exists — else the
    transition-specific state error."
    PRD section 2.10: "**Business rules (priorities 7 through 29).** Identity
    and ownership checks, kind matching, grant windows, eligibility gating,
    segregation of duties, extension constraints, sharing-step legality,
    public-sharing gates, publish gates, capacity caps, credit sufficiency,
    posture gates, upgrade rules, idempotency, revoke and terminate blockers,
    portal protection, evidence and rationale requirements, API-key service
    scoping, extension applicability, org-activation prerequisites, and
    uniqueness — each described in §3 alongside the workflow it guards, each
    with its own error code, and each applied in this priority order when
    several rules attach to the same endpoint."
    PRD section 3.6: "The user must currently be `INVITED`
    (`ERR_USER_NOT_INVITED`), the parent organization must be `ACTIVE`
    (`ERR_ORG_NOT_ACTIVE`), the home grant must be `ACTIVE`
    (`ERR_GRANT_NOT_ACTIVE`), and the home grant must have a free seat — its
    `seats_in_use` strictly less than its `seats_allocated`
    (`ERR_NO_SEATS_AVAILABLE`)."

    Design: Difficulty/priority_pair_validation_conflict/eligibility_gate_beats_seat_capacity_on_user_accept
    """
    base = setup_base_chain(grant_overrides={"seats_allocated": 1})
    org_id, grant_id = base["org"]["id"], base["grant"]["id"]
    bob = invite_user(org_id, grant_id, username="bob", email="bob@meridian.example", level="VIEWER")
    # Suspend the grant (state check will fire; seats_in_use forced to 0 so the
    # capacity check alone would have passed).
    resp = api.transition_license_grant(
        grant_id,
        {"target_status": "SUSPENDED", "expected_organization_version": get_org_version(org_id)},
        LA_HEADERS)
    get_success_data(resp)
    resp = _user_transition(api, bob["id"], "ACTIVE", make_named_user_headers(bob["id"]))
    validate_error(resp, ApiErrorId.ERR_GRANT_NOT_ACTIVE)
    assert get_user(bob["id"])["status"] == "INVITED"


def test_accept_onto_full_named_grant_rejected_no_seats(api):
    """PRD section 3.6: "the home grant must have a free seat — its
    `seats_in_use` strictly less than its `seats_allocated`
    (`ERR_NO_SEATS_AVAILABLE`)".

    Design: Difficulty/priority_pair_validation_conflict/eligibility_gate_beats_seat_capacity_on_user_accept
    """
    base = setup_base_chain(grant_overrides={"seats_allocated": 1})
    org_id, grant_id = base["org"]["id"], base["grant"]["id"]
    accept_user(invite_user(org_id, grant_id, username="u1", email="u1@m.example")["id"])
    bob = invite_user(org_id, grant_id, username="bob", email="bob@meridian.example", level="VIEWER")
    resp = _user_transition(api, bob["id"], "ACTIVE", make_named_user_headers(bob["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_SEATS_AVAILABLE)
    assert get_user(bob["id"])["status"] == "INVITED"
