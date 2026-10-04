"""Remaining breadth corners: creation guards, listing, side effects, precedence."""
from test_helpers import (
    TEST_USERS,
    create_active_rule,
    create_adopted_holding,
    create_holding_payload,
    create_rule_payload,
    enrollment_in_grace,
    fetch_entitlement,
    fetch_holding,
    fetch_loan,
    fetch_member,
    list_holdings,
    make_member_headers,
    paginated,
    post_deposit,
    register_member,
    rewards_adjust_payload,
    setup_cumulative_autopay_stack,
    setup_grace_enrollment_for,
    validate_error,
    validate_success,
)


# --------------------------------------------------------------------------
# Creation guards and defaults
# --------------------------------------------------------------------------

def test_opening_a_holding_without_a_product_line_is_a_malformed_request(api):
    """PRD §2.9: "A body that is malformed, omits a required field, carries an
    unknown field, or supplies a value outside its declared type or enumeration
    is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/holding_create_missing_product_line_returns_invalid_request
    """
    member = register_member(member_number="M-C-005", email="vic.c@x.com")
    resp = api.create_holding({"member_id": member["id"]},
                              TEST_USERS["platform_admin_headers"])
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)
    assert list_holdings(member["id"]) == [], "the refused create must not persist a holding"


def test_omitting_the_balance_defaults_a_holding_to_zero(api):
    """PRD §2.4: "`balance_cents` records the held balance for the line — a
    deposit balance, an invested value, or outstanding principal — defaulting
    to 0."
    PRD §3.1: "the holding is created in `PENDING` status with a null `adopted_at`
    and a balance defaulting to 0."

    Design: Corner/entities/holding_create_omitting_balance_defaults_it_to_zero
    """
    member = register_member(member_number="M-C-006", email="wen.c@x.com")
    resp = api.create_holding({"member_id": member["id"], "product_line": "BANKING"},
                              TEST_USERS["platform_admin_headers"])
    holding = validate_success(resp, expected_status=201)
    assert holding["balance_cents"] == 0
    assert holding["adoption_status"] == "PENDING"
    assert holding["adopted_at"] is None
    assert fetch_member(member["id"])["qualifying_deposit_balance_cents"] == 0


