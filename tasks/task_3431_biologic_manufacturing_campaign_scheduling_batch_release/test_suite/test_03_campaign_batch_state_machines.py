"""Campaign and batch state-machine admission rules, including the allocate cycle."""
from test_helpers import (
    ApiErrorId, TEST_USERS, USER_IDS,
    validate_success, validate_error,
    setup_campaign, setup_batch_upstream,
    advance_campaign, get_batch_entity,
    make_manufacturing_operator_headers,
)


def test_campaign_advance_skip_proposed_to_seed_rejected(api, process_engineer_headers,
                                                         platform_admin_headers):
    """PRD §3.3: "Starting the seed train — advancing an `ALLOCATED` campaign to `SEED_IN_PROGRESS` — evaluates four preconditions in order. The campaign must be `ALLOCATED` (`ERR_INVALID_CAMPAIGN_STATE`)."

    Design: Corner/state_machines/campaign_advance_skip_proposed_to_seed_rejected
    """
    env = setup_campaign()
    camp_id = env["campaign"]["id"]
    resp = api.advance_campaign(camp_id, "SEED_IN_PROGRESS", process_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_CAMPAIGN_STATE)
    reread = validate_success(api.get_campaign(camp_id, platform_admin_headers))
    assert reread["status"] == "PROPOSED"


def test_batch_advance_skip_upstream_to_complete_rejected(api, platform_admin_headers):
    """PRD §3.4: "From `UPSTREAM` to `DOWNSTREAM`, the batch must actually be in `UPSTREAM` (`ERR_INVALID_BATCH_STATE`)"
    PRD §3.4: "From `DOWNSTREAM` to `PROCESS_COMPLETE`, the batch must be in `DOWNSTREAM` and the evidence bar rises to the whole record"

    Design: Corner/state_machines/batch_advance_skip_upstream_to_complete_rejected
    """
    env = setup_batch_upstream()
    batch_id = env["batch"]["id"]
    headers = make_manufacturing_operator_headers(USER_IDS["operator"])
    resp = api.advance_batch(batch_id, "PROCESS_COMPLETE", headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_BATCH_STATE)
    assert get_batch_entity(batch_id)["process_status"] == "UPSTREAM"


def test_allocate_deallocate_reallocate_version_sequence(api):
    """PRD §3.2: "Every successful campaign advance — allocation, de-allocation, seed start, production start — increments the campaign's `version` by one."
    PRD §3.2: "De-allocation moves an `ALLOCATED` campaign back to `PROPOSED`"

    Design: Difficulty/non_linear_state_machine/campaign_allocate_deallocate_reallocate_cycle
    """
    env = setup_campaign()
    camp_id = env["campaign"]["id"]
    assert env["campaign"]["version"] == 1
    allocated = advance_campaign(camp_id, "ALLOCATED")
    assert allocated["status"] == "ALLOCATED" and allocated["version"] == 2
    deallocated = advance_campaign(camp_id, "PROPOSED")
    assert deallocated["status"] == "PROPOSED" and deallocated["version"] == 3
    reallocated = advance_campaign(camp_id, "ALLOCATED")
    assert reallocated["status"] == "ALLOCATED" and reallocated["version"] == 4


def test_allocate_deallocate_reallocate_hours_unchanged(api, platform_admin_headers):
    """PRD §3.2: "At creation the system also computes the campaign's `allocated_hours` — the capacity-hours it will charge to its site month once allocated"
    PRD §2.11: "campaigns in `PROPOSED`, `COMPLETED`, or `PREEMPTED` consume nothing."

    Design: Difficulty/non_linear_state_machine/campaign_allocate_deallocate_reallocate_cycle
    """
    env = setup_campaign()
    camp_id = env["campaign"]["id"]
    for target in ("ALLOCATED", "PROPOSED", "ALLOCATED"):
        advance_campaign(camp_id, target)
        reread = validate_success(api.get_campaign(camp_id, platform_admin_headers))
        assert reread["allocated_hours"] == 72, \
            "de-allocation does not rewrite the stored charge"
