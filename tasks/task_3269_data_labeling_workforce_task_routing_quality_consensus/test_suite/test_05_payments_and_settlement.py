"""Dynamic pay rates, the weekly ceiling, settlement and appeal compensation."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    make_worker_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    REVIEWER,
    REVIEWER_TWO,
    attach_item,
    commit_label,
    create_program,
    create_unit,
    dispatch_panel,
    enroll_qualification,
    file_appeal,
    get_program,
    make_pool,
    open_program,
    pay_commit,
    production_commits,
    propose_appeal,
    setup_dispatched_item,
    verify_qualification,
    worker_for_commit,
)


def test_single_rounding_then_weekly_ceiling_clamp(api):
    """PRD §3.10: "The remaining allowance is the ceiling minus that settled sum,
    floored at zero so it can never be negative. The accepted amount is the smaller
    of the rounded uncapped product and that remaining allowance, and the commit's
    `payment_capped` flag is true exactly when the rounded uncapped product is
    strictly greater than the remaining allowance"

    Design: Difficulty/combinatorial_formula/payout_single_rounding_then_weekly_ceiling_clamp
    """
    program = create_program(weekly_earning_cap_cents=20)
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker, _q = make_pool(1, "es-MX", "PROFICIENT")[0]

    settled_commits = []
    for index in range(1, 3):
        item = attach_item(unit, item_key=f"i-{index:04d}", payload_uri=f"s3://ax/{index:04d}")
        dispatched = dispatch_panel(item)
        commit = production_commits(dispatched)[0]
        commit_label(commit, worker, "A")
        paid = pay_commit(commit["id"], 8)
        assert paid["paid_amount_cents"] == 8, "a PROFICIENT commit is 8 cents uncapped"
        settled_commits.append(commit)

    third = attach_item(unit, item_key="i-0003", payload_uri="s3://ax/0003")
    dispatched = dispatch_panel(third)
    commit = production_commits(dispatched)[0]
    commit_label(commit, worker, "A")

    validate_error(
        api_client.create_payout_record(
            commit["id"], {"amount_cents": 8, "currency": "USD"}, ADMIN
        ),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
        422,
    )

    accepted = pay_commit(commit["id"], 4)
    assert accepted["paid_amount_cents"] == 4, "sixteen settled cents leave a four cent remainder"
    assert accepted["payment_capped"] is True, "the ceiling, not the formula, bound this payment"


def test_a_novice_commit_with_plentiful_capacity_is_not_capped(api):
    """PRD §3.10: "The unrounded amount is the base rate multiplied by the streak
    multiplier and then by the tier multiplier; that product is then rounded half
    up to a whole number of cents, and that rounding is the **only** rounding site
    in the calculation."

    Design: Difficulty/combinatorial_formula/payout_single_rounding_then_weekly_ceiling_clamp
    """
    program = create_program(weekly_earning_cap_cents=9000)
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker, _q = make_pool(1, "es-MX", "NOVICE")[0]

    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")
    dispatched = dispatch_panel(item)
    commit = production_commits(dispatched)[0]
    commit_label(commit, worker, "A")

    accepted = pay_commit(commit["id"], 6)
    assert accepted["paid_amount_cents"] == 6, "the NOVICE product rounds to exactly six cents"
    assert accepted["payment_capped"] is False


def test_exact_penny_amount_for_a_proficient_production_commit(api):
    """PRD §3.10: "The base rate for a commit is 9 cents when the assignment's
    `kind` is `GOLD` and 6 cents when it is `PRODUCTION`."

    PRD §3.10: "The tier multiplier is 1.0 for `NOVICE`, 1.25 for `PROFICIENT`,
    and 1.5 for `EXPERT`"

    Design: Corner/calculations/exact_penny_amount_for_a_proficient_production_commit
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1)
    commit = commits[0]
    committed = commit_label(commit, worker_for_commit(commit, pool), "A")

    assert committed["committed_value"] == "A"
    assert committed["is_modal_agent"] is True, "the only modal member is the modal agent"

    accepted = pay_commit(commit["id"], 8)
    assert accepted["paid_amount_cents"] == 8, "round_half_up(6 * 1.0 * 1.25) == 8"