def test_declaring_an_entitlement_with_an_unknown_benefit_code_is_a_malformed_request(api):
    """PRD §2.9: "A body that is malformed, omits a required field, carries an
    unknown field, or supplies a value outside its declared type or enumeration
    is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/entitlement_create_rejects_an_unknown_benefit_code
    """
    member = register_member(member_number="M-C-009", email="zed.c@x.com")
    holding = create_adopted_holding(member["id"], "CAREER", 0)
    resp = api.create_entitlement(
        member["id"],
        {"source_holding_id": holding["id"], "benefit_code": "FREE_MONEY", "value_bps": 10},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(resp, "ERR_INVALID_REQUEST", expected_status=400)
    rows = validate_success(api.list_entitlements(TEST_USERS["benefits_admin_headers"],
                                                  params={"member_id": member["id"]}))
    assert rows == [], "the refused declaration must not persist an entitlement"


def test_an_entitlement_cannot_name_another_members_holding(api):
    """PRD §3.1: "An entitlement whose `source_holding_id` does not exist or
    belongs to a different member is refused with
    `ERR_ENTITLEMENT_NO_SOURCE_HOLDING`."

    Design: Corner/entities/entitlement_create_with_a_holding_owned_by_another_member_is_refused
    """
    owner = register_member(member_number="M-C-010A", email="ana.sol@x.com")
    other = register_member(member_number="M-C-010B", email="ben.sol@x.com")
    holding = create_adopted_holding(owner["id"], "CAREER", 0)

    resp = api.create_entitlement(
        other["id"],
        {"source_holding_id": holding["id"], "benefit_code": "CAREER_COACHING_CREDIT",
         "value_bps": 5},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(resp, "ERR_ENTITLEMENT_NO_SOURCE_HOLDING", expected_status=422)
    for member_id in (owner["id"], other["id"]):
        assert validate_success(api.list_entitlements(TEST_USERS["benefits_admin_headers"],
                                                      params={"member_id": member_id})) == []


def test_the_server_stamps_the_fields_the_client_cannot_supply(api):
    """PRD §2.4: "`id` is a server-minted UUID string with no type prefix.
    `created_at` is an ISO 8601 UTC timestamp with exactly three fractional
    digits, set at creation. `updated_at` is an ISO 8601 UTC timestamp with
    three fractional digits and is refreshed on every mutation, including
    mutations to derived fields. `version` is an integer that starts at 1 and
    increments by one on every mutation".
    PRD §3.1: "Adoption stamps `adopted_at`, moves the holding to `ADOPTED`".

    Design: Corner/entities/system_fields_are_server_minted_and_never_echo_client_values
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-C-008", email="yuri.c@x.com")
    holding = api.create_holding(create_holding_payload(member["id"], product_line="LENDING"),
                                 TEST_USERS["platform_admin_headers"]).json()["data"]
    assert holding["version"] == 1

    adopted = validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    assert adopted["adopted_at"] == "2026-09-01T00:00:00Z", (
        "adopted_at is stamped from the logical clock, not taken from the request"
    )
    assert adopted["version"] == 2, "the mutation increments the version by one"


def test_a_loan_starts_provisional_with_the_undiscounted_rate(api):
    """PRD §3.5: "The loan is created with autopay `NOT_ENROLLED`, pricing
    `PROVISIONAL`, a zero discount stack, an effective rate equal to the
    undiscounted rate, and a fresh `last_priced_at`."

    Design: Corner/entities/loan_account_effective_apr_is_computed_and_input_value_ignored
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-C-007", email="xiu.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "PERSONAL",
         "principal_cents": 800000, "base_apr_bps": 999},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    assert loan["effective_apr_bps"] == 999, "the effective rate equals the undiscounted rate"
    assert loan["discount_stack_bps"] == 0
    assert loan["pricing_status"] == "PROVISIONAL"
    assert loan["autopay_status"] == "NOT_ENROLLED"
    assert loan["last_priced_at"] == "2026-09-01T00:00:00Z"


# --------------------------------------------------------------------------
# State-machine corners
# --------------------------------------------------------------------------

def test_re_adopting_a_closed_holding_is_refused_and_leaves_no_side_effects(api):
    """PRD §3.2: "Closure is permanent. A member may close a holding they own,
    and the platform admits the closure only when the holding's outstanding
    `balance_cents` is zero and no loan account referencing the holding still
    sits in `PROVISIONAL` or `FINAL` pricing." and "`CLOSED` is the only terminal
    holding state".

    Design: Corner/state_machines/holding_adopt_from_closed_returns_invalid_state_and_no_side_effects
    """
    member = register_member(member_number="M-S-001", email="cara.c@x.com")
    holding = create_adopted_holding(member["id"], "CAREER", 0)
    validate_success(api.close_holding(holding["id"], make_member_headers(member["id"])))

    resp = api.adopt_holding(holding["id"], make_member_headers(member["id"]))
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    after = fetch_holding(holding["id"])
    assert after["adoption_status"] == "CLOSED"
    member_after = fetch_member(member["id"])
    assert member_after["product_adoption_count"] == 0
    assert member_after["member_tier"] == "NONE"
    assert validate_success(api.list_entitlements(TEST_USERS["benefits_admin_headers"],
                                                  params={"member_id": member["id"]})) == []


def test_a_member_cannot_adopt_another_members_holding(api):
    """PRD §3.1: "A `Member` adopts the holding they own, and the platform
    verifies that the acting identity is the member named on the holding before
    anything else."
    PRD §2.1: "a mismatch is an `ERR_FORBIDDEN_ROLE` rejection".

    Design: Corner/state_machines/holding_adopt_by_a_different_member_is_forbidden
    """
    owner = register_member(member_number="M-S-002A", email="dana.c@x.com")
    stranger = register_member(member_number="M-S-002B", email="evan.c@x.com")
    holding = api.create_holding(create_holding_payload(owner["id"], product_line="INVESTING"),
                                 TEST_USERS["platform_admin_headers"]).json()["data"]

    resp = api.adopt_holding(holding["id"], make_member_headers(stranger["id"]))
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)

    assert fetch_holding(holding["id"])["adoption_status"] == "PENDING"
    assert fetch_member(owner["id"])["member_status"] == "PROSPECT"
    assert fetch_member(stranger["id"])["member_status"] == "PROSPECT"


def test_closing_a_lending_holding_with_a_live_loan_is_refused(api):
    """PRD §3.2: "A lending holding that still carries a live loan is refused
    with `ERR_HOLDING_HAS_ACTIVE_LOAN` (HTTP 409), whatever pricing state that
    loan currently occupies — provisional, final or stepped down."

    Design: Corner/state_machines/holding_close_while_a_live_loan_exists_returns_holding_has_active_loan
    """
    member = register_member(member_number="M-S-003", email="fern.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "AUTO",
         "principal_cents": 300000, "base_apr_bps": 1050},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    assert loan["pricing_status"] == "PROVISIONAL"

    resp = api.close_holding(holding["id"], make_member_headers(member["id"]))
    validate_error(resp, "ERR_HOLDING_HAS_ACTIVE_LOAN", expected_status=409)
    assert fetch_holding(holding["id"])["adoption_status"] == "ADOPTED"


