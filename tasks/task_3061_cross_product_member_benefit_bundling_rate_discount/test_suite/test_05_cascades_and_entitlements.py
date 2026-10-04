"""Cross-entity cascades and the benefit-entitlement lifecycle."""
from test_helpers import (
    TEST_USERS,
    assert_entitlement,
    create_adopted_holding,
    declare_entitlement,
    fetch_entitlement,
    fetch_holding,
    fetch_loan,
    fetch_member,
    list_applications,
    list_notices,
    make_member_headers,
    register_member,
    setup_deposit_lapse_cascade,
    setup_holding_close_cascade,
    validate_error,
    validate_success,
)


def test_a_deposit_lapse_cascades_into_the_entitlement_and_the_loan_apr(api):
    """PRD §3.3: "A lapse that lands is heavy. Every direct-deposit entitlement
    that was `GRANTED` or `PENDING_REQUALIFICATION` is stepped down with its
    `value_bps` reduced by the 50-basis-point step-down magnitude, floored at
    zero, and stamped with `stepped_down_at`; each of those entitlements'
    banking holdings loses `deposit_rate_eligible`; the member's
    `qualifying_deposit_balance_cents` is recomputed; every loan of the member
    holding `PROVISIONAL` or `FINAL` pricing is repriced, with each applied
    application whose rule requires direct deposit rolled back, the stack and
    effective rate recomputed, final pricing demoted to stepped-down, and the
    pricing timestamp refreshed; a rate-step-down notice linked to the
    stepped-down entitlement is queued".

    Design: Difficulty/transitive_cascade/deposit_lapse_cascade_member_entitlement_application_loan
    """
    setup = setup_deposit_lapse_cascade()
    enrollment = setup["enrollment"]
    before = setup["loan"]
    assert before["pricing_status"] == "FINAL"
    assert before["discount_stack_bps"] == 50
    assert before["effective_apr_bps"] == 1150

    lapsed = validate_success(api.lapse_enrollment(enrollment["id"],
                                                   TEST_USERS["platform_admin_headers"]))
    assert lapsed["status"] == "LAPSED"

    entitlements = validate_success(api.list_entitlements(
        TEST_USERS["benefits_admin_headers"],
        params={"member_id": setup["member"]["id"], "benefit_code": "DIRECT_DEPOSIT"}))
    assert len(entitlements) == 1
    entitlement = entitlements[0]
    assert_entitlement(entitlement)
    assert entitlement["entitlement_status"] == "STEPPED_DOWN"
    assert entitlement["value_bps"] == 0, "50 - 50 floored at zero"
    assert entitlement["stepped_down_at"] is not None

    assert fetch_holding(setup["banking_holding"]["id"])["deposit_rate_eligible"] is False

    apps = list_applications(loan_account_id=before["id"])
    rolled_back = [app for app in apps if app["rule_id"] == setup["rule"]["id"]]
    assert rolled_back and rolled_back[0]["application_state"] == "ROLLED_BACK", (
        "every applied application whose rule requires direct deposit is rolled back"
    )

    after = fetch_loan(before["id"])
    assert after["pricing_status"] == "STEPPED_DOWN"
    assert after["discount_stack_bps"] == 0
    assert after["effective_apr_bps"] == 1200, "up from 50 / 1150"


def test_a_deposit_lapse_queues_a_rate_step_down_notice_linked_to_the_entitlement(api):
    """PRD §3.3: "a rate-step-down notice linked to the stepped-down
    entitlement is queued; and the member's churn score is recomputed, which may
    in turn move the member machine into the at-risk state."

    Design: Difficulty/transitive_cascade/deposit_lapse_cascade_member_entitlement_application_loan
    """
    setup = setup_deposit_lapse_cascade()
    validate_success(api.lapse_enrollment(setup["enrollment"]["id"],
                                          TEST_USERS["platform_admin_headers"]))

    notices = list_notices(setup["member"]["id"], status="QUEUED", notice_type="RATE_STEP_DOWN")
    assert notices, "the lapse must queue a RATE_STEP_DOWN notice"
    stepped = validate_success(api.list_entitlements(
        TEST_USERS["benefits_admin_headers"],
        params={"member_id": setup["member"]["id"], "benefit_code": "DIRECT_DEPOSIT"}))[0]
    linked = [n for n in notices if n.get("related_entitlement_id") == stepped["id"]]
    assert linked, "a RATE_STEP_DOWN notice is linked to the entitlement it concerns"
    notice = linked[0]
    assert notice["reason_code"] == "DEPOSIT_STOPPED", (
        "the reason code records that the deposit stopped"
    )


