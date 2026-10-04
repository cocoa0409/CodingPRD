"""Corner queue — consistency model: reads immediately after a mutation
observe its effects (no lag, no reconciliation pass)."""
from test_helpers import (
    TEST_USERS,
    get_contract,
    setup_accepted_report,
    validate_success,
)

AO = TEST_USERS["agency_officer_headers"]


def test_immediate_read_after_publish_disbursement(api):
    """PRD §3.8: "On publication the contract's `disbursed_cents` increases by
    the milestone amount, `remaining_cents` is recomputed under the §3.1
    invariant, and the report reaches the terminal `PUBLISHED` state."

    Design: Corner/consistency_model/immediate_read_after_publish_disbursement
    """
    ctx = setup_accepted_report()  # milestone 30000000 against award 90000000

    report = validate_success(api.publish_report(ctx["report"]["id"], AO), 200)
    assert report["status"] == "PUBLISHED"

    # The very next read in the same logical instant shows the disbursement.
    contract = get_contract(ctx["contract"]["id"])
    assert contract["disbursed_cents"] == 30000000
    assert contract["remaining_cents"] == 60000000
