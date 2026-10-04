"""Compensating reversals and the quantities they must restore exactly.

Crediting a quality claim unwinds fulfilments that already happened, and it
must put back the exact scratch values those redemptions carried. The license
counters are conserved across an approve/return-to-draft cycle for the same
reason.
"""

from test_helpers import (
    approve_artwork_for_set,
    approve_card_set,
    build_approved_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    issue_plain_redemption,
    submit_card_set_for_review,
    TEST_USERS,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def _line_with_waiting_redemption(api):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    return license_obj, line, card_set


def test_credit_returns_a_fulfilled_redemption_to_issued(api):
    """PRD §3.7: "every redemption whose `card_set_id` is this claim's card set
    and whose status is `FULFILLED` is returned to `ISSUED`".

    Design: Difficulty/compensating_invariant/quality_credit_restores_every_redemption_scratch_value_exactly
    """
    from test_helpers import build_fulfilled_redemption

    scenario = build_fulfilled_redemption(api, estimated_value_cents=150000)
    card_set = scenario["card_set"]
    redemption = validate_success(
        api.get_redemption(
            scenario["redemption"]["id"], TEST_USERS["redemption_analyst_headers"]
        )
    )
    assert redemption["status"] == "FULFILLED"

    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 40,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(claim["id"], QA))
    credited = validate_success(api.credit_quality_claim(claim["id"], QA))
    assert credited["status"] == "CREDITED"

    after = validate_success(
        api.get_redemption(redemption["id"], TEST_USERS["redemption_analyst_headers"])
    )
    assert after["status"] == "ISSUED"


def test_credit_restores_the_scratch_value_the_redemption_carried(api):
    """PRD §3.7: "crediting a claim against a set returns every redemption
    under that set that is currently `FULFILLED` back to `ISSUED`, restoring
    each redemption's `estimated_value_cents` to the value it held when the
    reversal began".

    PRD §3.6: "The reverse direction exists too and is equally deliberate:
    fulfilling, cancelling, closing or acknowledging a redemption all recompute
    counts but do not touch the set's `version`, because a count refresh is not
    a state change on the set".

    Design: Difficulty/compensating_invariant/quality_credit_restores_every_redemption_scratch_value_exactly
    """
    from test_helpers import build_fulfilled_redemption

    scenario = build_fulfilled_redemption(api, estimated_value_cents=500000)
    card_set = scenario["card_set"]
    before = validate_success(api.get_card_set(card_set["id"], PLANNER))

    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 40,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(claim["id"], QA))
    validate_success(api.credit_quality_claim(claim["id"], QA))

    after = validate_success(api.get_card_set(card_set["id"], PLANNER))
    assert after["version"] == before["version"] + 1, (
        "the compensating reversal explicitly changes the set's own state, "
        "so it is the one path that bumps the set's version"
    )
    redemption = validate_success(
        api.get_redemption(
            scenario["redemption"]["id"], TEST_USERS["redemption_analyst_headers"]
        )
    )
    assert redemption["estimated_value_cents"] == 500000, "restored exactly"


def test_credit_raises_the_sets_outstanding_redemption_count(api):
    """PRD §3.7: "the set's `autograph_redemptions_outstanding` is recomputed;
    and the set's `version` is advanced by one."

    Design: Difficulty/compensating_invariant/quality_credit_restores_every_redemption_scratch_value_exactly
    """
    from test_helpers import build_fulfilled_redemption

    scenario = build_fulfilled_redemption(
        api, estimated_value_cents=150000, redemption_code="RDM-8001"
    )
    card_set = scenario["card_set"]
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 40,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(claim["id"], QA))
    validate_success(api.credit_quality_claim(claim["id"], QA))

    after = validate_success(api.get_card_set(card_set["id"], PLANNER))
    assert after["autograph_redemptions_outstanding"] == 1, (
        "the reversed redemption is outstanding once more"
    )


def test_an_incremental_counter_would_drift_on_the_credit_cycle(api):
    """Aggregate counters — how many sets sit under a license, how many redemptions
    remain outstanding against a set, how many claims have been filed — are
    recomputed by full traversal rather than by incremental adjustment

    Design: Difficulty/compensating_invariant/quality_credit_restores_every_redemption_scratch_value_exactly
    """
    from test_helpers import build_fulfilled_redemption

    scenario = build_fulfilled_redemption(api, estimated_value_cents=400000)
    card_set = scenario["card_set"]
    before = validate_success(api.get_card_set(card_set["id"], PLANNER))

    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 40,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(claim["id"], QA))
    validate_success(api.credit_quality_claim(claim["id"], QA))

    after = validate_success(api.get_card_set(card_set["id"], PLANNER))
    # The count is a traversal over ISSUED-or-FULFILLED redemptions, and the
    # reversal moves the redemption from one of those states to the other, so
    # the counter is unchanged — an incremental delta would have added one.
    assert after["autograph_redemptions_outstanding"] == before["autograph_redemptions_outstanding"]

    # The credit moves a claim to CREDITED and returns a redemption to ISSUED;
    # it touches no card-set status, so the set never leaves IN_PRODUCTION.
    lic = validate_success(api.get_license(scenario["license"]["id"], LM))
    assert lic["set_count"] == 1, "the set still exists under its license"


