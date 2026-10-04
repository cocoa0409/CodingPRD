"""Claims: billed-total computation, the pinned per-line pricing order, the
contract-rate vs Medicare-fallback variants, the deny-resubmit-pay cycle,
adjudicate state guards, the credentialed-provider gate, and the conserved
payment buckets."""
from test_helpers import (
    api_client, validate_error,
    assert_claim, assert_payment_buckets_conserved,
    adjudicate_claim, adjudicate_claim_payload, claim_service_line,
    create_claim_for_appointment, create_tpa, decide_credential, get_claim,
    get_provider, get_tpa, make_tpa_admin_headers, resubmit_claim,
    reverse_claim_payment, setup_episode_with_completed_appointments,
    setup_paid_claim,
)


def test_claim_billed_total_computed_from_lines():
    """PRD §3.7: "The claim's `provider_id` and `tpa_id` are copied from the
    authorization, its `billed_total_cents` is computed as the sum over all
    lines of `unit_billed_cents` multiplied by `units`, and it enters
    `RECEIVED` status with `submitted_at` stamped from the logical clock,
    `resubmit_count` at zero, and `paid_amount_cents` null until a payment
    decision."

    Design: Corner/entities/claim_billed_total_computed_from_lines
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=2,
                                                    duration_days=60)
    claim = create_claim_for_appointment(
        env["authorization"], env["appointments"][0], env["provider"],
        service_lines=[
            claim_service_line(service_code="PT_EVAL",
                               service_category="SPECIALTY_CARE", units=2,
                               unit_billed_cents=9000),
            claim_service_line(service_code="GEN1",
                               service_category="PRIMARY_CARE", units=3,
                               unit_billed_cents=100),
        ],
    )
    assert_claim(claim)
    assert claim["billed_total_cents"] == 18300  # 2*9000 + 3*100
    assert claim["status"] == "RECEIVED"
    assert claim["resubmit_count"] == 0
    assert claim["paid_amount_cents"] is None


def test_claim_payment_contract_vs_medicare_fallback():
    """PRD §3.7: "For each line, the applicable per-unit rate is the provider's
    `contract_rates` entry for the line's `service_code` when one exists, and
    otherwise the Medicare fallback for the line's category: 10000 cents per
    unit for `PRIMARY_CARE`, 18000 cents per unit for `SPECIALTY_CARE`."
    PRD §3.7: "The line's allowed amount is the lesser of its billed amount
    (`unit_billed_cents` times `units`) and the rate times `units`."

    Design: Difficulty/dual_variant_calc/claim_payment_contract_vs_medicare_fallback
    """
    tpa = create_tpa()
    env_c = setup_episode_with_completed_appointments(
        num_appointments=1, authorized_visits=1, tpa=tpa,
        contract_rates={"PT_EVAL": 8000},
    )
    env_m = setup_episode_with_completed_appointments(
        num_appointments=1, authorized_visits=1, tpa=tpa,
    )
    lines = [claim_service_line(service_code="PT_EVAL",
                                service_category="SPECIALTY_CARE", units=2,
                                unit_billed_cents=9000)]
    cl_c = create_claim_for_appointment(
        env_c["authorization"], env_c["appointments"][0], env_c["provider"],
        service_lines=lines,
    )
    cl_m = create_claim_for_appointment(
        env_m["authorization"], env_m["appointments"][0], env_m["provider"],
        service_lines=lines,
    )

    paid_c = adjudicate_claim(cl_c["id"], env_c["tpa"], "PAID")
    paid_m = adjudicate_claim(cl_m["id"], env_m["tpa"], "PAID")

    # Contract rate: allowed min(18000, 8000*2) = 16000, fee 400.
    assert paid_c["paid_amount_cents"] == 15600
    # Medicare fallback: allowed min(18000, 18000*2) = 18000, fee 450.
    assert paid_m["paid_amount_cents"] == 17550
    assert paid_c["paid_amount_cents"] != paid_m["paid_amount_cents"]


def test_claim_fee_per_line_then_sum_rounding_order():
    """PRD §2.7: "Claim payment computation rounds the administrator fee half
    up to a whole cent on each service line individually, and only then sums
    the per-line nets; rounding the aggregate instead of the lines is
    non-conformant."
    PRD §3.7: "The administrator's fee on the line is that allowed amount
    multiplied by 2.5 percent, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/claim_fee_per_line_then_sum_rounding_order
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=1)
    claim = create_claim_for_appointment(
        env["authorization"], env["appointments"][0], env["provider"],
        service_lines=[
            claim_service_line(service_code="GEN1", units=1,
                               unit_billed_cents=101),
            claim_service_line(service_code="GEN2", units=1,
                               unit_billed_cents=103),
        ],
    )
    assert claim["billed_total_cents"] == 204

    paid = adjudicate_claim(claim["id"], env["tpa"], "PAID")
    # Per-line: fees round_half_up(2.525)=3 and round_half_up(2.575)=3 -> 6.
    assert paid["paid_amount_cents"] == 198
    # Sum-then-round would give 204 - round(5.10) = 199; that is NOT the
    # contract.
    assert paid["paid_amount_cents"] != 199


