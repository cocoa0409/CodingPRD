"""Compensating actions, and the invariants they are obliged to restore.

Two round trips are checked here.  A submit-then-deny round trip must return the
carrier's fee position to exactly where it started, while a submit-then-return
round trip must deliberately leave the debit standing (PRD S3.3).  A
suspension-then-restoration round trip must return the contract population and
every shipment status to exactly where they started, while the money it computes
along the way is not symmetric at all (PRD S2.10, S3.9).
"""

from test_helpers import (
    REGISTRY_ADMIN,
    assert_contract_population_identity,
    assert_customer_contract,
    assert_fee_ledger_entry,
    assert_fee_ledger_identities,
    assert_no_embargoed_shipments,
    assert_shipment,
    create_contract,
    create_draft_application,
    cure_with_replacement_filing,
    expected_filing_fee,
    expected_settled_actual,
    expected_suspension_estimate,
    get_success_data,
    review_application,
    setup_active_authority_with_shipment,
    setup_registry,
    setup_suspended_by_filing_cancel,
    submit_application,
    validate_paginated,
)

FILING_FEE_CENTS = 64791


def _ledger(api, carrier_id):
    entries, meta = validate_paginated(
        api.list_fee_ledger_entries(carrier_id, REGISTRY_ADMIN, limit=100)
    )
    return entries, meta


def _submit_new_application(api, carrier_id):
    application = create_draft_application(api, carrier_id)
    return submit_application(api, carrier_id, application["id"])


# ---------------------------------------------------------------------------
# DENY compensates the submission debit; RETURN deliberately does not
# ---------------------------------------------------------------------------
def test_deny_reverses_the_filing_fee_debit_to_the_pre_submission_balance(api):
    """PRD S3.3: "When `submission_count` becomes 1, the three required insurance
    minimums and the filing fee are recomputed and then **frozen**:
    `filing_fee_cents` and `filing_fee_breakdown` take their final values, a
    ledger entry with `entry_type` `FILING_FEE_DEBIT` and an `amount_cents` equal
    to positive `filing_fee_cents` is appended with its `docket_ref` naming this
    application, and both `fees_assessed_total_cents` and `fee_balance_cents` on
    the owning carrier increase by that amount."
    PRD S3.3: "**`DENY`** moves the application `SUBMITTED → DENIED`, which is
    terminal, and captures the findings text into `denied_reason`. No authority
    is created. Denial is the compensating action for submission: a ledger entry
    with `entry_type` `FILING_FEE_REVERSAL_CREDIT` and an `amount_cents` equal to
    the negation of `filing_fee_cents` is appended with `docket_ref` naming this
    application, `fees_reversed_total_cents` increases by `filing_fee_cents`, and
    `fee_balance_cents` decreases by the same amount."
    PRD S3.3: "Because denial is the true inverse of submission, a
    submit-then-deny round trip must leave `fee_balance_cents` and the difference
    between `fees_assessed_total_cents` and `fees_reversed_total_cents` at
    exactly the values they held before the submission."

    Design: Difficulty/compensating_invariant/deny_reverses_the_filing_fee_debit_while_return_leaves_it_standing
    """
    env = setup_registry(api)
    before = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert before["fee_balance_cents"] == 0
    assert before["fees_assessed_total_cents"] == 0
    assert before["fees_reversed_total_cents"] == 0
    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 0

    application = _submit_new_application(api, env.carrier_id)
    assert application["filing_fee_cents"] == FILING_FEE_CENTS
    assert (
        expected_filing_fee("NEW", "FOR_HIRE_PROPERTY", 3)["filing_fee_cents"]
        == FILING_FEE_CENTS
    )

    submitted = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert submitted["fee_balance_cents"] == FILING_FEE_CENTS
    assert submitted["fees_assessed_total_cents"] == FILING_FEE_CENTS
    assert submitted["fees_reversed_total_cents"] == 0
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)

    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 1
    debit = assert_fee_ledger_entry(entries[0])
    assert debit["entry_type"] == "FILING_FEE_DEBIT"
    assert debit["amount_cents"] == FILING_FEE_CENTS
    assert debit["docket_ref"] is not None

    denied = review_application(api, application["id"], disposition="DENY")
    assert denied["status"] == "DENIED"

    authorities, authority_meta = validate_paginated(
        api.list_authorities(REGISTRY_ADMIN, application_id=application["id"])
    )
    assert authority_meta["total_count"] == 0, "a denial creates no authority"
    assert authorities == []

    after = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert after["fee_balance_cents"] == 0, (
        "a submit-then-deny round trip returns fee_balance_cents to its "
        "pre-submission value"
    )
    assert after["fees_assessed_total_cents"] == FILING_FEE_CENTS
    assert after["fees_reversed_total_cents"] == FILING_FEE_CENTS
    assert after["fees_paid_total_cents"] == 0
    assert (
        after["fees_assessed_total_cents"] - after["fees_reversed_total_cents"]
        == before["fees_assessed_total_cents"] - before["fees_reversed_total_cents"]
    )
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)

    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 2, "the ledger is append-only: two entries now"
    credit = assert_fee_ledger_entry(entries[1])
    assert credit["entry_type"] == "FILING_FEE_REVERSAL_CREDIT"
    assert credit["amount_cents"] == -FILING_FEE_CENTS
    assert credit["docket_ref"] == entries[0]["docket_ref"], (
        "both entries name the same application"
    )