def test_crediting_a_claim_leaves_two_redemptions_alone_when_neither_was_fulfilled(api):
    """PRD §3.7: "Approval moves the claim to `APPROVED`, and this is the state
    that makes it visible to the print-run safety floor and to the recall
    cascade."

    Design: Difficulty/compensating_invariant/quality_credit_restores_every_redemption_scratch_value_exactly
    """
    license_obj, line, card_set = _line_with_waiting_redemption(api)
    first = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-8101",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 150000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            TEST_USERS["redemption_analyst_headers"],
        )
    )
    second = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-8102",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 500000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            TEST_USERS["redemption_analyst_headers"],
        )
    )
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 40,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    get_success_data(api.open_claim_review(claim["id"], QA))
    get_success_data(api.approve_quality_claim(claim["id"], QA))
    validate_success(api.credit_quality_claim(claim["id"], QA))

    for redemption, scratch in ((first, 150000), (second, 500000)):
        read = validate_success(
            api.get_redemption(redemption["id"], TEST_USERS["redemption_analyst_headers"])
        )
        assert read["status"] == "ISSUED"
        assert read["estimated_value_cents"] == scratch, "an unfulfilled scratch never moved"

    conserved = validate_success(api.get_card_set(card_set["id"], PLANNER))
    assert conserved["autograph_redemptions_outstanding"] == 2


def test_an_approve_then_return_to_draft_leaves_the_counters_conserved(api):
    """PRD §2.9: "a value that moves backwards (a set rolled out of approval, a
    claim credited rather than approved) immediately lowers the counter rather
    than leaving a stale increment behind."

    Design: Difficulty/compensating_invariant/card_set_approval_roll_back_leaves_the_license_counts_untouched
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))

    approved = validate_success(approve_card_set(api, card_set["id"], submitted["version"]))
    assert approved["status"] == "APPROVED"
    during = validate_success(api.get_license(license_obj["id"], LM))
    assert during["approved_set_count"] == 1

    back = validate_success(api.return_card_set_to_draft(card_set["id"], PM))
    assert back["status"] == "DRAFT"
    after = validate_success(api.get_license(license_obj["id"], LM))
    assert after["approved_set_count"] == 0, "the counter returns to its pre-approval value"
    assert after["set_count"] == 1, "the set still exists, so set_count must not move"


def test_the_return_to_draft_leaves_the_rights_pin_in_place(api):
    """PRD §3.1: "those sets will be refused at every subsequent mutation until
    they are returned to draft and approved again."

    Design: Difficulty/compensating_invariant/card_set_approval_roll_back_leaves_the_license_counts_untouched
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    approved = get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))
    assert approved["rights_pinned_version"] == 1

    back = get_success_data(api.return_card_set_to_draft(card_set["id"], PM))
    assert back["rights_pinned_version"] == 1, (
        "the rollback does not clear the pin the approval wrote"
    )


def test_two_lines_under_one_license_keep_the_counts_sane_after_a_rollback(api):
    """PRD §3.1: "`set_count` is the number of card sets, in any status
    whatsoever, whose parent product line names this license."

    Design: Difficulty/compensating_invariant/card_set_approval_roll_back_leaves_the_license_counts_untouched
    """
    license_obj = create_active_license(api)
    scenario_a = build_approved_set(api, license_id=license_obj["id"])
    line_b = create_line_ready(api, license_obj["id"])
    set_b = create_card_set_raw(api, line_b["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, set_b["id"], license_obj["id"])
    submitted_b = get_success_data(api.submit_card_set(set_b["id"], PM))
    get_success_data(approve_card_set(api, set_b["id"], submitted_b["version"]))

    during = validate_success(api.get_license(license_obj["id"], LM))
    assert during["set_count"] == 2
    assert during["approved_set_count"] == 2

    get_success_data(api.return_card_set_to_draft(scenario_a["card_set"]["id"], PM))
    after = validate_success(api.get_license(license_obj["id"], LM))
    assert after["approved_set_count"] == 1
    assert after["set_count"] == 2, "both sets remain, only one is out of approval"