def test_the_three_tier_multipliers_price_the_same_production_commit(api):
    """PRD §3.10: "The tier multiplier is 1.0 for `NOVICE`, 1.25 for `PROFICIENT`,
    and 1.5 for `EXPERT`, and it is the same `tier_multiplier` the qualification
    exposes."

    Design: Corner/calculations/exact_penny_amount_for_a_proficient_production_commit
    """
    # Every iteration registers one more worker into the same running process,
    # and PRD §3.4 ranks the pool by qualification_score descending, so the
    # handles ascend in score (6383, 9555, 9765) and each case's own worker
    # stays the top-ranked member.
    cases = [("NOVICE", "pia-andersen", 6), ("PROFICIENT", "kevin-lum", 8),
             ("EXPERT", "kai-wong", 9)]
    for tier, handle, expected in cases:
        program = create_program(program_code=f"AX-50{tier[:2]}", weekly_earning_cap_cents=9000)
        unit = create_unit(program, unit_code="U-1", panel_size=1)
        open_program(program)
        worker, qualification = make_pool(1, "es-MX", tier, handles=[handle])[0]
        assert qualification["tier_multiplier"] == {"NOVICE": 1.0, "PROFICIENT": 1.25, "EXPERT": 1.5}[tier]

        item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")
        dispatched = dispatch_panel(item)
        # The panel is the ranked pool's first member, so the assignment belongs
        # to whichever single pooled worker this case registered.
        commit = production_commits(dispatched)[0]
        assert commit["worker_id"] == worker["id"], "the sole pooled worker is on the panel"
        commit_label(commit, worker, "A")
        accepted = pay_commit(commit["id"], expected)
        assert accepted["paid_amount_cents"] == expected, f"{tier} prices at {expected} cents"


def test_program_restriction_outranks_the_empty_selector_pool(api):
    """PRD §2.11: "Rank 6 is the safety band:
    `ERR_PROGRAM_OPERATIONALLY_RESTRICTED` (409), `ERR_WORKER_RESTRICTED` (403),
    `ERR_FIELD_SCHEMA_MISMATCH` (400), and `ERR_EDGE_CASE_GUIDANCE_CONFLICT`
    (409)."

    PRD §2.11: "Rank 9 collects the remaining business constraints:
    `ERR_NO_ELIGIBLE_WORKER` (422)"

    Design: Difficulty/priority_pair_validation_conflict/frozen_program_state_beats_worker_restriction_on_dispatch
    """
    program = create_program()
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker, _q = make_pool(1, "es-MX", "PROFICIENT")[0]
    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")

    get_success_data(
        api_client.create_incident(
            worker["id"],
            {
                "program_code": "AX-4410",
                "category": "PII_EXPOSURE",
                "severity": "MAJOR",
                "description_text": "Screenshot of the customer corpus shared externally.",
                "incident_action": "REPORT",
            },
            ADMIN,
        ),
        201,
    )

    resp = api_client.dispatch_panel(item["id"], ADMIN)
    error_data = validate_error(resp, "ERR_PROGRAM_OPERATIONALLY_RESTRICTED", 409)
    assert error_data["error_id"] != "ERR_NO_ELIGIBLE_WORKER", (
        "the rank 6 safety gate short-circuits before the rank 9 selector runs"
    )


def test_resolving_the_incident_clears_the_restriction_and_the_dispatch_succeeds(api):
    """PRD §2.5: "its value is `REPORT` or `RESOLVE`, the reporting action opens
    the incident and recomputes both flags, while the resolving action closes it
    and recomputes both flags again."

    Design: Difficulty/priority_pair_validation_conflict/frozen_program_state_beats_worker_restriction_on_dispatch
    """
    program = create_program()
    unit = create_unit(program, unit_code="U-1", panel_size=1)
    open_program(program)
    worker, _q = make_pool(1, "es-MX", "PROFICIENT")[0]
    item = attach_item(unit, item_key="i-0001", payload_uri="s3://ax/0001")

    incident = get_success_data(
        api_client.create_incident(
            worker["id"],
            {
                "program_code": "AX-4410",
                "category": "PII_EXPOSURE",
                "severity": "MAJOR",
                "description_text": "Observed breach.",
                "incident_action": "REPORT",
            },
            ADMIN,
        ),
        201,
    )
    restricted_program = get_program(program["id"])
    assert restricted_program["operational_restricted"] is True

    get_success_data(
        api_client.create_incident(
            worker["id"],
            {
                "program_code": "AX-4410",
                "category": "PII_EXPOSURE",
                "severity": "MAJOR",
                "description_text": "Observed breach.",
                "incident_action": "RESOLVE",
            },
            ADMIN,
        ),
        201,
    )
    cleared_program = get_program(program["id"])
    assert cleared_program["operational_restricted"] is False

    clear_worker = get_success_data(api_client.get_worker(worker["id"], ADMIN), 200)
    assert clear_worker["restricted"] is False

    dispatched = dispatch_panel(item)
    assert len(production_commits(dispatched)) == 1


