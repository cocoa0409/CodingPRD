"""The rejection catalogue itself: ten not-found codes each owned by exactly one
reference family, the three header defects that are all authentication failures
before any authorisation question is asked, and the two refusals that guard the
sweeping hold a posture cascade minted.
"""

from test_helpers import (
    ANONYMOUS,
    INVESTIGATOR,
    OFFICER,
    OFFICER_ALT,
    REVIEWER,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_cents,
    assert_funds,
    assert_points,
    assert_posture,
    credit,
    issue_action,
    make_seller_headers,
    publish_rule,
    read_holds,
    read_seller,
    register_seller,
    seller_payload,
    set_clock,
    substantiated_violation,
    validate_error,
    validate_paginated,
    validate_success,
    violation_payload,
)

CLOCK = "2026-08-01T00:00:00.000Z"

# Syntactically a reference, semantically a dead one, for every family at once.
MISSING = NON_EXISTENT_UUID

# Header dictionaries built by hand, because the defect under test is the absence
# or the corruption of a header that the ordinary builders always supply.
JSON_HEADER = {"Content-Type": "application/json"}
NO_ROLE = dict(JSON_HEADER, **{"X-User-ID": "inv-1"})
UNKNOWN_ROLE = dict(JSON_HEADER, **{"X-User-Role": "Auditor", "X-User-ID": "aud-1"})
NO_USER_ID = dict(JSON_HEADER, **{"X-User-Role": "PolicyInvestigator"})


def _harbor_tools(api, **overrides):
    return register_seller(
        api,
        **dict(
            {"legal_name": "Harbor Tools LLC", "email": "ops@harbor-tools.example",
             "tax_id_hash": "TAX-HT-0001", "payout_bank_token": "BANK-HT-0001",
             "address_fingerprint": "ADDR-HT-0001"},
            **overrides,
        ),
    )


# --------------------------------------------------------------------------
# Nine path families and one body family, ten distinct codes
# --------------------------------------------------------------------------
def test_every_dead_path_identifier_reports_its_own_familys_not_found(api):
    """PRD §2.9: "The not-found codes are `ERR_SELLER_NOT_FOUND`,
    `ERR_LISTING_NOT_FOUND`, `ERR_VIOLATION_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
    `ERR_ACTION_NOT_FOUND`, `ERR_POA_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_HOLD_NOT_FOUND`, and `ERR_LINK_NOT_FOUND`, all with HTTP 404."

    Design: Corner/errors/error_every_path_and_body_reference_family_returns_its_own_not_found
    """
    set_clock(api, CLOCK)
    seller = _harbor_tools(api)
    owner = make_seller_headers(seller["id"])

    probes = [
        ("GET /sellers/{id}",
         lambda: api.get_seller(MISSING, INVESTIGATOR),
         ApiErrorId.SELLER_NOT_FOUND),
        ("POST /listings/{id}/relist",
         lambda: api.relist_listing(MISSING, owner),
         ApiErrorId.LISTING_NOT_FOUND),
        ("POST /violations/{id}/open-investigation",
         lambda: api.open_investigation(MISSING, INVESTIGATOR),
         ApiErrorId.VIOLATION_NOT_FOUND),
        ("GET /health-evaluations/{id}",
         lambda: api.get_health_evaluation(MISSING, INVESTIGATOR),
         ApiErrorId.EVALUATION_NOT_FOUND),
        ("GET /enforcement-actions/{id}",
         lambda: api.get_enforcement_action(MISSING, INVESTIGATOR),
         ApiErrorId.ACTION_NOT_FOUND),
        ("POST /plans-of-action/{id}/review",
         lambda: api.review_plan_of_action(MISSING, {"decision": "ACCEPT"}, OFFICER),
         ApiErrorId.POA_NOT_FOUND),
        ("GET /appeals/{id}",
         lambda: api.get_appeal(MISSING, REVIEWER),
         ApiErrorId.APPEAL_NOT_FOUND),
        ("POST /disbursement-holds/{id}/release",
         lambda: api.release_hold(MISSING, {"release_reason": "MANUAL"}, OFFICER),
         ApiErrorId.HOLD_NOT_FOUND),
        ("POST /related-account-links/{id}/adjudicate",
         lambda: api.adjudicate_related_account_link(
             MISSING, {"decision": "DISMISSED"}, OFFICER),
         ApiErrorId.LINK_NOT_FOUND),
    ]

    for label, call, expected in probes:
        response = call()
        # A single generic "not found" would satisfy the status but not the code.
        assert response.status_code == 404, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, expected.value, 404)

    # The one live row in the fixture was never touched by any of the nine.
    assert read_seller(api, seller["id"])["version"] == 1


