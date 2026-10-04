"""Dispute workflow tests: the appeal loop with compensating reinstatement
and re-decision."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    create_publisher,
    create_published_channel,
    make_publisher_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_removed_channel_dispute():
    publisher = create_publisher(legal_name="Loop Pub")
    channel = create_published_channel(publisher)
    get_success_data(api_client.remove_channel(
        channel["id"], {"reason": "policy violation strike 3"}, ADMIN,
    ))
    resp = api_client.create_dispute(
        {
            "publisher_id": publisher["id"],
            "subject_type": "CHANNEL_REMOVAL",
            "channel_id": channel["id"],
            "reason": "removal contested",
        },
        make_publisher_headers(publisher["id"]),
    )
    dispute = get_success_data(resp)
    return publisher, channel, dispute


def test_overturned_channel_removal_reinstates_channel():
    """PRD §3.9: "For a channel-removal dispute decided `OVERTURNED`, the
    removal is compensated: the channel moves from `REMOVED` back to
    `PUBLISHED` with `policy_hold` cleared to false. For a channel-removal
    dispute decided `UPHELD`, the channel stays `REMOVED`."

    Design: Corner/state_machines/dispute_appeal_cycle_reopens_evidence_and_redecides
    """
    publisher, channel, dispute = _setup_removed_channel_dispute()
    get_success_data(api_client.triage_dispute(dispute["id"], ADMIN))
    get_success_data(api_client.request_dispute_evidence(dispute["id"], ADMIN))
    decided = get_success_data(api_client.decide_dispute(
        dispute["id"], {"decision": "OVERTURNED"}, ADMIN,
    ))
    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "OVERTURNED"

    reinstated = get_success_data(api_client.get_channel(channel["id"], ADMIN))
    assert reinstated["status"] == "PUBLISHED"
    assert reinstated["policy_hold"] is False


def test_dispute_appeal_cycle_redecides_upheld():
    """PRD §3.9: "Appeal moves the dispute to `APPEALED`, from which the
    platform requests evidence again, returning it to `EVIDENCE` for another
    decision loop."

    Design: Corner/state_machines/dispute_appeal_cycle_reopens_evidence_and_redecides
    """
    publisher, channel, dispute = _setup_removed_channel_dispute()
    pub_headers = make_publisher_headers(publisher["id"])
    get_success_data(api_client.triage_dispute(dispute["id"], ADMIN))
    get_success_data(api_client.request_dispute_evidence(dispute["id"], ADMIN))
    get_success_data(api_client.decide_dispute(
        dispute["id"], {"decision": "OVERTURNED"}, ADMIN,
    ))

    appealed = validate_success(api_client.appeal_dispute(
        dispute["id"], {"reason": "platform appeals"}, pub_headers,
    ))
    assert appealed["status"] == "APPEALED"

    evidence = get_success_data(
        api_client.request_dispute_evidence(dispute["id"], ADMIN)
    )
    assert evidence["status"] == "EVIDENCE"

    redecided = get_success_data(api_client.decide_dispute(
        dispute["id"], {"decision": "UPHELD"}, ADMIN,
    ))
    assert redecided["status"] == "DECIDED"
    assert redecided["decision"] == "UPHELD"