def test_return_leaves_the_filing_fee_debit_standing(api):
    """PRD S3.3: "**`RETURN`** moves the application `SUBMITTED →
    RETURNED_FOR_CORRECTION`. No authority is created. Critically, the filing-fee
    debit **stands**: a return is not a compensating action, so the ledger is
    untouched and `fee_balance_cents` does not move. From
    `RETURNED_FOR_CORRECTION` the carrier may submit again, closing the loop
    `SUBMITTED → RETURNED_FOR_CORRECTION → SUBMITTED`, and that loop may be
    traversed without bound. Each traversal increments `submission_count` and
    charges nothing."
    PRD S3.3: "When `submission_count` becomes 2 or more, nothing is recomputed,
    no ledger entry is appended, and no carrier fee field moves at all. The fee
    is assessed exactly once per application no matter how many correction loops
    it makes."

    Design: Difficulty/compensating_invariant/deny_reverses_the_filing_fee_debit_while_return_leaves_it_standing
    """
    env = setup_registry(api)
    application = _submit_new_application(api, env.carrier_id)
    assert application["filing_fee_cents"] == FILING_FEE_CENTS
    assert application["submission_count"] == 1

    returned = review_application(api, application["id"], disposition="RETURN")
    assert returned["status"] == "RETURNED_FOR_CORRECTION"

    after = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert after["fee_balance_cents"] == FILING_FEE_CENTS, (
        "a return is not a compensating action, so the debit stands"
    )
    assert after["fees_assessed_total_cents"] == FILING_FEE_CENTS
    assert after["fees_reversed_total_cents"] == 0
    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 1, "the ledger is untouched by a return"
    assert entries[0]["entry_type"] == "FILING_FEE_DEBIT"
    assert entries[0]["amount_cents"] == FILING_FEE_CENTS
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)

    resubmitted = submit_application(api, env.carrier_id, application["id"])
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submission_count"] == 2
    assert resubmitted["filing_fee_cents"] == FILING_FEE_CENTS

    reloaded = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert reloaded["fee_balance_cents"] == FILING_FEE_CENTS
    assert reloaded["fees_assessed_total_cents"] == FILING_FEE_CENTS
    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 1, "a second submission charges nothing"
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)