def test_a_dead_body_reference_reports_the_first_field_the_endpoint_declares(api):
    """PRD §2.9: "The same discipline governs foreign keys carried in a request
    body: they are resolved in the order in which the endpoint declares its input
    fields, and the first unresolvable reference decides the rejection, drawing from
    the same catalogue plus `ERR_POLICY_RULE_NOT_FOUND`."

    Design: Corner/errors/error_every_path_and_body_reference_family_returns_its_own_not_found
    """
    set_clock(api, CLOCK)
    seller = _harbor_tools(api)

    # A live seller and a dead rule: the tenth code, reachable only through a body.
    dead_rule = api.create_violation(
        violation_payload(seller["id"], MISSING, reporter_type="BUYER",
                          evidence_reference="EV-404-0001"),
        INVESTIGATOR,
    )
    validate_error(dead_rule, ApiErrorId.POLICY_RULE_NOT_FOUND.value, 404)

    # Both references dead: `seller_id` is declared first, so it decides.
    both_dead = api.create_violation(
        violation_payload(MISSING, MISSING, reporter_type="BUYER",
                          evidence_reference="EV-404-0002"),
        INVESTIGATOR,
    )
    validate_error(both_dead, ApiErrorId.SELLER_NOT_FOUND.value, 404)

    rows, meta = validate_paginated(api.list_violations(INVESTIGATOR))
    assert rows == [], f"a rejected report was filed anyway: {rows}"
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Authentication before authorisation, and before path existence
# --------------------------------------------------------------------------
def test_three_header_defects_are_all_authentication_failures(api):
    """PRD §2.1: "If `X-User-Role` is absent or is not one of the five role names
    below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the same
    rejection applies when `X-User-ID` is absent for any role other than
    `Anonymous`."

    Design: Corner/errors/error_absent_credentials_are_unauthenticated_before_any_unauthorized_check
    """
    set_clock(api, CLOCK)

    probes = [
        ("no X-User-Role", lambda: api.list_sellers(NO_ROLE)),
        ("X-User-Role: Auditor", lambda: api.list_sellers(UNKNOWN_ROLE)),
        ("no X-User-ID", lambda: api.list_sellers(NO_USER_ID)),
        # Authentication is the first stage of §2.8, so it answers before the
        # path-existence stage that owns the 404 family.
        ("no X-User-Role on a dead path", lambda: api.get_seller(MISSING, NO_ROLE)),
    ]

    for label, call in probes:
        response = call()
        assert response.status_code == 401, \
            f"{label} answered {response.status_code}: {response.text}"
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)


def test_the_registrant_role_may_register_and_nothing_else(api):
    """PRD §2.1: "Seller registration is the only operation this role may perform,
    and it is the only role that may perform it."

    Design: Corner/errors/error_absent_credentials_are_unauthenticated_before_any_unauthorized_check
    """
    set_clock(api, CLOCK)

    # Anonymous supplies no X-User-ID and is nevertheless authenticated, so the
    # refusal here is the authorisation stage and not the authentication stage.
    refused = api.create_policy_rule(
        {"code": "LA-AUTH-1", "category": "LISTING_ACCURACY",
         "base_severity_weight": 2.00, "removal_scope": "ACCOUNT"},
        ANONYMOUS,
    )
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value, 403)

    catalogue, meta = validate_paginated(api.list_policy_rules(OFFICER, {"limit": 100}))
    assert [row["code"] for row in catalogue] == [], \
        f"the refused publication was recorded: {catalogue}"
    assert meta["total_count"] == 0

    registered = validate_success(
        api.register_seller(
            seller_payload(
                legal_name="Harbor Tools LLC", email="ops@harbor-tools.example",
                tax_id_hash="TAX-HT-0001", payout_bank_token="BANK-HT-0001",
                address_fingerprint="ADDR-HT-0001",
            ),
            ANONYMOUS,
        ),
        201,
    )

    assert registered["version"] == 1
    assert_posture(registered, enforcement_state="ACTIVE", disbursement_state="NORMAL",
                   severity_points_balance="0.00")


