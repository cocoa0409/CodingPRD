"""The consistency model: every derived figure a request causes is already applied when that request
responds, and a request that is refused applies nothing that has to be tidied up later.
"""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aums,
    make_officer_headers,
    make_permittee_headers,
)
from test_helpers import factories as f
from test_helpers.fixtures import (
    drafted_aoi_setup,
    get_allotment,
    get_aoi,
    get_bill,
    get_permittee,
    get_use_record,
)


def test_every_derived_change_a_request_causes_is_already_visible_when_it_answers():
    """Three proofs in one walk. The issue response itself already carries the snapshot and the billable
    figure, and the ledger, the bill and the permittee balance it caused are readable by the very next
    call with nothing in between. Acceptance performs both of its declared hops inside one request and
    answers BILLED, never the intermediate USE_REPORTED, and the supersession of the preliminary bill is
    complete on the same response. And the refused overpayment leaves nothing half-applied: the bill's
    amount_paid_cents and the permittee's balance are byte-for-byte what they were, so the payment that
    follows for the exact remaining balance settles the year and closes the instruction at once.

    PRD 3.4: "The `aoi_status` becomes `ISSUED`, `authorized_aums_at_issue` is re-stamped from
    `authorized_aums`, the allotment's `allocated_aums` and `open_aums` are recomputed by the ledger of
    §2.9 — `allocated_aums` rising by exactly this instruction's `billable_aums` — the allotment's
    `version` is bumped, and `scheduled_aums` is refreshed on every pasture the instruction's use records
    name."
    PRD 3.4: "When `billable_aums` is greater than zero, a preliminary bill of `bill_type`
    `PRELIMINARY_USE` is raised, computed by the preliminary variant of the use-bill arithmetic in §3.6,
    and the permittee's `outstanding_balance_cents` is recomputed to include it."
    PRD 2.9: "`allocated_aums` is the sum, over every annual operating instruction whose permit belongs
    to this allotment, whose `grazing_year` equals the allotment's `current_grazing_year`, and whose
    `aoi_status` is one of `ISSUED`, `USE_REPORTED`, `BILLED` or `CLOSED`, of that instruction's
    `authorized_aums` less its `nonuse_aums`."
    PRD 3.6: "Step two computes `base_amount_cents` as `billed_aums` multiplied by the grazing fee rate
    of 172 cents per AUM, rounded half-up to a whole cent; that same 172 is recorded on the bill as its
    `fee_rate_cents_per_aum`."
    PRD 3.6: "`admin_fee_cents` is 0 when `base_amount_cents` is below 50,000 cents, 2,500 cents when
    `base_amount_cents` is at least 50,000 and below 200,000 cents, and 6,000 cents when
    `base_amount_cents` is 200,000 cents or more."
    PRD 3.6: "Every use bill is raised in `bill_status` `ISSUED` with `amount_paid_cents` of 0 and a
    `due_date` of the logical-clock date at issuance plus 30 days."
    PRD 3.6: "The **final** variant, used when an accepted use report is billed, sets `billed_aums` to
    whichever is larger of the instruction's `actual_aums_total` and one quarter of the instruction's
    `authorized_aums` less its `nonuse_aums`, that quarter being floored to a whole AUM"
    PRD 3.6: "When the preliminary bill's `amount_paid_cents` is exactly 0, that bill moves to
    `bill_status` `VOIDED` and a bill of `bill_type` `FINAL_USE` is issued for the final total with
    `superseded_bill_id` set to the voided bill's `id`."
    PRD 3.5: "On success the three reported values are stored, the leg's `actual_aums` is computed by
    exactly the same forage arithmetic as `planned_aums` — head count times animal-unit equivalent times
    whole days in the half-open window, divided by 30, rounded half-up to 2 decimal places once — and the
    leg moves `SCHEDULED → ACTUAL_REPORTED`."
    PRD 3.5: "Reporting a leg does **not** move the instruction's own `aoi_status`; the officer's
    acceptance does that."
    PRD 3.5: "Acceptance is a single atomic operation performed by an `AuthorizedOfficer` that carries
    the instruction through two hops, `ISSUED → USE_REPORTED → BILLED`."
    PRD 3.5: "The second hop moves every use record of the instruction from `ACTUAL_REPORTED` to
    `ACCEPTED`, computes the final charge by the final variant of §3.6, settles the difference against the
    preliminary bill, sets `aoi_status` to `BILLED`, and recomputes the permittee's
    `outstanding_balance_cents`."
    PRD 2.6: "**Overpayment** — `ERR_OVERPAYMENT`, HTTP 422, on payment recording. The `amount_cents`
    must be at least 1 and must not exceed the bill's `total_amount_cents` less its `amount_paid_cents`;
    overpayment is refused outright rather than credited."
    PRD 3.6: "A successful payment increases `amount_paid_cents` by `amount_cents`, and when the
    accumulated `amount_paid_cents` reaches or exceeds `total_amount_cents` the bill moves to
    `bill_status` `PAID`."
    PRD 3.6: "when every non-voided bill of the linked operating instruction has reached `PAID`, that
    instruction moves `BILLED → CLOSED`"
    PRD 2.9: "A permittee's `outstanding_balance_cents` always equals the sum, over that permittee's
    bills whose `bill_status` is `ISSUED` or `DELINQUENT`, of each bill's `total_amount_cents` less its
    `amount_paid_cents`; bills in `PAID` or `VOIDED` contribute nothing, and an `ADJUSTMENT_CREDIT` bill
    contributes its negative total and so reduces the balance."

    Design: Corner/consistency_model/corner_every_derived_change_is_visible_in_the_same_request
    """
    setup = drafted_aoi_setup(
        authorized_aums=150, planned_head_count=150, planned_entry_date="2026-06-01",
        planned_exit_date="2026-07-01", total_permitted_aums=200, pasture_aum_capacity=200,
        carrying_capacity_aums=200, requested_aums=200,
        allotment_overrides={"name": "Immediate Consistency Allotment",
                             "admin_unit_code": "QB-186", "acres": 4200})
    allotment_id = setup["allotment"]["id"]
    permittee_id = setup["permittee"]["id"]
    holder = make_permittee_headers(permittee_id)

    # (1) The issue response is itself the proof; no follow-up read is needed to see the derived fields.
    issued = get_success_data(api_client.issue_aoi(setup["aoi"]["id"], make_officer_headers()))
    assert issued["aoi_status"] == "ISSUED"
    assert issued["authorized_aums"] == 150
    assert issued["authorized_aums_at_issue"] == 150
    assert issued["billable_aums"] == 150

    ledger = get_allotment(allotment_id)
    assert ledger["allocated_aums"] == 150, "already applied in the very next request"
    assert ledger["open_aums"] == 50

    items, meta = validate_paginated(api_client.list_bills(
        make_officer_headers(), {"aoi_id": setup["aoi"]["id"], "limit": 100}))
    assert meta["total_count"] == 1
    preliminary = items[0]
    assert preliminary["bill_type"] == "PRELIMINARY_USE"
    assert preliminary["billed_aums"] == 150
    assert preliminary["fee_rate_cents_per_aum"] == 172
    assert preliminary["base_amount_cents"] == 25800  # 150 x 172
    assert preliminary["admin_fee_cents"] == 0, "25,800 is below the 50,000-cent tier boundary"
    assert preliminary["total_amount_cents"] == 25800
    assert preliminary["due_date"] == "2026-08-31", "the clock date at issuance plus 30 days"
    assert get_permittee(permittee_id)["outstanding_balance_cents"] == 25800

    reported = get_success_data(api_client.report_actual_use(
        setup["use_record"]["id"], f.report_actual_use_payload(
            actual_entry_date="2026-06-01", actual_exit_date="2026-07-01",
            actual_head_count=150), holder))
    assert reported["record_status"] == "ACTUAL_REPORTED"
    assert_aums(reported["actual_aums"], 150.00)  # 150 head x CATTLE 1.0 x 30 days / 30
    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "ISSUED", "reporting moves no instruction"

    # (2) Both declared hops run inside the one acceptance request.
    accepted = get_success_data(api_client.accept_use_report(
        setup["aoi"]["id"], make_officer_headers()))
    assert accepted["aoi_status"] == "BILLED", "not the intermediate USE_REPORTED"
    assert_aums(accepted["actual_aums_total"], 150.00)
    assert get_use_record(setup["use_record"]["id"])["record_status"] == "ACCEPTED"
    assert get_bill(preliminary["id"])["bill_status"] == "VOIDED"

    final_items, final_meta = validate_paginated(api_client.list_bills(
        make_officer_headers(), {"aoi_id": setup["aoi"]["id"], "bill_status": "ISSUED",
                                 "limit": 100}))
    assert final_meta["total_count"] == 1
    final = final_items[0]
    assert final["bill_type"] == "FINAL_USE"
    assert final["superseded_bill_id"] == preliminary["id"]
    assert_aums(final["billed_aums"], 150.00)  # max(150.00, floor(150 / 4) == 37)
    assert final["total_amount_cents"] == 25800
    assert get_permittee(permittee_id)["outstanding_balance_cents"] == 25800

    # (3) A refused write reconciles nothing later either.
    validate_error(api_client.record_payment(final["id"], f.payment_payload(25801), holder),
                   ApiErrorId.ERR_OVERPAYMENT, 422)
    assert get_bill(final["id"])["amount_paid_cents"] == 0
    assert get_permittee(permittee_id)["outstanding_balance_cents"] == 25800

    paid = get_success_data(api_client.record_payment(
        final["id"], f.payment_payload(25800), holder), 201)
    assert paid["amount_paid_cents"] == 25800
    assert paid["bill_status"] == "PAID"

    assert get_aoi(setup["aoi"]["id"])["aoi_status"] == "CLOSED"
    settled = get_permittee(permittee_id)
    assert settled["outstanding_balance_cents"] == 0
    assert settled["permittee_status"] == "IN_GOOD_STANDING"
