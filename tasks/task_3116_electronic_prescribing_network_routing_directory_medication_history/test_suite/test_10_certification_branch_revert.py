"""The NetworkParticipant certification machine's branching-with-revert shape.

CERTIFIED is not terminal: the participant can be demoted back into certification, promoted
again, and finally suspended, and each move re-derives the status of every endpoint it owns.
"""
from test_helpers import (
    validate_success,
    set_clock,
    create_pharmacy,
    add_endpoint,
    start_certification_window,
    reload_participant,
    reload_endpoint,
    certify_participant,
    api_client,
    TEST_USERS,
)

OPERATOR = TEST_USERS["network_operator_headers"]

MED_HISTORY_CODES = (
    "CONNECTIVITY",
    "SCRIPT_NEW_RX",
    "ELIGIBILITY_FORMULARY",
    "MED_HISTORY",
)


def _pharmacy_with_two_service_endpoints():
    """Riverbend Pharmacy holding a MED_HISTORY endpoint and an ELIGIBILITY_FORMULARY
    endpoint, both PENDING_CERT, with certification_status UNCERTIFIED."""
    set_clock()
    pharmacy = create_pharmacy()
    ep_hist = add_endpoint(
        pharmacy["id"], service_set="MED_HISTORY", endpoint_role="RECEIVER",
        service_level="ELIGIBLE_A", sla_response_minutes=60,
        message_standard="NCPDP_SCRIPT_2022011",
    )
    ep_elig = add_endpoint(
        pharmacy["id"], service_set="ELIGIBILITY_FORMULARY", endpoint_role="RECEIVER",
        service_level="ELIGIBLE_A", sla_response_minutes=60,
        message_standard="NCPDP_SCRIPT_2022011",
    )
    assert ep_hist["status"] == "PENDING_CERT"
    assert ep_elig["status"] == "PENDING_CERT"
    assert reload_participant(pharmacy["id"])["certification_status"] == "UNCERTIFIED"
    return pharmacy, ep_hist, ep_elig


def test_promotion_enables_pending_endpoints_and_demotion_returns_them(api):
    """PRD §3.2: "The participant's `certification_status` becomes `CERTIFIED`, and — in the
    same transaction — every one of its endpoints still sitting in `PENDING_CERT` becomes
    `ACTIVE`, and `directory_listed` is recomputed, typically flipping from false to true."
    PRD §3.2: "Every reopen of a certified participant is consequential for the directory:
    each of that participant's endpoints that is currently `ACTIVE` drops back to
    `PENDING_CERT`, and `directory_listed` is recomputed — which, for a participant whose
    endpoints were all serving, flips it from true to false."

    Design: Difficulty/non_linear_state_machine/network_participant_certification_branch_with_revert
    """
    pharmacy, ep_hist, ep_elig = _pharmacy_with_two_service_endpoints()

    certified = certify_participant(pharmacy["id"], test_codes=MED_HISTORY_CODES)
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["directory_listed"] is True
    # The certification window reset the list, then the four recorded passes repopulated it
    # in first-pass order.
    assert certified["certification_tests_passed"] == list(MED_HISTORY_CODES)

    assert reload_endpoint(ep_hist["id"])["status"] == "ACTIVE"
    assert reload_endpoint(ep_elig["id"])["status"] == "ACTIVE"

    # The revert edge: reopening the window drops every ACTIVE endpoint back to PENDING_CERT
    # and resets the pass list.
    demoted = start_certification_window(pharmacy["id"])
    assert demoted["certification_status"] == "IN_CERTIFICATION"
    assert demoted["directory_listed"] is False
    assert reload_endpoint(ep_hist["id"])["status"] == "PENDING_CERT"
    assert reload_endpoint(ep_elig["id"])["status"] == "PENDING_CERT"


def test_the_participant_can_be_promoted_again_and_then_suspended(api):
    """PRD §3.2: "The same operation also serves as the reopen path. A participant sitting in
    `SUSPENDED` may be returned to `IN_CERTIFICATION`, again requiring at least one endpoint
    row and again resetting `certification_tests_passed`"
    PRD §3.6: "The participant's `certification_status` becomes `SUSPENDED`; every one of its
    directory endpoints becomes `DISABLED` regardless of prior status; `directory_listed` is
    recomputed and lands false; and the participant's `version` increments."

    Design: Difficulty/non_linear_state_machine/network_participant_certification_branch_with_revert
    """
    pharmacy, ep_hist, ep_elig = _pharmacy_with_two_service_endpoints()

    certify_participant(pharmacy["id"], test_codes=MED_HISTORY_CODES)
    reopen = start_certification_window(pharmacy["id"])
    assert reopen["certification_status"] == "IN_CERTIFICATION"

    # Re-record and promote again: CERTIFIED → IN_CERTIFICATION → CERTIFIED executed twice.
    re_certified = certify_participant(pharmacy["id"], test_codes=MED_HISTORY_CODES)
    assert re_certified["certification_status"] == "CERTIFIED"
    assert re_certified["directory_listed"] is True
    assert reload_endpoint(ep_hist["id"])["status"] == "ACTIVE"
    assert reload_endpoint(ep_elig["id"])["status"] == "ACTIVE"

    # The third edge out of CERTIFIED.
    suspended_ok = api_suspend(pharmacy["id"])
    validate_success(suspended_ok, 200)
    suspended = reload_participant(pharmacy["id"])
    assert suspended["certification_status"] == "SUSPENDED"
    assert suspended["directory_listed"] is False
    assert reload_endpoint(ep_hist["id"])["status"] == "DISABLED"
    assert reload_endpoint(ep_elig["id"])["status"] == "DISABLED"


def api_suspend(participant_id):
    return api_client.suspend_participant(participant_id, OPERATOR)