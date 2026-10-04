"""Conserved counters: opt-out releases, settlement voids and the reversal clears."""
from test_helpers import (
    setup_verification_stack,
    setup_responded_request,
    create_validated_batch_accrual,
    post_settlement,
    void_settlement,
    list_accruals,
    list_responses,
    get_employer,
    get_request,
    get_worker,
    get_verifier,
    set_clock,
    make_worker_headers,
    make_verifier_headers,
    TEST_USERS,
    api,
    validate_success,
    validate_error,
    ApiErrorId,
)


def test_worker_opt_out_releases_exactly_the_counted_verification_records(api):
    """PRD §3.9: "An employer's `counted_verification_records` is the sum of
    `records_matched_count` across its requests that are currently `RESPONDED`,
    restricted to requests whose `current_employer_id` is that employer."
    PRD §3.9: "a request that added its matched count when it reached `RESPONDED`
    releases exactly the same count when its reversal takes it out of `RESPONDED`, so an
    employer's counter returns to its pre-verification value with no drift."

    Design: Difficulty/compensating_invariant/worker_opt_out_releases_exactly_the_counted_verification_records
    """
    ctx = setup_responded_request(clock="2026-09-01T00:00:00Z")
    employer_id = ctx["employer"]["id"]

    before = get_employer(employer_id)["counted_verification_records"]
    assert before == 1

    api.opt_out_worker(ctx["worker"]["id"], make_worker_headers(ctx["worker"]["id"]))
    after = get_employer(employer_id)["counted_verification_records"]
    assert after == 0
    assert after - before == -1


def test_opt_out_reverses_a_responded_request_and_leaves_contributed_records_alone(api):
    """PRD §3.2: "reverses every request already `RESPONDED` into
    `REVERSED_RECONSENT_REQUIRED` (also stamped `WORKER_OPT_OUT`)".
    PRD §3.3: "the employer's `total_records_contributed` grows by
    `accepted_record_count`".

    Design: Difficulty/compensating_invariant/worker_opt_out_releases_exactly_the_counted_verification_records
    """
    ctx = setup_responded_request(clock="2026-09-01T00:00:00Z")
    employer_id = ctx["employer"]["id"]
    request_id = ctx["request"]["id"]

    contributed_before = get_employer(employer_id)["total_records_contributed"]
    api.opt_out_worker(ctx["worker"]["id"], make_worker_headers(ctx["worker"]["id"]))

    request = get_request(request_id, make_verifier_headers(ctx["verifier"]["id"]))
    assert request["request_state"] == "REVERSED_RECONSENT_REQUIRED"
    assert get_employer(employer_id)["total_records_contributed"] == contributed_before


def test_settlement_void_restores_earned_cents_exactly(api):
    """PRD §3.9: "An employer's `compensation_earned_cents` is the sum of the waived
    amounts on its `WAIVED` accruals plus the sum of the paid amounts on its `PAID`
    accruals, and voiding a settlement must leave the total exactly where it stood
    before the settlement posted."

    Design: Difficulty/compensating_invariant/settlement_void_restores_employer_compensation_earned_cents_exactly
    """
    ctx = create_validated_batch_accrual(record_count=1200)
    employer_id = ctx["employer"]["id"]

    before = get_employer(employer_id)["compensation_earned_cents"]
    assert before == 0

    settlement = post_settlement(employer_id, settlement_period_end="2026-09-30T00:00:00Z",
                                 settlement_budget_cents=12000, waiver_budget_cents=0)
    assert settlement["settled_gross_cents"] == 12000
    assert settlement["settled_net_cents"] == 12000
    assert get_employer(employer_id)["compensation_earned_cents"] == 12000

    voided = void_settlement(settlement["settlement_id"])
    assert voided["reverted_cents"] == 12000
    assert get_employer(employer_id)["compensation_earned_cents"] == 0


def test_void_releases_paid_cents_and_returns_the_accrual_to_accrued(api):
    """PRD §3.7: "A void releases exactly the settled figures it had added —
    `waived_cents` or `paid_cents` is reset to 0 — and decrements the employer's
    `compensation_earned_cents` by the released amount".

    Design: Difficulty/compensating_invariant/settlement_void_restores_employer_compensation_earned_cents_exactly
    """
    ctx = create_validated_batch_accrual(record_count=1200)
    employer_id = ctx["employer"]["id"]
    settlement = post_settlement(employer_id, settlement_period_end="2026-09-30T00:00:00Z",
                                 settlement_budget_cents=12000)
    void_settlement(settlement["settlement_id"])

    accrual = list_accruals(employer_id)[0]
    assert accrual["cycle_state"] == "ACCRUED"
    assert accrual["paid_cents"] == 0
    assert accrual["waived_cents"] == 0


def test_all_or_nothing_settlement_leaves_a_partially_covered_accrual_alone(api):
    """PRD §3.7: "Every settlement is all-or-nothing per accrual: no accrual is ever
    partially settled, and a bucket's residual capacity is not carried forward beyond
    the settlement that spent it."
    PRD §3.7: "An employer holding 7000 cents of paid budget against a single 9000-cent
    accrual therefore settles nothing at all".

    Design: Difficulty/compensating_invariant/settlement_void_restores_employer_compensation_earned_cents_exactly
    """
    ctx = create_validated_batch_accrual(record_count=1200)
    employer_id = ctx["employer"]["id"]
    post_settlement(employer_id, settlement_period_end="2026-09-30T00:00:00Z",
                    settlement_budget_cents=11000)
    assert get_employer(employer_id)["compensation_earned_cents"] == 0
    accrual = list_accruals(employer_id)[0]
    assert accrual["cycle_state"] == "ACCRUED"


def test_reversal_clears_the_derived_request_fields_in_the_same_response(api):
    """PRD §2.4: "the reversal path deletes it".
    PRD §3.5: "the request moves to `RESPONDED` and stamps `responded_at` from the
    logical clock."
    PRD §3.2: "reverses every request already `RESPONDED` into
    `REVERSED_RECONSENT_REQUIRED`".

    Design: Corner/consistency_model/reversal_clears_derived_request_fields_in_the_same_request
    """
    ctx = setup_responded_request(clock="2026-09-01T00:00:00Z")
    request_id = ctx["request"]["id"]
    verifier_id = ctx["verifier"]["id"]
    admin_reverse = validate_success(api.reverse_request(request_id, ADMIN_HEADERS()), 200)

    assert admin_reverse["resolved_product_tier"] is None
    after = get_request(request_id, make_verifier_headers(verifier_id))
    assert after["request_state"] == "REVERSED_RECONSENT_REQUIRED"
    assert after["current_employment_status"] is None
    assert after["rendered_field_set"] == []
    assert list_responses(request_id, verifier_id) == []


def test_reversal_charges_the_verifier_the_reversal_penalty(api):
    """PRD §3.8: "the three event kinds carry different base penalties: a dispute that
    reached `ESCALATED` carries 25, a feed stall that reached `ESCALATED` carries 40,
    and a response reversal carries 30."
    PRD §3.8: "the first attributed event is charged exactly its base penalty".

    Design: Corner/consistency_model/reversal_clears_derived_request_fields_in_the_same_request
    """
    ctx = setup_responded_request(clock="2026-09-01T00:00:00Z")
    api.reverse_request(ctx["request"]["id"], ADMIN_HEADERS())

    verifier = get_verifier(ctx["verifier"]["id"], make_verifier_headers(ctx["verifier"]["id"]))
    assert verifier["negative_escalation_count"] == 30


def ADMIN_HEADERS():
    return TEST_USERS["admin_headers"]