def test_claim_denied_resubmit_paid_cycle():
    """PRD §3.7: "The owning `ProviderRep` may resubmit a `DENIED` claim with
    corrected `service_lines`, cycling it back to `RECEIVED` — at most twice
    per claim: a resubmission attempted when `resubmit_count` has already
    reached 2 is rejected with `ERR_RESUBMISSION_LIMIT` (HTTP 409), and
    resubmitting from any status but `DENIED` fails with `ERR_INVALID_STATE`."
    PRD §3.1: "On every claim-finalization event — an adjudication decided
    `PAID`, an adjudication decided `DENIED`, or a cascade auto-denial — the
    administrator's `adjudicated_events` rises by one, and `denied_events`
    rises by one whenever the outcome was a denial; resubmissions and payment
    reversals do not move either counter."

    Design: Difficulty/non_linear_state_machine/claim_denied_resubmit_paid_cycle
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=1)
    claim = create_claim_for_appointment(
        env["authorization"], env["appointments"][0], env["provider"],
        service_lines=[claim_service_line(unit_billed_cents=4000)],
    )

    denied = adjudicate_claim(claim["id"], env["tpa"], "DENIED",
                              "CLINICAL_REVIEW")
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "CLINICAL_REVIEW"

    back = resubmit_claim(claim["id"], env["provider"],
                          service_lines=[claim_service_line(
                              unit_billed_cents=5000)])
    assert back["status"] == "RECEIVED"
    assert back["resubmit_count"] == 1
    assert back["billed_total_cents"] == 5000

    paid = adjudicate_claim(claim["id"], env["tpa"], "PAID")
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 4875  # 5000 - fee 125

    tpa = get_tpa(env["tpa"]["id"])
    assert tpa["adjudicated_events"] == 2  # resubmission is not a finalization
    assert tpa["denied_events"] == 1


def test_claim_adjudicate_from_paid_returns_invalid_state():
    """PRD §3.7: "Only a `RECEIVED` claim can be adjudicated (else
    `ERR_INVALID_STATE`), and the provider must still be `CREDENTIALED` (else
    `ERR_PROVIDER_NOT_CREDENTIALED`)."

    Design: Corner/state_machines/claim_adjudicate_from_paid_returns_invalid_state
    """
    env = setup_paid_claim(authorized_visits=1)
    claim = env["claim"]
    assert claim["status"] == "PAID"
    assert claim["paid_amount_cents"] == 975  # 1000 - fee 25

    resp = api_client.adjudicate_claim(
        claim["id"], adjudicate_claim_payload("PAID"),
        make_tpa_admin_headers(env["tpa"]["id"]),
    )
    validate_error(resp, "ERR_INVALID_STATE")

    after = get_claim(claim["id"])
    assert after["status"] == "PAID"
    assert after["paid_amount_cents"] == 975


def test_payment_buckets_conserved_across_pay_and_reverse():
    """PRD §2.10: "Second, the payment buckets of every provider always
    balance: `lifetime_paid_cents` equals `current_paid_cents` plus
    `reversed_cents`."
    PRD §2.10: "A paid adjudication adds the paid amount to both the lifetime
    and current buckets; a payment reversal moves the paid amount from the
    current bucket to the reversed bucket, leaving the lifetime total
    untouched."

    Design: Difficulty/compensating_invariant/payment_buckets_conserved_across_pay_and_reverse
    """
    env = setup_episode_with_completed_appointments(num_appointments=2,
                                                    authorized_visits=2,
                                                    duration_days=60)
    auth, provider, tpa = (env["authorization"], env["provider"], env["tpa"])
    c1 = create_claim_for_appointment(
        auth, env["appointments"][0], provider,
        service_lines=[claim_service_line(unit_billed_cents=5000)],
    )
    c2 = create_claim_for_appointment(
        auth, env["appointments"][1], provider,
        service_lines=[claim_service_line(unit_billed_cents=2000)],
    )

    paid1 = adjudicate_claim(c1["id"], tpa, "PAID")
    paid2 = adjudicate_claim(c2["id"], tpa, "PAID")
    assert paid1["paid_amount_cents"] == 4875  # 5000 - 125
    assert paid2["paid_amount_cents"] == 1950  # 2000 - 50

    pre = get_provider(tpa["id"], provider["id"])
    assert (pre["lifetime_paid_cents"], pre["current_paid_cents"],
            pre["reversed_cents"]) == (6825, 6825, 0)
    assert_payment_buckets_conserved(pre)

    reversed_claim = reverse_claim_payment(c1["id"], tpa,
                                           reason="duplicate billing recoupment")
    assert reversed_claim["status"] == "REVERSED"

    post = get_provider(tpa["id"], provider["id"])
    assert (post["lifetime_paid_cents"], post["current_paid_cents"],
            post["reversed_cents"]) == (6825, 1950, 4875)
    assert_payment_buckets_conserved(post)


def test_claim_adjudication_blocked_when_provider_suspended():
    """PRD §3.7: "Only a `RECEIVED` claim can be adjudicated (else
    `ERR_INVALID_STATE`), and the provider must still be `CREDENTIALED` (else
    `ERR_PROVIDER_NOT_CREDENTIALED`)."
    PRD §3.1: "Exactly five transitions are legal: `PENDING` to `CREDENTIALED`,
    `PENDING` to `DECREDENTIALED`, `CREDENTIALED` to `SUSPENDED`, `SUSPENDED`
    to `CREDENTIALED`, and `CREDENTIALED` to `DECREDENTIALED`."

    Design: Difficulty/cross_entity_state_dependency/claim_adjudication_blocked_when_provider_suspended
    """
    env = setup_episode_with_completed_appointments(num_appointments=1,
                                                    authorized_visits=1)
    claim = create_claim_for_appointment(
        env["authorization"], env["appointments"][0], env["provider"],
        service_lines=[claim_service_line(unit_billed_cents=5000)],
    )

    decide_credential(env["provider"], "SUSPENDED")
    resp = api_client.adjudicate_claim(
        claim["id"], adjudicate_claim_payload("PAID"),
        make_tpa_admin_headers(env["tpa"]["id"]),
    )
    validate_error(resp, "ERR_PROVIDER_NOT_CREDENTIALED")
    assert get_claim(claim["id"])["status"] == "RECEIVED"

    decide_credential(env["provider"], "CREDENTIALED")  # reinstatement
    paid = adjudicate_claim(claim["id"], env["tpa"], "PAID")
    assert paid["status"] == "PAID"
    assert paid["paid_amount_cents"] == 4875