# --------------------------------------------------------------------------
# The sweeping hold: two refusals on the same row, in priority order
# --------------------------------------------------------------------------
def _suspended_seller_with_the_sweeping_hold(api, code, evidence_reference):
    """A first offence reaches the suspension rung, so the cascade sweeps the whole
    100000-cent balance into one auto-created FULL_HOLD.

    PRD §3.2 caps `base_severity_weight` at 8.00, so twelve points are reached the
    only way a first offence can reach them: PRD §3.6's rights-owner escalation,
    "if the rule's category is `INTELLECTUAL_PROPERTY` and the cited violation's
    `reporter_type` is `RIGHTS_OWNER`, multiply the running figure by a further
    1.50" — 8.00 x 1.00 x 1.50 = 12.00.
    """
    set_clock(api, CLOCK)
    rule = publish_rule(
        api, code=code, category="INTELLECTUAL_PROPERTY", base_severity_weight=8.00,
        removal_scope="ACCOUNT", requires_poa=False,
    )
    seller = _harbor_tools(api)
    credit(api, seller["id"], 100000, "PAYOUT-CYCLE-2026-07-S")
    violation = substantiated_violation(
        api, seller["id"], rule["id"], reporter_type="RIGHTS_OWNER",
        evidence_reference=evidence_reference,
        decision_note="Three listings misdescribed the material of the tool handles.",
    )
    action = issue_action(api, violation["id"])
    active = read_holds(api, params={"seller_id": seller["id"], "state": "ACTIVE"})
    assert len(active) == 1, f"expected one swept hold, got {active}"
    return seller, action, active[0]


def test_the_swept_hold_refuses_the_cascade_reason_before_refusing_the_release(api):
    """PRD §3.9: "A `ComplianceOfficer` may release a hold by hand, supplying a
    `release_reason` that a caller may only ever set to `MANUAL` or
    `INVESTIGATION_CLOSED`; the other two reasons, `APPEAL_GRANTED` and
    `SUPERSEDED_BY_FULL_HOLD`, are written by cascades alone." And: "The hold must be
    in `ACTIVE`, the acting officer must not be the hold's `created_by_user_id` per
    §2.7, and the hold's `hold_type` must be `RESERVE` — a sweeping `FULL_HOLD` row
    may be released only by a reinstatement or posture cascade, and a manual attempt
    on one is refused with `ERR_HOLD_NOT_MANUALLY_RELEASABLE`."

    Design: Corner/errors/error_full_hold_row_cannot_be_released_by_hand
    """
    seller, action, swept = _suspended_seller_with_the_sweeping_hold(
        api, "LA-SUSP-1", "EV-SUSP-0001"
    )
    assert_points(action["severity_points_applied"], "12.00", "severity_points_applied")
    assert action["action_type"] == "ACCOUNT_SUSPENSION"
    assert swept["hold_type"] == "FULL_HOLD"
    assert swept["reserve_basis"] == "NONE"
    assert swept["auto_created"] is True
    assert_cents(swept["held_amount_cents"], 100000, "held_amount_cents")

    # The reason the cascade itself writes is not a value a caller may send, and
    # the request-shape stage answers before the releasability stage.
    by_cascade_reason = api.release_hold(
        swept["id"], {"release_reason": "SUPERSEDED_BY_FULL_HOLD"}, OFFICER
    )
    validate_error(by_cascade_reason, ApiErrorId.INVALID_REQUEST.value, 400)

    # With a reason a caller may send, the row's own type decides.
    by_hand = api.release_hold(swept["id"], {"release_reason": "MANUAL"}, OFFICER)
    validate_error(by_hand, ApiErrorId.HOLD_NOT_MANUALLY_RELEASABLE.value, 409)

    after = validate_success(api.get_hold(swept["id"], OFFICER))
    assert after["state"] == "ACTIVE"
    assert after["released_at"] is None
    assert after["release_reason"] is None
    assert_funds(read_seller(api, seller["id"]), available=0, held=100000,
                 credited=100000, debited=0)
    assert_posture(read_seller(api, seller["id"]), enforcement_state="SUSPENDED",
                   disbursement_state="FULL_HOLD")


def test_forfeiture_is_refused_while_the_account_is_only_suspended(api):
    """PRD §3.9: "The seller's `enforcement_state` must be `BANNED`; forfeiting from
    a merely suspended account is refused with `ERR_SELLER_NOT_BANNED`."

    Design: Corner/errors/error_forfeit_is_refused_while_the_seller_is_only_suspended
    """
    seller, _, swept = _suspended_seller_with_the_sweeping_hold(
        api, "LA-FRF-1", "EV-FRF-0001"
    )
    before = read_seller(api, seller["id"])
    # Suspension is not closure: the account has never been banned.
    assert_posture(before, enforcement_state="SUSPENDED", disbursement_state="FULL_HOLD")
    assert before["ban_reason"] is None

    # co-2 is not the hold's creator, so the segregation check cannot fire first.
    refused = api.forfeit_hold(swept["id"], {"forfeited_amount_cents": 100000}, OFFICER_ALT)

    validate_error(refused, ApiErrorId.SELLER_NOT_BANNED.value, 409)
    unmoved = validate_success(api.get_hold(swept["id"], OFFICER))
    assert unmoved["state"] == "ACTIVE"
    assert unmoved["released_at"] is None

    after = read_seller(api, seller["id"])
    # A guard that debited first and validated second would show up here.
    assert_funds(after, available=0, held=100000, credited=100000, debited=0)
    assert after["version"] == before["version"]
