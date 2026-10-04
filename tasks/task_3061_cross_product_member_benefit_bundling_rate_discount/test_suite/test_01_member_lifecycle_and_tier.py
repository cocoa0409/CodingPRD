"""Member standing, the member cycle, and the two tier variants."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_member,
    create_holding_payload,
    fetch_holding,
    fetch_member,
    is_iso8601_timestamp,
    make_member_headers,
    register_member,
    setup_cumulative_autopay_stack,
    validate_error,
    validate_success,
)


def test_member_first_adoption_promotes_prospect_to_member_active(api):
    """PRD §2.4: "`member_status` takes one of `PROSPECT`, `MEMBER_ACTIVE`,
    `MEMBER_AT_RISK`, or `MEMBER_LAPSED`. `member_since_at` records the
    timestamp of the member's first product adoption and is null while the
    member remains a prospect."
    PRD §3.1: "the very first adoption in a member's life also promotes them
    from `PROSPECT` to `MEMBER_ACTIVE` and stamps `member_since_at` with the
    current logical instant — this is the single event that converts a prospect
    into a member."

    Design: Difficulty/non_linear_state_machine/member_status_cycle_prospect_lapsed_back_to_prospect
    """
    api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                        TEST_USERS["platform_admin_headers"])
    member = api.create_member(
        {"member_number": "M-CYC-005", "full_name": "Eli Marsh", "email": "eli.cyc@x.com"},
        TEST_USERS["anonymous_headers"],
    ).json()["data"]
    assert member["member_status"] == "PROSPECT"
    assert member["member_since_at"] is None

    resp = api.create_holding(create_holding_payload(member["id"], product_line="INVESTING"),
                              TEST_USERS["platform_admin_headers"])
    holding = validate_success(resp, expected_status=201)
    assert_holding = fetch_holding(holding["id"])
    assert assert_holding["adoption_status"] == "PENDING"

    resp = api.adopt_holding(holding["id"], make_member_headers(member["id"]))
    adopted = validate_success(resp, expected_status=200)
    assert adopted["adoption_status"] == "ADOPTED"

    after = fetch_member(member["id"])
    assert_member(after)
    assert after["member_status"] == "MEMBER_ACTIVE", (
        "the first adoption must convert the prospect into a member"
    )
    assert after["member_since_at"] is not None, "member_since_at must be stamped on first adoption"
    assert is_iso8601_timestamp(after["member_since_at"])
    assert after["member_since_at"] == "2026-09-01T00:00:00Z"


def test_member_cycle_returns_to_prospect_after_laps_and_reset(api):
    """PRD §3.7: "a member at risk crosses into the lapsed state once the score
    reaches 85, and a member whose deposits stop and whose tier collapses can
    cross the lapse band directly from the active state".
    PRD §3.7: "a lapsed member holding no adopted products may instead be reset
    to `PROSPECT`, which clears `member_since_at` and forces the tier to `NONE`".

    Design: Difficulty/non_linear_state_machine/member_status_cycle_prospect_lapsed_back_to_prospect
    """
    member = register_member(member_number="M-CYC-005B", email="eli.cyc.b@x.com")
    holding = api.create_holding(
        create_holding_payload(member["id"], product_line="INVESTING"),
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))

    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    api.post_deposit(member["id"], {"enrollment_id": enrollment["id"], "amount_cents": 200000,
                                    "posted_at": "2026-09-01T00:00:00Z"},
                     TEST_USERS["platform_admin_headers"])
    api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"])

    # Miss October, move into GRACE, then land LAPSED well past the deadline.
    api.set_current_utc({"current_utc": "2026-11-01T00:00:00Z"}, TEST_USERS["platform_admin_headers"])
    api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"])
    api.set_current_utc({"current_utc": "2027-01-01T00:00:00Z"}, TEST_USERS["platform_admin_headers"])
    api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"])

    lapsed = validate_success(api.detect_churn(member["id"], TEST_USERS["platform_admin_headers"]))
    assert lapsed["member_status"] == "MEMBER_LAPSED", (
        f"churn score {lapsed['churn_risk_score']} did not cross the lapse band"
    )

    # The member still holds an adopted product, so reset-to-prospect is refused.
    resp = api.reset_member_to_prospect(member["id"], TEST_USERS["platform_admin_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    # Suspending the only holding drops the adopted count to zero.
    api.suspend_holding(holding["id"], TEST_USERS["platform_admin_headers"])
    assert fetch_member(member["id"])["product_adoption_count"] == 0

    reset = validate_success(
        api.reset_member_to_prospect(member["id"], TEST_USERS["platform_admin_headers"])
    )
    assert reset["member_status"] == "PROSPECT", (
        "the member machine is cyclic: PROSPECT is reachable a second time"
    )
    assert reset["member_since_at"] is None
    assert reset["member_tier"] == "NONE"
    assert fetch_member(member["id"])["member_status"] == "PROSPECT"


# --------------------------------------------------------------------------
# Member creation, retrieval and identity errors
# --------------------------------------------------------------------------

def test_member_creation_returns_every_declared_field_and_starts_prospect(api):
    """PRD §3.1: "Registration supplies a `member_number`, a `full_name`, and
    an `email`, and creates the member in `PROSPECT` standing with a null
    `member_since_at`, a `member_tier` of `NONE`, a `benefit_entitlement_state`
    of `NONE`, a `rewards_points_balance` of 0 and a `churn_risk_score` of 0."

    Design: Corner/entities/member_create_returns_every_declared_field_and_starts_prospect
    """
    payload = {"member_number": "M-C-001", "full_name": "Sara Kim", "email": "sara.c@x.com"}
    resp = api.create_member(payload, TEST_USERS["anonymous_headers"])
    member = validate_success(resp, expected_status=201)
    assert resp.json()["response_type"] == "object"

    assert_member(member)
    assert member["member_number"] == "M-C-001"
    assert member["full_name"] == "Sara Kim"
    assert member["email"] == "sara.c@x.com"
    assert member["member_status"] == "PROSPECT"
    assert member["member_since_at"] is None
    assert member["member_tier"] == "NONE"
    assert member["benefit_entitlement_state"] == "NONE"
    assert member["rewards_points_balance"] == 0
    assert member["churn_risk_score"] == 0
    assert member["product_adoption_count"] == 0
    assert member["product_line_set"] == []
    assert member["version"] == 1

    meta = resp.json()["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def test_member_get_round_trips_every_stored_field_unchanged(api):
    """PRD §2.4: "`last_qualifying_deposit_at` is the most recent timestamp at
    which a qualifying deposit posted, and is null until one has ever posted."

    Design: Corner/entities/member_get_round_trips_every_stored_field_unchanged
    """
    created = api.create_member(
        {"member_number": "M-C-002", "full_name": "Tom Vega", "email": "tom.c@x.com"},
        TEST_USERS["anonymous_headers"],
    ).json()["data"]

    resp = api.get_member(created["id"], TEST_USERS["platform_admin_headers"])
    member = validate_success(resp, expected_status=200)
    assert resp.json()["response_type"] == "object"
    assert_member(member)
    assert member["id"] == created["id"]
    assert member["member_number"] == "M-C-002"
    assert member["email"] == "tom.c@x.com"
    assert member["member_since_at"] is None
    assert member["last_qualifying_deposit_at"] is None
    assert member["created_at"] == created["created_at"]
    assert member["version"] == created["version"]


def test_member_get_with_an_unknown_id_returns_member_not_found(api):
    """PRD §2.9: "The member named in the path exists, else `ERR_MEMBER_NOT_FOUND`;
    this applies to every endpoint whose path carries a member identifier."

    Design: Corner/entities/member_get_with_an_unknown_id_returns_member_not_found
    """
    resp = api.get_member(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    error = validate_error(resp, "ERR_MEMBER_NOT_FOUND", expected_status=404)
    assert resp.json()["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


# --------------------------------------------------------------------------
# Tier variants
# --------------------------------------------------------------------------

def test_member_tier_point_in_time_counts_only_adopted_holdings(api):
    """PRD §2.4: "A separate forward-looking projection answers what a member
    would reach if every one of their pending holdings were adopted — that
    projection additionally counts holdings whose adoption status is `PENDING`,
    so a member with one adopted holding and two pending holdings spanning three
    distinct lines reads `BASE` under the canonical point-in-time rule but
    `PREMIER` under the projection."

    Design: Difficulty/dual_variant_calc/member_tier_point_in_time_vs_forward_looking_on_pending_holdings
    """
    api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                        TEST_USERS["platform_admin_headers"])
    member = register_member(member_number="M-3061-002", email="bo.c@x.com")
    banking = api.create_holding(
        create_holding_payload(member["id"], product_line="BANKING", balance_cents=300000),
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    for line in ("INVESTING", "CAREER"):
        api.create_holding(create_holding_payload(member["id"], product_line=line),
                           TEST_USERS["platform_admin_headers"])
    validate_success(api.adopt_holding(banking["id"], make_member_headers(member["id"])))

    stored = fetch_member(member["id"])
    assert stored["member_tier"] == "BASE", (
        "the canonical point-in-time tier counts only the single ADOPTED holding"
    )
    assert stored["product_adoption_count"] == 1
    assert stored["product_line_set"] == ["BANKING"]


def test_tier_projection_counts_pending_holdings_and_reports_the_delta(api):
    """PRD §2.4: "that projection additionally counts holdings whose adoption
    status is `PENDING`, so a member with one adopted holding and two pending
    holdings spanning three distinct lines reads `BASE` under the canonical
    point-in-time rule but `PREMIER` under the projection."

    Design: Difficulty/dual_variant_calc/member_tier_point_in_time_vs_forward_looking_on_pending_holdings
    """
    api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                        TEST_USERS["platform_admin_headers"])
    member = register_member(member_number="M-3061-002B", email="bo.c.b@x.com")
    banking = api.create_holding(
        create_holding_payload(member["id"], product_line="BANKING", balance_cents=300000),
        TEST_USERS["platform_admin_headers"],
    ).json()["data"]
    for line in ("INVESTING", "CAREER"):
        api.create_holding(create_holding_payload(member["id"], product_line=line),
                           TEST_USERS["platform_admin_headers"])
    validate_success(api.adopt_holding(banking["id"], make_member_headers(member["id"])))

    resp = api.get_tier_projection(member["id"], TEST_USERS["platform_admin_headers"])
    projection = validate_success(resp, expected_status=200)
    assert projection["current_tier"] == "BASE"
    assert projection["projected_tier"] == "PREMIER", (
        "the projection counts the two PENDING holdings, reaching 3 products across 3 distinct lines"
    )
    assert projection["pending_adoption_count"] == 2


def test_tier_rule_admitted_by_the_recomputed_tier_lands_in_the_stack(api):
    """PRD §2.4: "Tier is derived from adoption breadth by a top-down threshold
    rule; the first clause satisfied determines the result. A member reaches
    `PREMIER` when their adopted product count is at least 3 and their adopted
    distinct product-line count is at least 3. Failing that, they reach `PLUS`
    when their adopted product count is at least 2 and their distinct line count
    is at least 2."
    PRD §3.4: "Once activated, the rule's status becomes `ACTIVE` and every loan
    of every member whose tier is at least `min_member_tier` is repriced, with
    the discount stack and effective rate recomputed."

    Design: Difficulty/combinatorial_formula/member_tier_then_base_apr_evaluation_order_pins_the_final_apr
    """
    setup = setup_cumulative_autopay_stack(base_apr_bps=1200, base_bps=250, autopay_bps=75)
    member = fetch_member(setup["member"]["id"])
    assert member["member_tier"] == "PLUS", (
        "two adopted products across LENDING and BANKING reach PLUS"
    )
    assert member["product_adoption_count"] == 2
    assert member["product_line_set"] == ["LENDING", "BANKING"]

    loan = setup["loan"]
    assert loan["discount_stack_bps"] == 325, (
        "250 from the tier rule plus 75 from the autopay rule; the tier rule is "
        "admitted only because the tier step ran before the discount lookup"
    )
    assert loan["effective_apr_bps"] == 875, "1200 - 325"


def test_a_min_tier_rule_prices_only_once_the_tier_step_has_run(api):
    """PRD §2.5: "The candidate pool is every rule that is `ACTIVE`, whose window
    contains the current logical instant under the half-open convention that the
    start is inclusive and the end is exclusive, whose `min_member_tier` is at or
    below the member's current tier".
    PRD §2.4: "Failing that, they reach `BASE` when their adopted product count
    is at least 1. Otherwise the tier is `NONE`."

    Design: Difficulty/combinatorial_formula/member_tier_then_base_apr_evaluation_order_pins_the_final_apr
    """
    from test_helpers import (
        attach_application,
        create_active_rule,
        create_adopted_holding,
        fetch_loan,
        loan_account_in_state,
        register_member,
        validate_success as vs,
    )

    vs(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                           TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-ORD-003", email="ord.c@x.com")
    lending = create_adopted_holding(member["id"], "LENDING", 0)
    loan = loan_account_in_state(member["id"], lending["id"], base_apr_bps=1200,
                                 principal_cents=2000000)
    assert fetch_member(member["id"])["member_tier"] == "BASE", (
        "a single adopted holding reaches BASE, below the rule's floor"
    )

    rule = create_active_rule("TIER_PLUS_ORD", discount_kind="MEMBER_TIER",
                              stacking_class="BASE", discount_bps=250,
                              min_member_tier="PLUS")
    before = fetch_loan(loan["id"])
    assert before["discount_stack_bps"] == 0, (
        "the tier gate is satisfied only after the tier step has raised the member"
    )
    assert before["effective_apr_bps"] == 1200

    attach_application(loan["id"], rule["id"])
    still = fetch_loan(loan["id"])
    assert still["discount_stack_bps"] == 0, (
        "an attached application does not bypass the tier gate while the member is BASE"
    )

    create_adopted_holding(member["id"], "INVESTING", 0)
    raised = fetch_member(member["id"])
    assert raised["member_tier"] == "PLUS"
    assert raised["product_adoption_count"] == 2

    after = fetch_loan(loan["id"])
    assert after["discount_stack_bps"] == 250, (
        "once the tier step has run the rule enters the candidate pool and prices"
    )
    assert after["effective_apr_bps"] == 950, "1200 - 250"