def test_closing_the_source_holding_revokes_the_benefit_and_reprices_the_loan(api):
    """PRD §3.2: "A successful close stamps `closed_at`, moves the holding to
    `CLOSED`, recomputes the member's `qualifying_deposit_balance_cents`,
    `product_adoption_count`, `product_line_set` and `member_tier`, and revokes
    every entitlement sourced from that holding that was `GRANTED` or
    `PENDING_REQUALIFICATION`."
    PRD §3.2: "When a rate entitlement is revoked, every discount application on
    the member's loans whose rule matches that entitlement's governing rule is
    rolled back, and every loan affected by that rollback has its discount stack
    and effective rate recomputed and its pricing timestamp refreshed."

    Design: Difficulty/transitive_cascade/holding_close_cascade_benefit_revoked_application_rolled_back_loan_repriced
    """
    setup = setup_holding_close_cascade()
    career = setup["career_holding"]
    before = setup["loan"]
    assert before["discount_stack_bps"] == 100
    assert before["effective_apr_bps"] == 1200
    assert fetch_holding(setup["lending_holding"]["id"])["reunderwriting_permitted"] is True

    closed = validate_success(api.close_holding(career["id"], make_member_headers(setup["member"]["id"])))
    assert closed["adoption_status"] == "CLOSED"
    assert closed["closed_at"] == "2026-09-01T00:00:00Z"

    member = fetch_member(setup["member"]["id"])
    assert member["product_adoption_count"] == 1, "only the LENDING holding remains adopted"
    assert member["member_tier"] == "BASE"

    entitlement = fetch_entitlement(setup["entitlement"]["id"])
    assert entitlement["entitlement_status"] == "REVOKED", (
        "the entitlement sourced from the closed holding is revoked"
    )

    apps = list_applications(loan_account_id=before["id"])
    match = [app for app in apps if app["rule_id"] == setup["rule"]["id"]]
    assert match and match[0]["application_state"] == "ROLLED_BACK"

    after = fetch_loan(before["id"])
    assert after["discount_stack_bps"] == 0
    assert after["effective_apr_bps"] == 1300, "the discount no longer prices"


def test_the_holding_close_cascade_does_not_over_reach_the_lending_side(api):
    """PRD §3.2: "suspension, by contrast, always has a way back", and closure
    revokes only "every entitlement sourced from that holding".
    PRD §3.5: "Finalization freezes the discount stack at the snapshots captured
    when the loan was finalized and marks the linked holding as permitting
    underwriting reuse."

    Design: Difficulty/transitive_cascade/holding_close_cascade_benefit_revoked_application_rolled_back_loan_repriced
    """
    setup = setup_holding_close_cascade()
    validate_success(api.close_holding(setup["career_holding"]["id"],
                                       make_member_headers(setup["member"]["id"])))

    lending = fetch_holding(setup["lending_holding"]["id"])
    assert lending["adoption_status"] == "ADOPTED", "the untouched LENDING holding is unmoved"
    assert lending["reunderwriting_permitted"] is True, (
        "the cascade does not over-reach: the lending holding keeps its reuse permission"
    )

    entitlements = validate_success(api.list_entitlements(
        TEST_USERS["benefits_admin_headers"],
        params={"member_id": setup["member"]["id"]}))
    summary = validate_success(api.get_benefit_summary(setup["member"]["id"],
                                                       TEST_USERS["benefits_admin_headers"]))
    assert summary["revoked_count"] >= 1
    for row in entitlements:
        if row["source_holding_id"] == setup["career_holding"]["id"]:
            assert row["entitlement_status"] == "REVOKED"


# --------------------------------------------------------------------------
# Entitlement lifecycle
# --------------------------------------------------------------------------

