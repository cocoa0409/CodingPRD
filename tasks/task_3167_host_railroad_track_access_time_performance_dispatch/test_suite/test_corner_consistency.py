"""Consistency corner: writes are immediately visible on the following read."""

from test_helpers import STATE_SPONSOR_HEADERS, fixtures


def test_activate_response_and_immediate_get_agree(api):
    """The activate response carries ACTIVE at version 2 and the next GET agrees.

    PRD: "All workflow state changes are immediate and strongly consistent, and every rule described in this document is enforced at the server on each request."
    PRD: "Activation is the host's act: a `HostRailroadRep` whose identity matches the agreement's `host_railroad_id` moves the agreement from `DRAFT` to `ACTIVE`, which bumps the agreement's `version` by one."
    Design: Corner/consistency/immediate_visibility_after_create_and_transition
    """
    net = fixtures.setup_draft_agreement(api)
    assert net["agreement"]["status"] == "DRAFT"
    assert net["agreement"]["version"] == 1

    activated = fixtures.activate_agreement(api, net, net["agreement"]["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["version"] == 2

    fetched = fixtures.read_agreement(api, net["agreement"]["id"], STATE_SPONSOR_HEADERS)
    assert fetched["status"] == "ACTIVE"
    assert fetched["version"] == 2