def test_deny_and_return_on_two_applications_leave_one_debit_outstanding(api):
    """PRD S3.3: "Because denial is the true inverse of submission, a
    submit-then-deny round trip must leave `fee_balance_cents` and the difference
    between `fees_assessed_total_cents` and `fees_reversed_total_cents` at
    exactly the values they held before the submission. A return, to repeat the
    point from the other side, must leave the debit standing. The two ledger
    identities of §3.1 are re-asserted after each of these appends."
    PRD S3.1: "First, a carrier's `fee_balance_cents` equals the signed sum of
    the `amount_cents` of every ledger entry belonging to that carrier. Second,
    `fee_balance_cents` equals `fees_assessed_total_cents` minus
    `fees_reversed_total_cents` minus `fees_paid_total_cents`, where
    `fees_assessed_total_cents` is the lifetime sum of that carrier's
    `FILING_FEE_DEBIT` amounts, `fees_reversed_total_cents` is the lifetime sum
    of the absolute values of its `FILING_FEE_REVERSAL_CREDIT` amounts, and
    `fees_paid_total_cents` is the lifetime sum of the absolute values of its
    `FEE_PAYMENT_CREDIT` amounts."

    Design: Difficulty/compensating_invariant/deny_reverses_the_filing_fee_debit_while_return_leaves_it_standing
    """
    env = setup_registry(api)

    first = _submit_new_application(api, env.carrier_id)
    denied = review_application(api, first["id"], disposition="DENY")
    assert denied["status"] == "DENIED"
    midpoint = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert midpoint["fee_balance_cents"] == 0
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)

    second = _submit_new_application(api, env.carrier_id)
    assert second["filing_fee_cents"] == FILING_FEE_CENTS
    returned = review_application(api, second["id"], disposition="RETURN")
    assert returned["status"] == "RETURNED_FOR_CORRECTION"

    carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert carrier["fees_assessed_total_cents"] == 129582
    assert carrier["fees_reversed_total_cents"] == FILING_FEE_CENTS
    assert carrier["fees_paid_total_cents"] == 0
    assert carrier["fee_balance_cents"] == FILING_FEE_CENTS, (
        "only the returned application's debit is still outstanding"
    )
    assert_fee_ledger_identities(api, env.carrier_id, REGISTRY_ADMIN)

    entries, meta = _ledger(api, env.carrier_id)
    assert meta["total_count"] == 3
    assert [entry["entry_type"] for entry in entries] == [
        "FILING_FEE_DEBIT",
        "FILING_FEE_REVERSAL_CREDIT",
        "FILING_FEE_DEBIT",
    ]
    assert [entry["amount_cents"] for entry in entries] == [
        FILING_FEE_CENTS,
        -FILING_FEE_CENTS,
        FILING_FEE_CENTS,
    ]


# ---------------------------------------------------------------------------
# Suspension and restoration conserve the contract and shipment population
# ---------------------------------------------------------------------------
SUSPEND_AT = "2026-09-10T00:00:00.000Z"
RESTORE_AT = "2026-09-14T00:00:00.000Z"
MONTHLY_COMMITTED_CENTS = 90000000
SUSPENSION_ESTIMATE_CENTS = 50400000
SETTLED_WITH_ONE_EMBARGO_CENTS = 2250000
SETTLED_WITHOUT_EMBARGO_CENTS = 1800000


def _authority_with_two_contracts_suspended(api):
    """One departed shipment on contract A, a bare contract B, both suspended
    by the cancellation of the authority's only BIPD filing."""
    env = setup_active_authority_with_shipment(
        api, depart=True, tender_at="2026-09-02T00:00:00Z"
    )
    env.contract_b = create_contract(
        api, env.carrier_id, env.authority_id, shipper_name="Sudan Feedyard LP"
    )
    env.contract_b_id = env.contract_b["id"]
    env.carrier_active = get_success_data(
        api.get_carrier(env.carrier_id, REGISTRY_ADMIN)
    )
    env = setup_suspended_by_filing_cancel(api, cancel_at="2026-09-10T00:00:00Z", env=env)
    return env


def _contract(api, contract_id):
    return get_success_data(api.get_contract(contract_id, REGISTRY_ADMIN))


def _shipments_of(api, contract_id):
    rows, meta = validate_paginated(
        api.list_shipments(REGISTRY_ADMIN, contract_id=contract_id)
    )
    return rows, meta


