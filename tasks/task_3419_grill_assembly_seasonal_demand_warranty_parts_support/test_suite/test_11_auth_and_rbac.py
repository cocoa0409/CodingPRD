"""Auth ladder rungs 1-4 and existence discipline: missing headers, role
authorization (endpoint- and action-level), entity-backed ownership, and the
per-entity 404 codes.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_channel,
    create_season_payload,
    make_channel_rep_headers,
    refetch_allocation,
    respond_allocation_payload,
    setup_offered_allocation,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]


def test_request_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "A request missing either header, or carrying an `X-User-Role` value
    outside these five declared roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."
    PRD 2.9: "1. **Authentication.** The `X-User-ID` and `X-User-Role` headers must be
    present and the role must be one of the five declared roles, else
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    # No X-User-ID / X-User-Role headers at all; authentication precedes existence,
    # so the (also unknown) season id never gets to 404.
    resp = api.get_season("00000000-0000-4000-8000-000000000000", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_channel_rep_cannot_create_season_returns_unauthorized(api):
    """PRD 2.1: "An attempt to perform an operation outside the caller's designated
    role — or an action the role is not permitted for on that endpoint — is rejected
    with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD 4: `POST /grillops/seasons` is authorized for PlannerAdmin only.

    Design: Corner/validations/channel_rep_cannot_create_season_returns_unauthorized
    """
    payload = create_season_payload(
        name="Rogue Season", year=2027,
        build_start="2026-11-01T00:00:00Z", allocation_open="2027-01-15T00:00:00Z",
        in_season_start="2027-03-01T00:00:00Z", clearance_start="2027-07-01T00:00:00Z",
        season_end="2027-09-30T00:00:00Z", demand_forecast_units=500,
    )
    resp = api.create_season(payload, headers=TEST_USERS["channel_rep_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_channel_rep_cannot_accept_another_channels_allocation(api):
    """PRD 2.1: "When `X-User-Role` is `ChannelRep`, `X-User-ID` is the `id` of the
    acting `ChannelAccount`; ownership checks on any resource that references a
    channel compare the resource's channel foreign key to `X-User-ID`."
    PRD 2.1: "An entity-backed caller acting on a resource owned by a different
    account — a `ChannelRep` touching another channel's allocation or sale, an
    `Assembler` starting a job assigned to someone else — is rejected with
    `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403)."

    Design: Corner/validations/channel_rep_cannot_accept_another_channels_allocation
    """
    bundle = setup_offered_allocation(allocated_units=5, units_built=10, channel_over={"name": "CH-A"})
    allocation = bundle["allocation"]
    ch_b = create_channel(name="CH-B", channel_type="SPECIALTY_DEALER",
                          allocation_priority=20, credit_limit_cents=100000000)
    # CH-B's rep carries the correct current version; ownership still forbids.
    resp = api.respond_allocation(
        allocation["id"],
        respond_allocation_payload("ACCEPT", allocation["version"]),
        headers=make_channel_rep_headers(ch_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
    after = refetch_allocation(allocation["id"])
    assert after["status"] == "OFFERED", "the rejected acceptance must not move the offer"


def test_planner_cannot_accept_allocation_returns_unauthorized(api):
    """PRD 2.1: "The action-level permissions are: `PlannerAdmin` may revise an
    allocation offer but may never accept, decline, or release one; a `ChannelRep` may
    never revise an offer; an `Assembler` may only start and complete jobs; an
    `AppUser` may only call device endpoints."

    Design: Corner/validations/planner_cannot_accept_allocation_returns_unauthorized
    """
    bundle = setup_offered_allocation(allocated_units=5, units_built=10)
    allocation = bundle["allocation"]
    resp = api.respond_allocation(
        allocation["id"],
        respond_allocation_payload("ACCEPT", allocation["version"]),
        headers=PLANNER,  # on the endpoint's role list, but not for the ACCEPT action
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    after = refetch_allocation(allocation["id"])
    assert after["status"] == "OFFERED"


def test_unknown_ids_return_entity_specific_not_found(api):
    """PRD 2.8: "the system validates the existence of each identifier in strict
    left-to-right order and rejects the request immediately with the 404 code of the
    first identifier that does not resolve: `ERR_SEASON_NOT_FOUND` for a season,
    `ERR_MODEL_NOT_FOUND` for a model, `ERR_ALLOCATION_NOT_FOUND` for an allocation,
    ... `ERR_JOB_NOT_FOUND` for an assembly job"

    Design: Corner/entities/unknown_ids_return_entity_specific_not_found
    """
    season = api.get_season("00000000-0000-4000-8000-000000000000", headers=PLANNER)
    validate_error(season, ApiErrorId.ERR_SEASON_NOT_FOUND)
    model = api.get_model("00000000-0000-4000-8000-000000000001", headers=PLANNER)
    validate_error(model, ApiErrorId.ERR_MODEL_NOT_FOUND)
    allocation = api.get_allocation("00000000-0000-4000-8000-000000000002", headers=PLANNER)
    validate_error(allocation, ApiErrorId.ERR_ALLOCATION_NOT_FOUND)
    job = api.transition_assembly_job(
        "00000000-0000-4000-8000-000000000003", {"action": "CANCEL"}, headers=AGENT)
    validate_error(job, ApiErrorId.ERR_JOB_NOT_FOUND)
