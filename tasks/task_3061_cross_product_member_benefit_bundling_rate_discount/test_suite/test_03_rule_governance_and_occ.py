"""Rate-discount rule governance, the validation ladder, and the OCC guards."""
from test_helpers import (
    TEST_USERS,
    activate_rule,
    assert_rule,
    create_active_rule,
    create_rule_payload,
    fetch_loan,
    fetch_member,
    fetch_rule,
    list_holdings,
    make_member_headers,
    setup_cumulative_autopay_stack,
    setup_cross_sell_member,
    validate_error,
    validate_success,
)


def test_duplicate_rule_code_is_rejected_regardless_of_status(api):
    """PRD §2.5: "It is created with a stable, human-readable `rule_code` that
    is unique across all rules regardless of status".
    PRD §3.4: "a `rule_code` that already exists in any status is refused with
    `ERR_DUPLICATE_RULE_CODE`".

    Design: Corner/errors/duplicate_rule_code_is_rejected_regardless_of_status
    """
    first = validate_success(
        api.create_rule(
            create_rule_payload("DUP_ONE", discount_kind="AUTOPAY",
                                stacking_class="ADDITIVE", discount_bps=20),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )
    activate_rule(first["id"])
    validate_success(api.retire_rule(first["id"], TEST_USERS["benefits_admin_headers"]))
    assert fetch_rule(first["id"])["status"] == "RETIRED"

    resp = api.create_rule(
        create_rule_payload("DUP_ONE", discount_kind="PROMOTIONAL",
                            stacking_class="BASE", discount_bps=30,
                            effective_from="2027-02-01T00:00:00Z",
                            effective_to="2027-06-01T00:00:00Z"),
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(resp, "ERR_DUPLICATE_RULE_CODE", expected_status=409)

    retained = validate_success(api.list_rules(TEST_USERS["benefits_admin_headers"],
                                               params={"status": "RETIRED"}))
    assert len(retained) == 1
    assert retained[0]["rule_code"] == "DUP_ONE"


def test_editing_a_rule_into_a_stacking_cycle_is_refused(api):
    """PRD §3.4: "a stacking chain that revisits a rule is refused with
    `ERR_SELF_STACK_CYCLE`".
    PRD §3.4: "A draft may subsequently be edited — its `stacks_on_rule_id`, its
    `discount_bps`, or the end of its window `effective_to` — and each edit
    re-validates the whole stacking graph for cycles and for class agreement."

    Design: Corner/errors/self_stack_cycle_is_rejected_when_a_rule_joins_itself
    """
    root = validate_success(
        api.create_rule(
            create_rule_payload("ROOT_A", discount_kind="AUTOPAY",
                                stacking_class="ADDITIVE", discount_bps=20,
                                effective_from="2027-02-01T00:00:00Z",
                                effective_to="2027-04-01T00:00:00Z"),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )
    child = validate_success(
        api.create_rule(
            create_rule_payload("CYCLE_B", discount_kind="AUTOPAY",
                                stacking_class="ADDITIVE", discount_bps=25,
                                effective_from="2027-04-02T00:00:00Z",
                                effective_to="2027-06-01T00:00:00Z",
                                stacks_on_rule_id=root["id"]),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )
    assert child["stacks_on_rule_id"] == root["id"]

    resp = api.update_rule(root["id"], {"stacks_on_rule_id": child["id"]},
                           TEST_USERS["benefits_admin_headers"])
    validate_error(resp, "ERR_SELF_STACK_CYCLE", expected_status=422)

    assert fetch_rule(root["id"])["stacks_on_rule_id"] is None, (
        "the refused edit must leave the stacking graph acyclic"
    )
    dependent = validate_success(
        api.list_rules(TEST_USERS["benefits_admin_headers"],
                       params={"stacks_on_rule_id": root["id"]})
    )
    assert len(dependent) == 1


def test_activating_a_rule_joined_to_a_draft_parent_is_refused(api):
    """PRD §3.4: "Activation additionally requires that the rule's declared
    stacking parent exists and is not itself still a draft; a rule that stacks
    upon a missing or draft parent is refused with
    `ERR_ACTIVE_RULE_ON_UNPRICED_LOAN`."

    Design: Corner/errors/activating_a_rule_joined_to_a_draft_rule_is_refused
    """
    parent = validate_success(
        api.create_rule(
            create_rule_payload("DP_ROOT", discount_kind="AUTOPAY",
                                stacking_class="ADDITIVE", discount_bps=20,
                                effective_from="2027-01-01T00:00:00Z",
                                effective_to="2028-01-01T00:00:00Z"),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )
    child = validate_success(
        api.create_rule(
            create_rule_payload("DP_CHILD", discount_kind="AUTOPAY",
                                stacking_class="ADDITIVE", discount_bps=15,
                                effective_from="2028-01-02T00:00:00Z",
                                effective_to="2029-01-02T00:00:00Z",
                                stacks_on_rule_id=parent["id"]),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )
    assert fetch_rule(parent["id"])["status"] == "DRAFT"

    resp = api.activate_rule(child["id"], TEST_USERS["benefits_admin_headers"])
    validate_error(resp, "ERR_ACTIVE_RULE_ON_UNPRICED_LOAN", expected_status=422)
    assert fetch_rule(child["id"])["status"] == "DRAFT"

    # Activating the parent first clears the blocking condition.
    activate_rule(parent["id"])
    activated = validate_success(api.activate_rule(child["id"], TEST_USERS["benefits_admin_headers"]))
    assert_rule(activated)
    assert activated["status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------

def test_requalification_cycle_open_with_a_stale_member_version_is_refused(api):
    """PRD §2.8: "When a client opens a requalification cycle for a member, the
    request body must carry `expected_member_version` matching the member's
    current `version`. If the member's version has advanced since the client
    last read it, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)".
    PRD §3.6: "Opening a superseding cycle increments the member's version."

    Design: Corner/cross_cutting_layers/stale_member_version_on_requalification_cycle_open_returns_stale_version
    """
    setup = setup_cumulative_autopay_stack()
    member = fetch_member(setup["member"]["id"])
    stale_version = member["version"]

    first = api.open_requalification_cycle(
        member["id"], {"expected_member_version": stale_version},
        TEST_USERS["platform_admin_headers"],
    )
    validate_success(first, expected_status=201)

    advanced = fetch_member(member["id"])
    assert advanced["version"] > stale_version, "opening a cycle advances the member's version"

    resp = api.open_requalification_cycle(
        member["id"], {"expected_member_version": stale_version},
        TEST_USERS["platform_admin_headers"],
    )
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)

    cycles = validate_success(api.list_requalification_cycles(
        TEST_USERS["platform_admin_headers"], params={"member_id": member["id"]}))
    assert len(cycles) == 1, "the refused open must not have created a second cycle"


def test_requalification_cycle_open_with_the_current_version_succeeds(api):
    """PRD §3.6: "A successfully opened cycle is `OPEN`, with an `opened_at` at
    the current instant, a `due_at` 90 days out, and a `cycle_index` one greater
    than the member's greatest existing index."

    Design: Corner/cross_cutting_layers/stale_member_version_on_requalification_cycle_open_returns_stale_version
    """
    setup = setup_cumulative_autopay_stack()
    member = fetch_member(setup["member"]["id"])

    resp = api.open_requalification_cycle(
        member["id"], {"expected_member_version": member["version"]},
        TEST_USERS["platform_admin_headers"],
    )
    cycle = validate_success(resp, expected_status=201)
    assert cycle["status"] == "OPEN"
    assert cycle["cycle_index"] == 1
    assert cycle["opened_at"] == "2026-09-01T00:00:00Z"
    assert cycle["due_at"] == "2026-12-01T00:00:00Z"
    assert cycle["evaluated_at"] is None

    after = fetch_member(member["id"])
    assert after["version"] > member["version"]


def test_attaching_an_application_with_a_fresh_version_passes_the_occ_rung(api):
    """PRD §2.8: "When a client attaches a discount application to a loan, the
    request body must carry `expected_loan_account_version` matching the loan
    account's `version`; a mismatch is likewise rejected with `ERR_STALE_VERSION`
    (HTTP 412), so the caller cannot price against a loan it has not observed."
    PRD §2.9: "5. The optimistic-concurrency guard fires, else `ERR_STALE_VERSION`;
    this rung governs only the cycle-opening and application-attaching operations
    named in §2.8."
    PRD §2.9: "12. No applied discount application already occupies the same
    loan-and-rule pair, else `ERR_DUPLICATE_DISCOUNT_APPLICATION`."

    Design: Corner/cross_cutting_layers/correct_version_on_the_occ_write_endpoint_succeeds_and_advances_version
    """
    setup = setup_cumulative_autopay_stack(base_apr_bps=1200, base_bps=30, autopay_bps=20)
    loan = fetch_loan(setup["loan"]["id"])
    stale_version = loan["version"]
    rule_id = setup["rules"][0]["id"]

    # A pricing mutation advances the loan's version. The autopay standing changes
    # from ENROLLED to SUSPENDED, which refreshes the loan row.
    validate_success(api.suspend_autopay(loan["id"], TEST_USERS["platform_admin_headers"]))
    advanced = fetch_loan(loan["id"])
    assert advanced["version"] > stale_version, "an autopay change refreshes the loan row"

    stale = api.create_application(
        loan["id"], {"rule_id": rule_id, "expected_loan_account_version": stale_version},
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(stale, "ERR_STALE_VERSION", expected_status=412)

    # A freshly created rule is not yet in the loan's candidate pool, so an attach
    # carrying the current version clears rung 5 and cannot trip a later rung.
    fresh_rule = create_active_rule("OCC_FRESH_B", discount_kind="PROMOTIONAL",
                                    stacking_class="CAP_CONTRIBUTING", discount_bps=10)
    current = fetch_loan(loan["id"])
    retry = api.create_application(
        loan["id"], {"rule_id": fresh_rule["id"],
                     "expected_loan_account_version": current["version"]},
        TEST_USERS["benefits_admin_headers"],
    )
    assert retry.status_code != 412, (
        f"a fresh version must pass the OCC rung, got {retry.status_code}: {retry.text[:300]}"
    )
    validate_success(retry, expected_status=201)


# --------------------------------------------------------------------------
# Validation-ladder precedence on the cross-sell decision
# --------------------------------------------------------------------------

def test_state_precondition_outranks_compliance_on_cross_sell_decide(api):
    """PRD §2.9: "6. The target resource is in a state that permits the
    requested transition, else `ERR_INVALID_STATE`; this applies to every
    state-transition operation."
    PRD §2.9: "8. A cross-sell decision would not condition credit on a banking
    or investing purchase, else `ERR_CREDIT_CONDITIONING_BLOCKED`."
    PRD §3.9: "A check that has reached any of those three outcomes no longer
    occupies the pending state".

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_compliance_on_cross_sell_decide
    """
    setup = setup_cross_sell_member("INVESTING", consent_recorded=False)
    check = setup["check"]
    assert check["conditioning_blocked"] is True, (
        "an INVESTING target with no consent on file is flagged as blocked"
    )

    blocked = validate_success(
        api.decide_cross_sell_check(check["id"], {"outcome": "BLOCKED"},
                                    TEST_USERS["compliance_officer_headers"])
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["decided_at"] is not None
    assert blocked["decided_by"] is not None

    resp = api.decide_cross_sell_check(check["id"], {"outcome": "CLEARED"},
                                       TEST_USERS["compliance_officer_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    after = validate_success(api.get_cross_sell_check(check["id"],
                                                      TEST_USERS["compliance_officer_headers"]))
    assert after["status"] == "BLOCKED", "the terminal outcome must not be overwritten"
    lendings = list_holdings(setup["member"]["id"], product_line="LENDING")
    for holding in lendings:
        assert holding["cross_sell_eligible"] is False, (
            "a BLOCKED decision sets cross-sell eligibility false for the target line's holdings"
        )


def test_blocking_a_check_whose_conditioning_is_not_blocked_is_refused(api):
    """PRD §3.9: "Blocking the check requires that conditioning is blocked, and
    moves the check to `BLOCKED`; a block is refused with
    `ERR_CREDIT_CONDITIONING_BLOCKED` when conditioning is not in fact blocked."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_compliance_on_cross_sell_decide
    """
    setup = setup_cross_sell_member("INVESTING", consent_recorded=True)
    check = setup["check"]
    assert check["conditioning_blocked"] is False

    resp = api.decide_cross_sell_check(check["id"], {"outcome": "BLOCKED"},
                                       TEST_USERS["compliance_officer_headers"])
    validate_error(resp, "ERR_CREDIT_CONDITIONING_BLOCKED", expected_status=422)

    after = validate_success(api.get_cross_sell_check(check["id"],
                                                      TEST_USERS["compliance_officer_headers"]))
    assert after["status"] == "PENDING", "a refused decision must leave the check pending"
    assert after["decided_at"] is None

def test_a_rule_window_that_merely_touches_a_live_rules_window_is_refused(api):
    """PRD §3.4: "Two rules of the same discount kind whose validity windows
    approach closer than one day are refused with `ERR_RULE_WINDOW_OVERLAP`; the
    comparison is made against every non-retired rule, and because the windows
    are half-open, two windows that merely touch have a gap of zero and are
    therefore refused, while a full one-day gap is accepted."

    Design: Difficulty/priority_pair_validation_conflict/rule_window_overlap_outranks_join_to_a_draft_rule_on_activation
    """
    existing = validate_success(
        api.create_rule(
            create_rule_payload("OVL_A", discount_kind="AUTOPAY",
                                stacking_class="ADDITIVE", discount_bps=40,
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2027-01-01T00:00:00Z"),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )
    activate_rule(existing["id"])

    # This window starts exactly where the live one ends, so the gap is zero.
    touching = api.create_rule(
        create_rule_payload("OVL_A2", discount_kind="AUTOPAY",
                            stacking_class="ADDITIVE", discount_bps=35,
                            effective_from="2027-01-01T00:00:00Z",
                            effective_to="2027-06-01T00:00:00Z"),
        TEST_USERS["benefits_admin_headers"],
    )
    validate_error(touching, "ERR_RULE_WINDOW_OVERLAP", expected_status=409)

    # A full one-day gap clears the same comparison.
    spaced = api.create_rule(
        create_rule_payload("OVL_A3", discount_kind="AUTOPAY",
                            stacking_class="ADDITIVE", discount_bps=35,
                            effective_from="2027-01-02T00:00:00Z",
                            effective_to="2027-06-01T00:00:00Z"),
        TEST_USERS["benefits_admin_headers"],
    )
    validate_success(spaced, expected_status=201)


def test_joining_a_draft_parent_is_refused_when_the_window_does_not_collide(api):
    """PRD §3.4: "Activation additionally requires that the rule's declared
    stacking parent exists and is not itself still a draft; a rule that stacks
    upon a missing or draft parent is refused with
    `ERR_ACTIVE_RULE_ON_UNPRICED_LOAN`."

    Design: Difficulty/priority_pair_validation_conflict/rule_window_overlap_outranks_join_to_a_draft_rule_on_activation
    """
    parent = validate_success(
        api.create_rule(
            create_rule_payload("DRAFT_PARENT_B", discount_kind="AUTOPAY",
                                stacking_class="ADDITIVE", discount_bps=10,
                                effective_from="2026-01-01T00:00:00Z",
                                effective_to="2027-01-01T00:00:00Z"),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )
    assert parent["status"] == "DRAFT"
    child = validate_success(
        api.create_rule(
            create_rule_payload("OVL_B2", discount_kind="PROMOTIONAL",
                                stacking_class="ADDITIVE", discount_bps=35,
                                effective_from="2027-03-01T00:00:00Z",
                                effective_to="2027-06-01T00:00:00Z",
                                stacks_on_rule_id=parent["id"]),
            TEST_USERS["benefits_admin_headers"],
        ),
        expected_status=201,
    )

    resp = api.activate_rule(child["id"], TEST_USERS["benefits_admin_headers"])
    validate_error(resp, "ERR_ACTIVE_RULE_ON_UNPRICED_LOAN", expected_status=422)
    assert fetch_rule(child["id"])["status"] == "DRAFT"
    assert fetch_rule(parent["id"])["status"] == "DRAFT"