def test_mis_stated_payout_amount_is_refused_rather_than_corrected(api):
    """PRD §3.10: "The assertion must match the computed amount exactly: an
    under-stated or over-stated claim is refused with
    `ERR_PAYMENT_AMOUNT_MISMATCH` (422) rather than being silently corrected."

    Design: Difficulty/priority_pair_validation_conflict/referential_duplicate_beats_fiscal_amount_mismatch
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1)
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    validate_error(
        api_client.create_payout_record(
            commit["id"], {"amount_cents": 999, "currency": "USD"}, ADMIN
        ),
        "ERR_PAYMENT_AMOUNT_MISMATCH",
        422,
    )
    live = get_success_data(api_client.get_commit(commit["id"], ADMIN), 200)
    assert live["payment_status"] == "UNPAID", "a refused payout applies no mutation"
    assert live["paid_amount_cents"] == 0


def test_payout_currency_must_match_the_worker_payout_currency(api):
    """PRD §3.10: "The currency must be the worker's `payout_currency`, else
    `ERR_CURRENCY_MISMATCH` (409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_duplicate_beats_fiscal_amount_mismatch
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1)
    commit = commits[0]
    commit_label(commit, worker_for_commit(commit, pool), "A")

    validate_error(
        api_client.create_payout_record(
            commit["id"], {"amount_cents": 8, "currency": "MXN"}, ADMIN
        ),
        "ERR_CURRENCY_MISMATCH",
        409,
    )


def test_settlement_then_compensating_reversal_restores_the_receivable(api):
    """PRD §3.10: "A settlement decrements `worker_receivable_cents` by the settled
    amount, and any settlement or reversal that would drive the balance strictly
    negative is refused with `ERR_INSUFFICIENT_RECEIVABLE` (422)."

    PRD §3.12: "The disputed worker's `worker_receivable_cents` is increased by
    `revised_amount_cents`, while their `lifetime_earned_cents` is deliberately
    left unchanged, so the reversal is compensating rather than a rewinding of
    lifetime earnings."

    Design: Difficulty/compensating_invariant/settlement_reversal_leaves_receivable_conserved
    """
    # PRD §3.10 makes settlement_min_cents the floor a withdrawal must clear;
    # the fixture default of 1000 cents sits above this scenario's 8-cent
    # receivable, so the worker is registered at the lowest legal floor.
    program, unit, pool, item, commits = setup_dispatched_item(
        panel_size=1, worker_overrides={"settlement_min_cents": 1}
    )
    commit = commits[0]
    worker = worker_for_commit(commit, pool)
    commit_label(commit, worker, "A")
    paid = pay_commit(commit["id"], 8)
    assert paid["payment_status"] == "ACCEPTED"

    settled = get_success_data(
        api_client.create_settlement_request(
            worker["id"], {"amount_cents": 5}, make_worker_headers(worker["id"])
        ),
        200,
    )
    assert settled["worker_receivable_cents"] == 3, "8 accepted less 5 settled"

    claim = file_appeal(item, worker, grounds="AMBIGUOUS_INSTRUCTIONS")
    proposed = propose_appeal(claim["id"], "PAY_REVERSAL", REVIEWER)
    assert proposed["revised_amount_cents"] == 8

    concurred = get_success_data(
        api_client.concur_appeal(
            claim["id"], {"expected_claim_version": proposed["version"]}, REVIEWER_TWO
        ),
        200,
    )
    assert concurred["status"] == "ACCEPTED", (
        "the concurrence moves the claim to CONCURRENCE and then, completing "
        "without disagreement, transitions it automatically to ACCEPTED"
    )

    restored = get_success_data(api_client.get_worker(worker["id"], ADMIN), 200)
    # PRD §3.10 fixes the ledger verbatim: worker_receivable_cents is "the sum
    # of accepted payouts minus settled cents plus reversed cents", which reads
    # 0 - 5 + 8 == 3 once the disputed payment has been reversed and the
    # revised amount credited.
    assert restored["worker_receivable_cents"] == 3, "0 accepted - 5 settled + 8 reversed"
    assert restored["lifetime_earned_cents"] == 8, "lifetime earnings are never rewound"

    disputed = get_success_data(api_client.get_commit(commit["id"], ADMIN), 200)
    assert disputed["payment_status"] == "REVERSED"


def test_reversal_clears_the_qualification_failure_streak(api):
    """PRD §3.12: "The disputed qualification's `gold_fail_streak` is reset to 0."

    PRD §3.12: "A concurrence rewrites a great deal at once. The claim's status
    becomes `CONCURRENCE`."

    Design: Difficulty/compensating_invariant/settlement_reversal_leaves_receivable_conserved
    """
    program, unit, pool, item, commits = setup_dispatched_item(panel_size=1)
    commit = commits[0]
    worker, qualification = pool[0]
    commit_label(commit, worker, "A")
    pay_commit(commit["id"], 8)

    claim = file_appeal(item, worker, grounds="AMBIGUOUS_INSTRUCTIONS")
    proposed = propose_appeal(claim["id"], "PAY_REVERSAL", REVIEWER)
    validate_success(
        api_client.concur_appeal(
            claim["id"], {"expected_claim_version": proposed["version"]}, REVIEWER_TWO
        ),
        200,
    )

    qualifications = get_success_data(
        api_client.list_worker_qualifications(worker["id"], ADMIN), 200
    )
    assert qualifications[0]["gold_fail_streak"] == 0