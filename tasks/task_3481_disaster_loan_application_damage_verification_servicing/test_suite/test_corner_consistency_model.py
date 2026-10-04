"""Corner queue: consistency_model — a mutating response and the immediately
following read observe the same committed state."""
from test_helpers import (
    decide_application,
    is_valid_uuid,
    list_tranche_data,
    read_loan,
    setup_application_in_decision_pending,
)


def test_approval_immediately_visible_in_same_request_and_read(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
    PRD §3.6: "Hop one creates the `Loan` in `PENDING_ACCEPTANCE` lifecycle status with `servicing_status` `CURRENT`: `application_id` and a denormalized `applicant_id` tie it to the file, `loan_purpose` is copied from the application, `interest_rate` and `term_months` follow Section 2.8, `deferral_months` is 12, and `commitment_amount_cents` starts equal to `approved_amount_cents`."
    PRD §3.6: "Finally, the application's `loan_id` is set — exactly once, linking the file to the new loan — and the application's `version` increments."
    PRD §3.6: "Hop two spawns the disbursement schedule: tranche stage 1 is the smaller of 2500000 cents and the approved amount, and any remainder is split into stage 2 taking the floor of half the remainder and stage 3 taking the rest; a tranche whose computed amount would be zero is not created."

    Design: Corner/consistency_model/approval_immediately_visible_in_same_request_and_read
    """
    # Net verified loss 25000000 - 5000000 = 20000000 covers the request.
    ctx = setup_application_in_decision_pending(
        requested_amount_cents=20000000,
        assessed_loss_cents=25000000,
        insurance_proceeds_cents=5000000)

    # The decision response itself carries the updated application, loan set.
    decided = decide_application(ctx, decision="APPROVED")
    assert decided["status"] == "APPROVED"
    assert decided["loan_id"] is not None
    assert is_valid_uuid(decided["loan_id"])

    # The very next read observes the fully persisted origination cascade.
    loan = read_loan(ctx, loan_id=decided["loan_id"])
    assert loan["lifecycle_status"] == "PENDING_ACCEPTANCE"
    assert loan["servicing_status"] == "CURRENT"
    assert loan["approved_amount_cents"] == 20000000
    assert loan["commitment_amount_cents"] == 20000000
    assert loan["disbursed_total_cents"] == 0

    # 20000000 -> 2500000 / floor(17500000/2)=8750000 / remainder 8750000.
    tranches = list_tranche_data(ctx)
    assert [t["amount_cents"] for t in tranches] == [2500000, 8750000, 8750000]
    assert all(t["status"] == "SCHEDULED" for t in tranches)