def test_suspension_moves_the_whole_contract_population_and_embargoes_its_shipments(api):
    """PRD S2.10: "Because the authority became `SUSPENDED`, hop two visits every
    `CustomerContract` whose `authority_id` names it and whose `status` is
    `ACTIVE`: each becomes `SUSPENDED_BY_AUTHORITY`, its `suspended_at` is set to
    the current logical time, its `resumed_at` is reset to null, its
    `disruption_liability_cents` is written from the suspension-estimate variant
    described in §3.9, and its `disruption_liability_variant` becomes
    `SUSPENSION_ESTIMATE`."
    PRD S2.10: "Because each of those contracts became `SUSPENDED_BY_AUTHORITY`,
    hop three visits every `Shipment` whose `contract_id` names that contract and
    whose `status` is either `TENDERED` or `IN_TRANSIT`: each records its current
    status into `pre_embargo_status`, becomes `EMBARGOED`, and has `embargoed_at`
    set to the current logical time; the contract's `embargoed_shipment_count` is
    then set to the number of shipments this hop moved for it."
    PRD S2.10: "Finally the authority's counters move: `active_contract_count`
    decreases by the number of contracts hop two moved and
    `suspended_contract_count` increases by that same number, and the owning
    carrier's `active_authority_count` decreases by one."
    PRD S3.9: "Take the interval from the contract's `suspended_at` to its
    `term_end_at`, convert it to days and round **up** to the next whole day;
    multiply the daily figure by that day count and then by the 15 percent
    penalty rate; round the product half-up to whole cents."

    Design: Difficulty/compensating_invariant/suspension_and_cure_conserve_the_contract_and_shipment_population
    """
    env = _authority_with_two_contracts_suspended(api)
    assert expected_suspension_estimate(MONTHLY_COMMITTED_CENTS, 112) == (
        SUSPENSION_ESTIMATE_CENTS
    )

    assert env.authority["authority_status"] == "SUSPENDED"
    assert env.authority["suspension_reason"] == "INSURANCE_LAPSE"
    assert env.authority["insurance_status"] == "LAPSED"
    assert env.authority["suspended_at"] == SUSPEND_AT
    assert env.authority["active_contract_count"] == 0
    assert env.authority["suspended_contract_count"] == 2

    for contract_id, embargoed in ((env.contract_id, 1), (env.contract_b_id, 0)):
        contract = assert_customer_contract(_contract(api, contract_id))
        assert contract["status"] == "SUSPENDED_BY_AUTHORITY"
        assert contract["suspended_at"] == SUSPEND_AT
        assert contract["resumed_at"] is None
        assert contract["disruption_liability_cents"] == SUSPENSION_ESTIMATE_CENTS
        assert contract["disruption_liability_variant"] == "SUSPENSION_ESTIMATE"
        assert contract["embargoed_shipment_count"] == embargoed

    shipment = assert_shipment(
        get_success_data(api.get_shipment(env.shipment_id, REGISTRY_ADMIN))
    )
    assert shipment["status"] == "EMBARGOED"
    assert shipment["pre_embargo_status"] == "IN_TRANSIT"
    assert shipment["embargoed_at"] == SUSPEND_AT
    assert shipment["embargo_released_at"] is None
    assert shipment["embargo_days_accrued"] == 0

    assert_contract_population_identity(api, env.authority_id, REGISTRY_ADMIN)


def test_cure_restores_the_population_and_settles_the_actual_liability(api):
    """PRD S2.10: "Hop two visits every `CustomerContract` on that authority whose
    `status` is `SUSPENDED_BY_AUTHORITY`: each returns to `ACTIVE`, its
    `resumed_at` is set to the current logical time, its
    `disruption_liability_cents` is rewritten from the settled-actual variant of
    §3.9, and its `disruption_liability_variant` becomes `SETTLED_ACTUAL`."
    PRD S2.10: "Hop three visits every `Shipment` on each of those contracts whose
    `status` is `EMBARGOED`: each returns to exactly the status recorded in its
    `pre_embargo_status`, sets `embargo_released_at` to the current logical time,
    adds to `embargo_days_accrued` the number of whole days between `embargoed_at`
    and the current logical time rounded up to the next whole day, and then resets
    `pre_embargo_status` to `NONE`."
    PRD S3.9: "First, take the interval from `suspended_at` to `resumed_at`,
    convert it to days and round up to the next whole day — call that the elapsed
    day count. Second, multiply the daily figure by that elapsed day count and
    then by the 15 percent penalty rate, and round half-up to whole cents; that is
    the base charge. Third, multiply the daily figure by the contract's
    `embargoed_shipment_count` and then by the same 15 percent rate, and round
    half-up to whole cents; that is the per-shipment penalty. Fourth, add the base
    charge and the per-shipment penalty to obtain the pre-waiver subtotal. Fifth,
    decide the waiver rate **from that pre-waiver subtotal, not from the final
    figure**: the rate is 10 percent when the pre-waiver subtotal is at least
    $50,000 and zero otherwise — a subtotal of exactly $50,000 is waived."

    Design: Difficulty/compensating_invariant/suspension_and_cure_conserve_the_contract_and_shipment_population
    """
    env = _authority_with_two_contracts_suspended(api)
    assert expected_settled_actual(MONTHLY_COMMITTED_CENTS, 4, 1) == (
        SETTLED_WITH_ONE_EMBARGO_CENTS
    )
    assert expected_settled_actual(MONTHLY_COMMITTED_CENTS, 4, 0) == (
        SETTLED_WITHOUT_EMBARGO_CENTS
    )

    env = cure_with_replacement_filing(
        api, env, cure_at="2026-09-14T00:00:00Z", policy_number="BIPD-2"
    )

    assert env.authority["authority_status"] == "ACTIVE"
    assert env.authority["suspension_reason"] == "NONE"
    assert env.authority["suspended_at"] is None
    assert env.authority["insurance_status"] == "FILED"
    assert env.authority["active_contract_count"] == 2
    assert env.authority["suspended_contract_count"] == 0

    contract_a = assert_customer_contract(_contract(api, env.contract_id))
    assert contract_a["status"] == "ACTIVE"
    assert contract_a["resumed_at"] == RESTORE_AT
    assert contract_a["disruption_liability_cents"] == SETTLED_WITH_ONE_EMBARGO_CENTS
    assert contract_a["disruption_liability_variant"] == "SETTLED_ACTUAL"

    contract_b = assert_customer_contract(_contract(api, env.contract_b_id))
    assert contract_b["status"] == "ACTIVE"
    assert contract_b["resumed_at"] == RESTORE_AT
    assert contract_b["disruption_liability_cents"] == SETTLED_WITHOUT_EMBARGO_CENTS, (
        "a contract with no embargoed shipment carries only the base charge"
    )
    assert contract_b["disruption_liability_variant"] == "SETTLED_ACTUAL"

    shipment = assert_shipment(
        get_success_data(api.get_shipment(env.shipment_id, REGISTRY_ADMIN))
    )
    assert shipment["status"] == "IN_TRANSIT", (
        "the shipment returns to exactly its pre_embargo_status"
    )
    assert shipment["pre_embargo_status"] == "NONE"
    assert shipment["embargo_released_at"] == RESTORE_AT
    assert shipment["embargo_days_accrued"] == 4

    assert_no_embargoed_shipments(api, env.contract_id, REGISTRY_ADMIN)
    assert_no_embargoed_shipments(api, env.contract_b_id, REGISTRY_ADMIN)
    assert_contract_population_identity(api, env.authority_id, REGISTRY_ADMIN)


