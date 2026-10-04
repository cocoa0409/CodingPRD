"""Distributors: listing/pagination, 404s, entity-backed reads, the
suspend/reinstate cycle and the three-strike termination rule."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, api_client,
    assert_distributor, make_distributor_contact_headers,
    validate_error, validate_paginated, validate_success,
)
from test_helpers import fixtures as fx

CM = TEST_USERS["channel_manager_headers"]


def test_distributors_list_paginates_with_total_count_and_has_more():
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0."
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the response envelope."
    PRD §2.3: "Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order."

    Design: Corner/entities/distributors_list_paginates_with_total_count_and_has_more
    """
    market = fx.create_market()
    d1 = fx.create_distributor_record(market["id"], legal_name="Ace Distribution")
    d2 = fx.create_distributor_record(market["id"], legal_name="Beta Wholesale",
                                      channels_served=["MASS"],
                                      credit_limit_cents=2000000)
    d3 = fx.create_distributor_record(market["id"], legal_name="Cobalt Trade",
                                      channels_served=["INDUSTRIAL"],
                                      credit_limit_cents=3000000)
    all_ids = {d1["id"], d2["id"], d3["id"]}

    page1, meta1 = validate_paginated(
        api_client.list_distributors(CM, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api_client.list_distributors(CM, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False

    assert {r["id"] for r in page1 + page2} == all_ids
    stamps = [r["created_at"] for r in page1 + page2]
    assert stamps == sorted(stamps), "rows are created_at ascending"

    page_all, meta_all = validate_paginated(api_client.list_distributors(CM))
    assert len(page_all) == 3
    assert meta_all["limit"] == 10 and meta_all["offset"] == 0, \
        "omitted parameters default to limit 10 and offset 0"


def test_distributor_get_with_unknown_id_returns_not_found():
    """PRD §2.10: "the server validates path identifiers strictly left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve, before any body-level, state-level or business-level check is attempted."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error." and "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/distributor_get_with_unknown_id_returns_not_found
    """
    resp = api_client.get_distributor(NON_EXISTENT_UUID, CM)
    err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert err.get("message"), "the error envelope carries a message"
    assert resp.json()["response_type"] == "error"


def test_distributor_contact_reads_own_distributor_record():
    """PRD §2.1: "Every role may call every read (GET) endpoint; the write operations below are exclusive to the named role unless stated otherwise."
    PRD §2.1: "When `X-User-Role` is `DistributorContact`, `X-User-ID` is the `id` of the acting `Distributor`; ownership checks on any resource that references a `Distributor` compare the resource's foreign-key field to `X-User-ID`."
    PRD §3.5: "The distributor starts as an `APPLICANT` with `suspension_count` 0".

    Design: Corner/rbac/distributor_contact_reads_own_distributor_record
    """
    fx.create_brand()
    market = fx.create_market()
    dist = fx.create_distributor_record(market["id"])

    got = validate_success(api_client.get_distributor(
        dist["id"], make_distributor_contact_headers(dist["id"])))
    assert_distributor(got)
    assert got["legal_name"] == "Ace Distribution"
    assert got["status"] == "APPLICANT"
    assert got["suspension_count"] == 0


def test_distributor_suspend_reinstate_cycle():
    """PRD §3.5: "Suspending an `APPROVED` distributor — whether by a `ChannelManager`'s manual action or automatically when an attainment recomputation flips its tier to `SANCTION` — increments `suspension_count` by one and cascades every `ACTIVE` coverage assignment of the distributor to `SUSPENDED`."
    PRD §3.5: "Reinstatement returns a `SUSPENDED` distributor to `APPROVED`, but — importantly — it does **not** resume coverage: each `SUSPENDED` assignment must be resumed individually."
    PRD §3.5: "Resuming a `SUSPENDED` assignment re-applies exactly the activation gates — distributor approved, window live, registration active where required, exclusivity and cell capacity — with the same error codes."

    Design: Difficulty/non_linear_state_machine/distributor_suspend_reinstate_cycle
    """
    sc = fx.setup_active_coverage()
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]

    suspended = validate_success(api_client.suspend_distributor(dist_id, CM))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_count"] == 1
    asg_mid = validate_success(api_client.get_coverage_assignment(asg_id, CM))
    assert asg_mid["status"] == "SUSPENDED", "the suspension cascaded"

    reinstated = validate_success(api_client.reinstate_distributor(dist_id, CM))
    assert reinstated["status"] == "APPROVED"
    asg_still = validate_success(api_client.get_coverage_assignment(asg_id, CM))
    assert asg_still["status"] == "SUSPENDED", \
        "reinstatement does not cascade back to coverage"

    resumed = validate_success(api_client.resume_coverage_assignment(asg_id, CM))
    assert resumed["status"] == "ACTIVE"


def test_third_suspension_terminates_distributor_and_assignments():
    """PRD §3.5: "But a suspension that would bring the count to 3 never lands: the distributor goes straight to `TERMINATED` with `suspension_count` set to 3."
    PRD §3.5: "On termination the distributor's `PROPOSED` assignments are `WITHDRAWN` and its `ACTIVE` or `SUSPENDED` assignments are `TERMINATED`."
    PRD §3.5: "`TERMINATED` is terminal."

    Design: Corner/state_machines/third_suspension_terminates_distributor_and_assignments
    """
    sc = fx.setup_active_coverage()
    dist_id = sc["distributor"]["id"]
    asg_id = sc["assignment"]["id"]

    api_client.suspend_distributor(dist_id, CM)
    api_client.reinstate_distributor(dist_id, CM)
    api_client.suspend_distributor(dist_id, CM)
    api_client.reinstate_distributor(dist_id, CM)
    third = validate_success(api_client.suspend_distributor(dist_id, CM))
    assert third["status"] == "TERMINATED", \
        "the third strike never rests in SUSPENDED"
    assert third["suspension_count"] == 3

    asg = validate_success(api_client.get_coverage_assignment(asg_id, CM))
    assert asg["status"] == "TERMINATED", \
        "the assignment was SUSPENDED from the second strike and terminates with the distributor"

    revive = api_client.reinstate_distributor(dist_id, CM)
    validate_error(revive, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_assignment_proposal_requires_approved_distributor():
    """PRD §3.5: "Creation requires: the distributor `APPROVED` (`ERR_DISTRIBUTOR_NOT_APPROVED`, HTTP 409); the market `OPEN` (`ERR_MARKET_NOT_OPEN`); the line `PILOT` or `LAUNCHED` (`ERR_LINE_STAGE_TOO_EARLY`); the channel present in the distributor's `channels_served` (`ERR_CHANNEL_NOT_SERVED`, HTTP 422), in the market's `allowed_channels` (`ERR_CHANNEL_NOT_ALLOWED`, HTTP 422), and in the line's `target_channels` (`ERR_CHANNEL_OUTSIDE_LINE_SCOPE`, HTTP 422); and a sane window — `starts_on` strictly before `ends_on`, and `ends_on` not already past (`ERR_WINDOW_INVALID`, HTTP 422)."
    PRD §2.7: "a successful create increments the distributor's `version` by one" — a rejected create mutates nothing.

    Design: Corner/validations/assignment_proposal_requires_approved_distributor
    """
    brand = fx.create_brand()
    line = fx.create_product_line(brand["id"])
    market = fx.create_market()
    dist = fx.create_distributor_record(market["id"])  # stays APPLICANT

    resp = api_client.create_coverage_assignment(
        dist["id"],
        {"market_id": market["id"], "product_line_id": line["id"],
         "channel": "HARDWARE", "starts_on": "2026-08-01",
         "ends_on": "2027-07-31", "annual_quota_units": 100,
         "expected_distributor_version": dist["version"]}, CM)
    validate_error(resp, ApiErrorId.ERR_DISTRIBUTOR_NOT_APPROVED)

    after = validate_success(api_client.get_distributor(dist["id"], CM))
    assert after["version"] == dist["version"], \
        "the rejected proposal did not bump the distributor version"