def test_autopay_and_pricing_move_independently_on_one_loan_row(api):
    """PRD §3.5: "Two parallel dimensions then evolve independently on the same
    loan."
    PRD §3.5: "an administrator may suspend autopay, but only from the enrolled
    state and only while the loan is not already stepped down; a suspension moves
    the standing to `SUSPENDED`."

    Design: Corner/state_machines/autopay_and_pricing_are_independent_dimensions_on_one_loan_row
    """
    member = register_member(member_number="M-S-004", email="gale.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "PERSONAL",
         "principal_cents": 700000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    assert loan["autopay_status"] == "NOT_ENROLLED"
    assert loan["pricing_status"] == "PROVISIONAL"

    enrolled = validate_success(api.enroll_autopay(loan["id"], make_member_headers(member["id"])))
    assert enrolled["autopay_status"] == "ENROLLED"
    finalized = validate_success(api.finalize_pricing(loan["id"], TEST_USERS["underwriter_headers"]))
    assert finalized["pricing_status"] == "FINAL"

    suspended = validate_success(api.suspend_autopay(loan["id"], TEST_USERS["platform_admin_headers"]))
    assert suspended["autopay_status"] == "SUSPENDED"
    assert suspended["pricing_status"] == "FINAL", (
        "the autopay dimension does not gate or reset the pricing dimension"
    )

    resumed = validate_success(api.enroll_autopay(loan["id"], make_member_headers(member["id"])))
    assert resumed["autopay_status"] == "ENROLLED"
    assert resumed["pricing_status"] == "FINAL"


def test_suspending_holdings_reports_per_item_outcomes_without_rollback(api):
    """PRD §3.2: "An administrator may suspend an adopted holding, moving it to
    `SUSPENDED`; suspension immediately recomputes the holding's
    `deposit_rate_eligible` to false, recomputes the member's
    `qualifying_deposit_balance_cents` and `product_adoption_count`".
    PRD §2.9: "6. The target resource is in a state that permits the requested
    transition, else `ERR_INVALID_STATE`; this applies to every state-transition
    operation."

    Design: Corner/cross_cutting_layers/operator_suspends_holdings_bulk_style_and_partial_failures_are_per_item
    """
    member = register_member(member_number="M-L-005", email="willa.c@x.com")
    adopted = create_adopted_holding(member["id"], "BANKING", 150000)
    pending_investing = api.create_holding(
        create_holding_payload(member["id"], product_line="INVESTING"),
        TEST_USERS["platform_admin_headers"]).json()["data"]
    pending_career = api.create_holding(
        create_holding_payload(member["id"], product_line="CAREER"),
        TEST_USERS["platform_admin_headers"]).json()["data"]

    first = validate_success(api.suspend_holding(adopted["id"], TEST_USERS["platform_admin_headers"]))
    assert first["adoption_status"] == "SUSPENDED"

    second = api.suspend_holding(pending_investing["id"], TEST_USERS["platform_admin_headers"])
    validate_error(second, "ERR_INVALID_STATE", expected_status=409)

    assert fetch_holding(adopted["id"])["adoption_status"] == "SUSPENDED", (
        "the earlier success is not rolled back by the later failure"
    )
    assert fetch_member(member["id"])["product_adoption_count"] == 0, (
        "SUSPENDED rows are excluded from the adopted count"
    )

    third = api.suspend_holding(pending_career["id"], TEST_USERS["platform_admin_headers"])
    validate_error(third, "ERR_INVALID_STATE", expected_status=409)


def test_a_closed_holding_remains_queryable_while_leaving_the_adopted_count(api):
    """PRD §3.2: "`CLOSED` is the only terminal holding state; suspension, by
    contrast, always has a way back."
    PRD §2.4: "`product_adoption_count` is the number of the member's product
    holdings whose adoption status is `ADOPTED`."

    Design: Corner/cross_cutting_layers/hard_delete_is_unavailable_so_closed_holdings_remain_queryable
    """
    member = register_member(member_number="M-L-006", email="xola.c@x.com")
    holding = create_adopted_holding(member["id"], "INVESTING", 0)
    validate_success(api.close_holding(holding["id"], make_member_headers(member["id"])))

    rows = list_holdings(member["id"])
    assert len(rows) == 1, "the closed row is never removed from the collection"
    assert rows[0]["adoption_status"] == "CLOSED"
    assert rows[0]["closed_at"] is not None
    assert fetch_member(member["id"])["product_adoption_count"] == 0


def test_adoption_fans_out_the_members_derived_fields_in_one_ordering(api):
    """PRD §3.1: "Adoption stamps `adopted_at`, moves the holding to `ADOPTED`,
    and sets in motion a cascade: the member's `product_adoption_count` and
    `product_line_set` are recomputed, `member_tier` is recomputed under the
    canonical point-in-time rule described in §2.4, `churn_risk_score` is
    recomputed, and any entitlement of that holding still in `PENDING` is
    granted."

    Design: Corner/cross_cutting_layers/holding_adopt_fans_out_derived_fields_across_the_member_row
    """
    member = register_member(member_number="M-L-003", email="ursa.c@x.com")
    banking = api.create_holding(
        create_holding_payload(member["id"], product_line="BANKING", balance_cents=200000),
        TEST_USERS["platform_admin_headers"]).json()["data"]
    investing = api.create_holding(
        create_holding_payload(member["id"], product_line="INVESTING"),
        TEST_USERS["platform_admin_headers"]).json()["data"]

    validate_success(api.adopt_holding(banking["id"], make_member_headers(member["id"])))
    after_first = fetch_member(member["id"])
    assert after_first["product_adoption_count"] == 1
    assert after_first["product_line_set"] == ["BANKING"]
    assert after_first["member_tier"] == "BASE"
    assert after_first["member_status"] == "MEMBER_ACTIVE"
    assert after_first["member_since_at"] is not None

    validate_success(api.adopt_holding(investing["id"], make_member_headers(member["id"])))
    after_second = fetch_member(member["id"])
    assert after_second["product_adoption_count"] == 2
    assert after_second["product_line_set"] == ["BANKING", "INVESTING"], (
        "the line set is sorted ascending by the enum's stable ordering"
    )
    assert after_second["member_tier"] == "PLUS"
    assert after_second["qualifying_deposit_balance_cents"] == 200000, (
        "the balance rollup is refreshed by the same cascade"
    )


def test_the_holding_list_filters_by_member_and_by_line_independently(api):
    """PRD §2.3: "A collection endpoint may also accept filter query parameters;
    the available filters for each collection are enumerated wherever that
    collection is discussed in this document."
    PRD §4: "List product holdings, filterable by member or line".

    Design: Corner/endpoints/holding_list_filters_by_member_and_by_line_independently
    """
    first = register_member(member_number="M-E-004", email="hana.p@x.com")
    second = register_member(member_number="M-E-005", email="iva.p@x.com")
    api.create_holding(create_holding_payload(first["id"], product_line="BANKING",
                                             balance_cents=100000),
                       TEST_USERS["platform_admin_headers"])
    api.create_holding(create_holding_payload(first["id"], product_line="INVESTING"),
                       TEST_USERS["platform_admin_headers"])
    api.create_holding(create_holding_payload(second["id"], product_line="BANKING"),
                       TEST_USERS["platform_admin_headers"])

    by_member = list_holdings(first["id"])
    assert len(by_member) == 2
    by_line = list_holdings(product_line="BANKING")
    assert len(by_line) == 2, "the line filter spans both members"
    both = list_holdings(first["id"], product_line="BANKING")
    assert len(both) == 1
    for row in by_member:
        assert row["id"] and row["created_at"] and row["updated_at"] and row["version"] >= 1


def test_the_rewards_ledger_list_paginates_over_the_whole_filtered_set(api):
    """PRD §2.3: "`limit` caps the number of items returned; when omitted it
    defaults to 10, and it may be set as low as 1 and as high as 100 — a value
    outside that range is a malformed request. `offset` skips a number of
    leading items and defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/rewards_ledger_list_paginates_and_reports_total_count_and_has_more
    """
    member = register_member(member_number="M-C-003", email="uma.c@x.com")
    for delta, code in ((100, "A"), (200, "B"), (300, "C")):
        validate_success(api.adjust_rewards(member["id"],
                                            rewards_adjust_payload(delta, source_event_code=code),
                                            TEST_USERS["benefits_admin_headers"]),
                         expected_status=201)

    first_page = api.list_ledger_entries(TEST_USERS["benefits_admin_headers"],
                                         params={"member_id": member["id"], "limit": 2, "offset": 0})
    rows, meta = paginated(first_page)
    assert rows, "the first page returns rows"
    assert len(rows) == 2
    assert meta["total_count"] == 3, "total_count counts the whole filtered set, not the page"
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0

    second_page = api.list_ledger_entries(TEST_USERS["benefits_admin_headers"],
                                          params={"member_id": member["id"], "limit": 2, "offset": 2})
    rows2, meta2 = paginated(second_page)
    assert len(rows2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    defaulted = api.list_ledger_entries(TEST_USERS["benefits_admin_headers"],
                                        params={"member_id": member["id"]})
    rows3, meta3 = paginated(defaulted)
    assert len(rows3) == 3
    assert meta3["limit"] == 10, "limit defaults to 10"
    assert meta3["offset"] == 0, "offset defaults to 0"


def test_authorization_is_checked_before_the_cross_sell_compliance_rung(api):
    """PRD §2.9: "2. `X-User-Role` is one of the six declared roles and is listed
    on the endpoint, and, where the operation is ownership-guarded, the acting
    identity is the owning member, else `ERR_FORBIDDEN_ROLE`. This rung applies
    to every endpoint."
    PRD §2.9: "Validation is a single ordered ladder, evaluated top to bottom, and
    the first rule that fails determines the error returned; later rules are not
    consulted."

    Design: Corner/validations/participant_role_on_a_benefits_admin_endpoint_returns_forbidden_role
    """
    resp = api.create_rule(
        create_rule_payload("UW_TRY", discount_kind="AUTOPAY", stacking_class="ADDITIVE",
                            discount_bps=10),
        TEST_USERS["underwriter_headers"],
    )
    validate_error(resp, "ERR_FORBIDDEN_ROLE", expected_status=403)
    assert validate_success(api.list_rules(TEST_USERS["benefits_admin_headers"],
                                           params={"status": "DRAFT"})) == []

    allowed = api.create_rule(
        create_rule_payload("UW_TRY", discount_kind="AUTOPAY", stacking_class="ADDITIVE",
                            discount_bps=10),
        TEST_USERS["benefits_admin_headers"],
    )
    validate_success(allowed, expected_status=201)


def test_retiring_a_rule_rolls_back_live_applications_and_reprices_the_loan(api):
    """PRD §3.4: "An operator retires an active rule, moving it to `RETIRED`, and
    every application referencing that rule that is still `APPLIED` and was
    applied before the current logical instant is rolled back; every affected
    loan is then repriced with its stack and effective rate recomputed and its
    pricing timestamp refreshed."

    Design: Corner/state_machines/retiring_a_rule_rolls_back_live_applications_and_reprices_loans
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-S-012", email="omar.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    rule = create_active_rule("AUTOPAY_C12", discount_kind="AUTOPAY",
                              stacking_class="ADDITIVE", discount_bps=75)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "PERSONAL",
         "principal_cents": 600000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    validate_success(api.enroll_autopay(loan["id"], make_member_headers(member["id"])))
    priced = fetch_loan(loan["id"])
    assert priced["discount_stack_bps"] == 75
    assert priced["effective_apr_bps"] == 1025

    application = validate_success(api.create_application(
        loan["id"], {"rule_id": rule["id"], "expected_loan_account_version": priced["version"]},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)

    retired = validate_success(api.retire_rule(rule["id"], TEST_USERS["benefits_admin_headers"]))
    assert retired["status"] == "RETIRED"

    rolled = validate_success(api.get_application(application["id"],
                                                  TEST_USERS["benefits_admin_headers"]))
    assert rolled["application_state"] == "ROLLED_BACK"

    after = fetch_loan(loan["id"])
    assert after["discount_stack_bps"] == 0
    assert after["effective_apr_bps"] == 1100, "up from 75 / 1025"


# --------------------------------------------------------------------------
# Calculations and validations
# --------------------------------------------------------------------------

def test_the_churn_score_composes_all_four_factors_and_is_clamped(api):
    """PRD §3.7: "The score sums four contributions: 40 points when the
    enrolment stands in `GRACE` or `LAPSED`; 20 points per missed cycle,
    saturating after 2 missed cycles; 25 points when the member's tier has
    fallen to `NONE` or `BASE`; and 15 points when the qualifying deposit
    balance has dropped below 5,000 dollars. The saturating contributions mean
    the raw score tops out at 120, and the stored score is clamped to 100."

    Design: Corner/calculations/churn_risk_score_composes_all_four_weighted_factors_and_clamps
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-CALC-04", email="ulla.c@x.com")
    create_adopted_holding(member["id"], "INVESTING", 0)
    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"]).json()["data"]
    post_deposit(member["id"], enrollment["id"], 300000, "2026-09-01T00:00:00Z")
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))

    # September qualifies; October is missed, so the enrolment moves into GRACE.
    validate_success(api.set_current_utc({"current_utc": "2026-11-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    # Many more months pass unposted, so the missed-cycle factor saturates.
    validate_success(api.set_current_utc({"current_utc": "2027-03-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    lapsed = validate_success(api.lapse_enrollment(enrollment["id"],
                                                   TEST_USERS["platform_admin_headers"]))
    assert lapsed["status"] == "LAPSED"

    after = fetch_member(member["id"])
    assert after["qualifying_deposit_balance_cents"] == 0, "no balance was ever funded"
    # 40 (lapsed) + 40 (two saturated missed cycles) + 25 (BASE tier) + 15 (balance
    # below the drop floor) = 120 raw, clamped to the stored ceiling of 100.
    assert after["churn_risk_score"] == 100, (
        f"the composed score is clamped at 100, got {after['churn_risk_score']}"
    )


def test_a_direct_deposit_rule_cannot_be_attached_while_the_enrolment_is_in_grace(api):
    """PRD §3.5: "a rule that requires direct deposit cannot be attached while
    the member's enrolment is not active, which is refused with
    `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Corner/validations/cascading_validation_enrollment_state_is_read_before_the_rule_is_priced
    """
    member = register_member(member_number="M-V-005", email="abe.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    rule = create_active_rule("DD_REQ", discount_kind="DIRECT_DEPOSIT",
                              stacking_class="ADDITIVE", discount_bps=50,
                              requires_direct_deposit=True)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "PERSONAL",
         "principal_cents": 500000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    grace = setup_grace_enrollment_for(member["id"])
    assert grace["status"] == "GRACE"

    current = fetch_loan(loan["id"])
    resp = api.create_application(
        loan["id"], {"rule_id": rule["id"], "expected_loan_account_version": current["version"]},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(resp, "ERR_ENROLLMENT_NOT_ACTIVE", expected_status=409)

    settle = validate_success(api.get_pricing_breakdown(loan["id"],
                                                        TEST_USERS["underwriter_headers"]))
    assert settle["stored_bps"] == 0, "no application row was created by the refused attach"
    after = fetch_loan(loan["id"])
    assert after["discount_stack_bps"] == 0, (
        "the requires_direct_deposit rule does not silently price at zero either"
    )


def test_a_direct_deposit_rule_prices_only_for_the_member_with_an_active_enrolment(api):
    """PRD §2.5: "The candidate pool is every rule that is `ACTIVE`, whose window
    contains the current logical instant under the half-open convention that the
    start is inclusive and the end is exclusive, whose `min_member_tier` is at or
    below the member's current tier, and which either does not require direct
    deposit or requires it while the member's enrolment is `ACTIVE`."

    Design: Corner/validations/conditional_direct_deposit_requirement_changes_the_rule_set_by_member
    """
    create_active_rule("COND_DD_50", discount_kind="DIRECT_DEPOSIT",
                       stacking_class="ADDITIVE", discount_bps=50,
                       requires_direct_deposit=True)

    with_deposit = register_member(member_number="M-V-007A", email="cal.a@x.com")
    holding_a = create_adopted_holding(with_deposit["id"], "LENDING", 0)
    loan_a = validate_success(api.create_loan_account(
        {"member_id": with_deposit["id"], "holding_id": holding_a["id"], "loan_type": "PERSONAL",
         "principal_cents": 300000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    enrollment = api.create_deposit_enrollment(
        {"member_id": with_deposit["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"]).json()["data"]
    post_deposit(with_deposit["id"], enrollment["id"], 150000, "2026-09-01T00:00:00Z")
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))

    without_deposit = register_member(member_number="M-V-007B", email="dee.a@x.com")
    holding_b = create_adopted_holding(without_deposit["id"], "LENDING", 0)
    loan_b = validate_success(api.create_loan_account(
        {"member_id": without_deposit["id"], "holding_id": holding_b["id"], "loan_type": "PERSONAL",
         "principal_cents": 300000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)

    priced = fetch_loan(loan_a["id"])
    assert priced["discount_stack_bps"] == 50, "the flag is satisfied, so the rule prices"
    assert priced["effective_apr_bps"] == 1050

    unpriced = fetch_loan(loan_b["id"])
    assert unpriced["discount_stack_bps"] == 0, (
        "the flag silently removes the rule from the candidate pool; no error is raised"
    )
    assert unpriced["effective_apr_bps"] == 1100


def test_the_stack_cap_is_applied_silently_and_the_diagnostic_shows_both_figures(api):
    """PRD §3.5: "The surviving magnitudes are summed and the sum is capped at
    400 basis points; the capped value is what the loan stores as its discount
    stack."
    PRD §3.5: "A request that asks to store an uncapped stack above the ceiling
    instead of accepting the applied cap is refused with `ERR_STACK_CAP_EXCEEDED`;
    the cap itself is applied silently rather than rejected."

    Design: Corner/validations/aggregate_discount_stack_cap_is_validated_across_the_whole_application_set
    """
    setup = setup_cumulative_autopay_stack(base_apr_bps=1200, base_bps=350, autopay_bps=0)
    loan = setup["loan"]
    assert loan["discount_stack_bps"] == 350, "two live classes before the third is added"

    create_active_rule("AGG_CC_100", discount_kind="PROMOTIONAL",
                       stacking_class="CAP_CONTRIBUTING", discount_bps=100)

    after = fetch_loan(loan["id"])
    breakdown = validate_success(api.get_pricing_breakdown(loan["id"],
                                                           TEST_USERS["underwriter_headers"]))
    assert breakdown["uncapped_bps"] == 450, "the raw rule arithmetic crosses the ceiling"
    assert breakdown["stored_bps"] == 400, "the cap is applied rather than rejected"
    assert after["discount_stack_bps"] == 400


# --------------------------------------------------------------------------
# Notice side effects and cycle resolution
# --------------------------------------------------------------------------

def test_a_recovery_from_grace_queues_a_rate_step_up_notice(api):
    """PRD §3.3: "While the enrolment sits in grace, a fresh qualifying deposit
    posted before `grace_deadline_at` returns it to `ACTIVE`, resets
    `missed_cycle_count`, recomputes `consecutive_qualifying_months`, restores
    every `PENDING_REQUALIFICATION` direct-deposit entitlement to `GRANTED`, and
    swaps any queued rate-step-down notice for a rate-step-up notice."

    Design: Corner/state_machines/deposit_recovery_queues_a_rate_step_up_notice
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-S-015", email="rin.c@x.com")
    holding = create_adopted_holding(member["id"], "BANKING", 0)
    grace = enrollment_in_grace(member["id"], holding["id"],
                                required_monthly_amount_cents=100000)
    assert grace["status"] == "GRACE"

    post_deposit(member["id"], grace["id"], 200000, "2026-11-05T00:00:00Z",
                 holding_id=holding["id"])
    recovered = validate_success(api.get_deposit_enrollment(grace["id"],
                                                            TEST_USERS["platform_admin_headers"]))
    assert recovered["status"] == "ACTIVE"

    queued = validate_success(api.list_churn_notices(
        TEST_USERS["platform_admin_headers"],
        params={"member_id": member["id"], "notice_type": "RATE_STEP_UP", "status": "QUEUED"}))
    assert len(queued) == 1, (
        "the recovery hop is the transition that produces the rate-step-up notice"
    )
    assert queued[0]["member_id"] == member["id"]
    assert queued[0]["status"] == "QUEUED"


def test_a_failed_cycle_can_be_remediated_and_then_closed_into_a_successor(api):
    """PRD §3.6: "An operator opens a remediation window, moving the cycle to
    `REMEDIATION`, extending its `due_at` by 30 days, and queuing a
    requalification-reminder notice with a tier-downgrade reason."
    PRD §3.6: "An operator closes a cycle that is `PASSED` or `FAILED`, refreshing
    `evaluated_at`, moving it to `CLOSED`, and immediately opening a successor
    cycle with the next index, an `opened_at` at the current instant and a
    `due_at` 90 days out."

    Design: Corner/state_machines/requalification_failed_then_remediation_then_passed_resolves_the_cycle
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-S-007", email="jonas.c@x.com")
    create_adopted_holding(member["id"], "BANKING", 100000)
    fresh = fetch_member(member["id"])
    cycle = validate_success(api.open_requalification_cycle(
        member["id"], {"expected_member_version": fresh["version"]},
        TEST_USERS["platform_admin_headers"]), expected_status=201)
    assert cycle["cycle_index"] == 1
    assert cycle["status"] == "OPEN"

    # Past the due instant with no qualifying months: the cycle fails.
    validate_success(api.set_current_utc({"current_utc": "2026-12-02T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    failed = validate_success(api.evaluate_cycle(cycle["id"], TEST_USERS["platform_admin_headers"]))
    assert failed["status"] == "FAILED"
    assert failed["evaluated_at"] is not None

    remediated = validate_success(api.open_remediation(cycle["id"],
                                                       TEST_USERS["platform_admin_headers"]))
    assert remediated["status"] == "REMEDIATION"
    assert remediated["due_at"] > failed["due_at"], "the remediation window extends the due instant"

    reminders = validate_success(api.list_churn_notices(
        TEST_USERS["platform_admin_headers"],
        params={"member_id": member["id"], "notice_type": "REQUALIFICATION_REMINDER"}))
    assert reminders, "opening remediation queues a requalification reminder"

    # Past the extended due instant without the months being met: it fails again.
    validate_success(api.set_current_utc({"current_utc": "2027-03-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    refailed = validate_success(api.evaluate_cycle(cycle["id"],
                                                   TEST_USERS["platform_admin_headers"]))
    assert refailed["status"] == "FAILED"

    successor = validate_success(api.close_cycle(cycle["id"], TEST_USERS["platform_admin_headers"]))
    closed = validate_success(api.get_requalification_cycle(cycle["id"],
                                                            TEST_USERS["platform_admin_headers"]))
    assert closed["status"] == "CLOSED"
    assert closed["evaluated_at"] is not None
    assert successor["status"] == "OPEN"
    assert successor["cycle_index"] == 2, "the successor carries the next index"
    assert successor["opened_at"] == "2027-03-01T00:00:00Z"
    assert successor["due_at"] == "2027-05-30T00:00:00Z", "the successor's window is 90 days out"

    cycles = validate_success(api.list_requalification_cycles(
        TEST_USERS["platform_admin_headers"], params={"member_id": member["id"]}))
    assert len(cycles) == 2


def test_reset_to_prospect_is_refused_while_the_member_still_holds_a_product(api):
    """PRD §3.7: "a lapsed member holding no adopted products may instead be
    reset to `PROSPECT`, which clears `member_since_at` and forces the tier to
    `NONE`."
    PRD §2.9: "6. The target resource is in a state that permits the requested
    transition, else `ERR_INVALID_STATE`; this applies to every state-transition
    operation."

    Design: Corner/state_machines/member_reset_to_prospect_with_products_is_refused
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-S-013", email="priya.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    enrollment = api.create_deposit_enrollment(
        {"member_id": member["id"], "required_monthly_amount_cents": 100000},
        TEST_USERS["platform_admin_headers"]).json()["data"]
    post_deposit(member["id"], enrollment["id"], 200000, "2026-09-01T00:00:00Z")
    validate_success(api.activate_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    validate_success(api.set_current_utc({"current_utc": "2026-11-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    validate_success(api.set_current_utc({"current_utc": "2027-01-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    validate_success(api.lapse_enrollment(enrollment["id"], TEST_USERS["platform_admin_headers"]))
    lapsed = validate_success(api.detect_churn(member["id"], TEST_USERS["platform_admin_headers"]))
    assert lapsed["member_status"] == "MEMBER_LAPSED"

    resp = api.reset_member_to_prospect(member["id"], TEST_USERS["platform_admin_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    still = fetch_member(member["id"])
    assert still["member_status"] == "MEMBER_LAPSED"
    assert still["member_since_at"] is not None

    reinstated = validate_success(api.reinstate_member(member["id"],
                                                       TEST_USERS["platform_admin_headers"]))
    assert reinstated["member_status"] == "MEMBER_ACTIVE", (
        "the other exit from MEMBER_LAPSED succeeds from the same state"
    )
    assert fetch_holding(holding["id"])["adoption_status"] == "ADOPTED"


def test_an_entitlement_declared_over_a_pending_holding_is_admitted(api):
    """PRD §3.1: "A newly declared entitlement sits in `PENDING` until its
    unlocking condition is met."
    PRD §2.6: "The loan rate discount, the career-coaching credit, the investing
    fee waiver, and the rewards multiplier are unlocked when the source holding
    is `ADOPTED`."

    Design: Corner/entities/holding_create_omitting_balance_defaults_it_to_zero
    """
    member = register_member(member_number="M-C-006B", email="wen.c.b@x.com")
    holding = api.create_holding(create_holding_payload(member["id"], product_line="CAREER"),
                                 TEST_USERS["platform_admin_headers"]).json()["data"]
    assert holding["adoption_status"] == "PENDING"

    entitlement = validate_success(api.create_entitlement(
        member["id"],
        {"source_holding_id": holding["id"], "benefit_code": "CAREER_COACHING_CREDIT",
         "value_bps": 1},
        TEST_USERS["benefits_admin_headers"],
    ), expected_status=201)
    assert entitlement["entitlement_status"] == "PENDING", (
        "a declared entitlement waits for its unlocking condition"
    )

    validate_success(api.adopt_holding(holding["id"], make_member_headers(member["id"])))
    granted = fetch_entitlement(entitlement["id"])
    assert granted["entitlement_status"] == "GRANTED", (
        "adoption of the source holding is the unlocking event"
    )
    assert granted["granted_at"] is not None
    assert granted["reconciliation_state"] in ("IN_SYNC", "DRIFT_REPORTED", "RECONCILED")

def test_attaching_a_discount_against_a_non_adopted_holding_is_refused(api):
    """PRD §2.9: "7. The holdings referenced by an entitlement or a discount
    application are adopted, else `ERR_HOLDING_NOT_ADOPTED`; this governs
    entitlement reconciliation, discount-application attachment, entitlement
    restoration, and entitlement step-down."

    Design: Corner/validations/entitlement_holding_not_adopted_outranks_duplicate_entitlement
    """
    member = register_member(member_number="M-V-004", email="zia.c@x.com")
    holding = create_adopted_holding(member["id"], "LENDING", 0)
    loan = validate_success(api.create_loan_account(
        {"member_id": member["id"], "holding_id": holding["id"], "loan_type": "PERSONAL",
         "principal_cents": 500000, "base_apr_bps": 1100},
        TEST_USERS["underwriter_headers"],
    ), expected_status=201)
    rule = create_active_rule("SUSP_SRC_50", discount_kind="PROMOTIONAL",
                              stacking_class="ADDITIVE", discount_bps=50)

    suspended = validate_success(api.suspend_holding(holding["id"],
                                                     TEST_USERS["platform_admin_headers"]))
    assert suspended["adoption_status"] == "SUSPENDED"

    current = fetch_loan(loan["id"])
    resp = api.create_application(
        loan["id"], {"rule_id": rule["id"], "expected_loan_account_version": current["version"]},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(resp, "ERR_HOLDING_NOT_ADOPTED", expected_status=409)

    settle = validate_success(api.get_pricing_breakdown(loan["id"],
                                                        TEST_USERS["underwriter_headers"]))
    assert settle["stored_bps"] == 0, "the refused attach created no application row"


def test_a_member_cannot_read_another_members_benefit_summary(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
    acting member entity; every ownership check on a resource that references a
    member compares that resource's member foreign-key field to `X-User-ID`, and
    a mismatch is an `ERR_FORBIDDEN_ROLE` rejection. `Member` is the only
    entity-backed role."

    Design: Corner/rbac/member_cannot_read_another_members_benefit_summary
    """
    first = register_member(member_number="M-R-002A2", email="lena.r2@x.com")
    second = register_member(member_number="M-R-002B2", email="milo.r2@x.com")

    cross = api.get_benefit_summary(second["id"], make_member_headers(first["id"]))
    validate_error(cross, "ERR_FORBIDDEN_ROLE", expected_status=403)

    own = api.get_benefit_summary(second["id"], make_member_headers(second["id"]))
    validate_success(own, expected_status=200)

    operational = api.get_benefit_summary(second["id"], TEST_USERS["benefits_admin_headers"])
    validate_success(operational, expected_status=200)