def test_entitlement_revocation_is_terminal_and_blocks_restore(api):
    """PRD §2.6: "Its `entitlement_status` runs through `PENDING`, `GRANTED`,
    `PENDING_REQUALIFICATION`, `STEPPED_DOWN`, and `REVOKED`."
    PRD §2.9: "6. The target resource is in a state that permits the requested
    transition, else `ERR_INVALID_STATE`; this applies to every state-transition
    operation."

    Design: Corner/state_machines/entitlement_revocation_is_terminal_and_blocks_restore
    """
    member = register_member(member_number="M-S-010", email="mona.c@x.com")
    holding = create_adopted_holding(member["id"], "INVESTING", 0)
    entitlement = declare_entitlement(member["id"], holding["id"], "INVESTING_FEE_WAIVER",
                                      value_bps=10)

    validate_success(api.close_holding(holding["id"], make_member_headers(member["id"])))
    revoked = fetch_entitlement(entitlement["id"])
    assert revoked["entitlement_status"] == "REVOKED"

    resp = api.restore_entitlement(entitlement["id"], TEST_USERS["benefits_admin_headers"])
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    still = fetch_entitlement(entitlement["id"])
    assert still["entitlement_status"] == "REVOKED"
    assert still["value_bps"] == 10
    assert fetch_member(member["id"])["benefit_entitlement_state"] == "NONE", (
        "the revoked row's holding is CLOSED and excluded from the rollup"
    )


def test_reconciliation_state_detects_drift_and_then_repairs_it(api):
    """PRD §2.6: "The entitlement's reconciliation state is derived by comparing
    its stored status against that guard verdict: a row whose stored status
    disagrees with its guard verdict and has not yet been rewritten reads
    `DRIFT_REPORTED`; a row rewritten by the reconciliation operation reads
    `RECONCILED`; and a row that already agrees reads `IN_SYNC`."

    Design: Corner/cross_cutting_layers/derived_field_reconciliation_between_entitlement_rows_and_the_member_rollup
    """
    setup = setup_deposit_lapse_cascade()
    validate_success(api.lapse_enrollment(setup["enrollment"]["id"],
                                          TEST_USERS["platform_admin_headers"]))
    stepped = validate_success(api.list_entitlements(
        TEST_USERS["benefits_admin_headers"],
        params={"member_id": setup["member"]["id"], "benefit_code": "DIRECT_DEPOSIT"}))[0]
    assert stepped["reconciliation_state"] == "DRIFT_REPORTED", (
        "the stored status disagrees with the guard verdict, which reads the enrolment as inactive"
    )

    rows = validate_success(api.reconcile_entitlements(setup["member"]["id"],
                                                       TEST_USERS["compliance_officer_headers"]))
    rewritten = [row for row in rows if row["id"] == stepped["id"]]
    assert rewritten, "the reconcile operation returns the member's entitlement rows"
    assert rewritten[0]["reconciliation_state"] == "RECONCILED"

    after = fetch_entitlement(stepped["id"])
    assert after["reconciliation_state"] == "IN_SYNC", "the rewritten row now agrees with its guard"


def test_entitlement_state_rollup_moves_from_full_to_partial_as_rows_step_down(api):
    """PRD §2.6: "At the member level, the entitlement state is recomputed as a
    rollup over the member's entitlements whose source holding is not closed: a
    lapsed member reads `SUSPENDED`; otherwise, if every counted entitlement is
    granted and at least one is counted, the state is `FULL`; otherwise, if at
    least one counted entitlement is granted, the state is `PARTIAL`; otherwise
    it is `NONE`."

    Design: Corner/calculations/benefit_entitlement_rollup_goes_none_partial_full_as_granted_rows_accumulate
    """
    validate_success(api.set_current_utc({"current_utc": "2026-09-01T00:00:00Z"},
                                         TEST_USERS["platform_admin_headers"]))
    member = register_member(member_number="M-CALC-07", email="xena.c@x.com")
    career = create_adopted_holding(member["id"], "CAREER", 0)
    lending = create_adopted_holding(member["id"], "LENDING", 0)
    career_ent = declare_entitlement(member["id"], career["id"], "CAREER_COACHING_CREDIT",
                                     value_bps=1)
    declare_entitlement(member["id"], lending["id"], "LOAN_RATE_DISCOUNT", value_bps=25)

    validate_success(api.reconcile_entitlements(member["id"], TEST_USERS["compliance_officer_headers"]))
    assert fetch_member(member["id"])["benefit_entitlement_state"] == "FULL", (
        "both counted rows are granted"
    )

    validate_success(api.step_down_entitlement(career_ent["id"], TEST_USERS["benefits_admin_headers"]))
    assert fetch_member(member["id"])["benefit_entitlement_state"] == "PARTIAL", (
        "one of the two counted rows is still granted"
    )
    summary = validate_success(api.get_benefit_summary(member["id"],
                                                       TEST_USERS["benefits_admin_headers"]))
    assert summary["granted_count"] == 1
    assert summary["stepped_down_count"] == 1