def test_the_suspension_restoration_round_trip_loses_no_shipment_or_authority(api):
    """PRD S2.10: "Two population identities must hold at all times, and they are
    re-asserted after every suspension, restoration and termination. First, an
    authority's `active_contract_count` plus its `suspended_contract_count`
    always equals the number of that authority's contracts whose `status` is not
    `TERMINATED`. Second, a suspension followed by a restoration is a true round
    trip: `active_contract_count` returns to its pre-suspension value,
    `suspended_contract_count` returns to zero, and every shipment on those
    contracts holds exactly the status it held before the embargo — which is the
    whole reason `pre_embargo_status` is persisted. After a restoration completes,
    no shipment on the restored contracts remains `EMBARGOED`. No shipment may be
    lost to, or gained by, the round trip."
    PRD S2.10: "The authority's `suspended_contract_count` decreases by the number
    of contracts hop two moved, its `active_contract_count` increases by that same
    number, and the carrier's `active_authority_count` increases by one."

    Design: Difficulty/compensating_invariant/suspension_and_cure_conserve_the_contract_and_shipment_population
    """
    env = _authority_with_two_contracts_suspended(api)
    assert env.carrier_active["active_authority_count"] == 1

    suspended_carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert suspended_carrier["active_authority_count"] == 0
    rows_a, meta_a = _shipments_of(api, env.contract_id)
    rows_b, meta_b = _shipments_of(api, env.contract_b_id)
    assert meta_a["total_count"] == 1
    assert meta_b["total_count"] == 0
    assert [row["status"] for row in rows_a] == ["EMBARGOED"]
    assert_contract_population_identity(api, env.authority_id, REGISTRY_ADMIN)

    env = cure_with_replacement_filing(
        api, env, cure_at="2026-09-14T00:00:00Z", policy_number="BIPD-2"
    )

    restored_carrier = get_success_data(api.get_carrier(env.carrier_id, REGISTRY_ADMIN))
    assert restored_carrier["active_authority_count"] == 1, (
        "active_authority_count returns to its pre-suspension value"
    )
    assert env.authority["active_contract_count"] == 2
    assert env.authority["suspended_contract_count"] == 0

    rows_a, meta_a = _shipments_of(api, env.contract_id)
    rows_b, meta_b = _shipments_of(api, env.contract_b_id)
    assert meta_a["total_count"] == 1, "no shipment is lost to the round trip"
    assert meta_b["total_count"] == 0, "and none is gained by it"
    assert [row["status"] for row in rows_a] == ["IN_TRANSIT"]
    assert_contract_population_identity(api, env.authority_id, REGISTRY_ADMIN)
