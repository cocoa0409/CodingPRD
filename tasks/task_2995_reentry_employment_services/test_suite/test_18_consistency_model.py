"""
Read-your-writes on derived values.

Nothing in this system settles later. Whatever a write computes has to be present in the
response to that same write, and whatever a cascade moves has to be visible to the very
next read — never after a second call, a re-read, or a delay.
"""

from test_helpers.assertions import (
    assert_all_null,
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    validate_unpaginated,
)
from test_helpers.constants import (
    CATEGORY_ID_FEE,
    DECISION_APPROVED,
    FUNDING_POSTURE_OPEN,
    RECORD_DRUG_OFFENSE,
    REQUEST_APPROVED,
    REQUEST_SUBMITTED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
)


def test_derived_money_is_visible_in_the_same_response_that_creates_it(api, build):
    """
    The create response itself already prices the request — the ID_FEE coverage rate of
    1.00 gives 8,000, the middle fee tier gives 240, and the total is 8,240 — with no
    follow-up read, and the ledger consulted immediately after the approval already shows
    the commitment rather than a figure that catches up afterwards.

    PRD section 2.9: "Every counter, percentage, score, tier, posture, compliance flag,
    and money column named as computed in this document is recalculated by the server at
    the end of any write whose inputs it depends on — including writes that reach the
    field only through a cascade — and the recalculated value is what the response
    carries."

    PRD section 3.8: "`admin_fee_cents` is `requested_cents` multiplied by that rate,
    rounded half up to whole cents, and `total_charge_cents` is `requested_cents` plus
    `admin_fee_cents`."

    PRD section 3.8: "An accepted request is created with `status` of `SUBMITTED`,
    `info_rounds_used` of 0, `submitted_by_user_id` set from the caller's `X-User-ID`"

    Design: Corner/consistency_model/derived_money_is_visible_in_the_same_response_that_creates_it
    """
    grant = build.grant(
        authorized_cents=100000,
        per_participant_cap_cents=60000,
        retention_benchmark_pct=75.0,
    )
    participant = build.participant_zero_barrier_draft(
        record_categories=[RECORD_DRUG_OFFENSE]
    )

    created = validate_unpaginated(
        api.create_support_request(
            f.support_request_payload(
                participant["id"],
                grant["id"],
                build.grant_version(grant["id"]),
                [f.line_item("State ID replacement fee", 8000)],
                category=CATEGORY_ID_FEE,
                justification="Replacement state identification",
            ),
            CASE_MANAGER,
        ),
        201,
    )
    assert_money_cents(created, "requested_cents", 8000)
    assert_money_cents(created, "admin_fee_cents", 240)
    assert_money_cents(created, "total_charge_cents", 8240)
    assert created["status"] == REQUEST_SUBMITTED
    assert_int_field(created, "info_rounds_used", 0)
    assert_all_null(created, ["reviewed_by_user_id", "settled_by_user_id"])

    reviewed = validate_unpaginated(
        api.review_support_request(
            created["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
        )
    )
    assert reviewed["status"] == REQUEST_APPROVED

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 8240)
    assert_money_cents(ledger, "available_cents", 91760)
    assert_money_cents(ledger, "disbursed_cents", 0)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_ledger_identity(ledger)
