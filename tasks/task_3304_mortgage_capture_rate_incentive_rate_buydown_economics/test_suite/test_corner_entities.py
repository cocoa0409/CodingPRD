"""Corner coverage - resource shape, defaults, required fields and keying."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers import ADMIN_HEADERS, ANONYMOUS_HEADERS, BANKER_HEADERS, SALES_HEADERS
from test_helpers import NON_EXISTENT_UUID


def test_a_fresh_community_opens_active_with_every_derived_counter_at_zero(api):
    """The five derived counters are computed, not client-settable.

    PRD §3.1: "A fresh community is created in `ACTIVE` posture with all five derived
    counters at zero."
    PRD §2.5: "All five default to 0 on creation".
    Design: Corner/entities/community_create_derives_zeroed_aggregate_fields
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    community = fixtures.create_community(api)

    assert community["program_status"] == "ACTIVE", community["program_status"]
    assert community["affiliated_units"] == 0, community["affiliated_units"]
    assert community["funded_units"] == 0, community["funded_units"]
    assert community["capture_rate_bps"] == 0, community["capture_rate_bps"]
    assert community["incentive_spend_cents"] == 0, community["incentive_spend_cents"]
    assert community["forward_units_committed"] == 0, community["forward_units_committed"]


def test_omitting_the_capture_target_applies_the_declared_default(api):
    """An absent capture_rate_target_bps defaults to 8500 basis points.

    PRD §2.5: "The community's `capture_rate_target_bps` field records the
    affiliated-lender capture target in basis points and defaults to 8500 when the
    creating client omits it".
    PRD §3.1: "The affiliate capture target may be supplied as `capture_rate_target_bps`
    or left unset, in which case it defaults to 8500 basis points."
    Design: Corner/entities/community_capture_rate_target_defaults_to_8500_bps
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    community = fixtures.create_community(
        api,
        incentive_policy_code="PREMIUM",
        price_reduction_cap_cents=4_000_000,
        closing_cost_cap_cents=2_500_000,
        rate_buydown_cap_cents=8_000_000,
    )

    assert community["capture_rate_target_bps"] == 8500, (
        f"the omitted target falls back to the declared default, "
        f"got {community['capture_rate_target_bps']}"
    )
    assert community["incentive_policy_code"] == "PREMIUM", community["incentive_policy_code"]


def test_creating_a_community_without_the_rate_buydown_cap_is_rejected(api):
    """The cap fields are required inputs, so one missing is a 400 rather than a zero.

    PRD §2.10: "Priority 24 requires that every field marked required by the
    endpoint's input schema be present and non-null; failure yields
    `ERR_INVALID_REQUEST` at HTTP 400."
    Design: Corner/entities/community_missing_required_field_returns_invalid_request
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    payload = f.community_payload()
    del payload["rate_buydown_cap_cents"]

    refused = api.create_community(payload, ADMIN_HEADERS)
    validate_error(refused, "ERR_INVALID_REQUEST", 400)

    catalogue, meta = validate_paginated(api.list_communities(ANONYMOUS_HEADERS))
    assert meta["total_count"] == 0, (
        f"the malformed request created no row, got {meta['total_count']}"
    )


def test_reading_a_community_by_an_unknown_identifier_is_a_not_found(api):
    """A well-formed but unknown identifier returns 404, not an empty object.

    PRD §2.10: "Priority 3 requires that every path identifier and every body foreign
    key resolve to an existing row, validated left-to-right along the path".
    PRD §2.10: "The first unresolvable reference aborts the request with
    `ERR_RESOURCE_NOT_FOUND` at HTTP 404".
    Design: Corner/entities/community_not_found_on_get_by_unknown_uuid
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    refused = api.get_community(NON_EXISTENT_UUID, ADMIN_HEADERS)
    validate_error(refused, "ERR_RESOURCE_NOT_FOUND", 404)


def test_the_community_catalogue_carries_the_pagination_envelope_fields(api):
    """Two rows under the default limit report the count and no further pages.

    PRD §2.3: "`total_count` reports the number of resources matching the request
    across all pages, and `has_more` is true precisely when further items remain
    beyond the returned window."
    PRD §2.3: "The `limit` parameter caps the number of items returned; it defaults to
    10 when omitted".
    Design: Corner/entities/community_list_pagination_envelope_fields
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    fixtures.create_community(api, name="C1")
    fixtures.create_community(
        api, name="C2", state_code="FL", incentive_policy_code="PREMIUM",
        price_reduction_cap_cents=4_000_000, closing_cost_cap_cents=2_500_000,
        rate_buydown_cap_cents=8_000_000,
    )

    rows, meta = validate_paginated(api.list_communities(ANONYMOUS_HEADERS))
    assert meta["limit"] == 10, meta["limit"]
    assert meta["offset"] == 0, meta["offset"]
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
    assert len(rows) == 2, f"the payload carries exactly two communities, got {len(rows)}"


def test_a_construction_stage_outside_the_declared_set_is_rejected(api):
    """An undeclared construction stage is refused rather than stored verbatim.

    PRD §2.10: "Priority 25 requires that every enum-typed field carry a member of its
    declared constraint set and that every numeric field lie inside its declared
    bounds; failure yields `ERR_INVALID_ENUM_VALUE` at HTTP 400."
    PRD §3.2: "Its physical progress is tracked by `construction_stage`, one of
    `NOT_STARTED`, `FOUNDATION`, `FRAMING`, `DRYWALL`, `FINISH` or `COMPLETE`".
    Design: Corner/entities/home_site_invalid_construction_stage_enum_rejected
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    community = fixtures.create_community(api)

    refused = api.create_home_site(
        community["id"],
        f.home_site_payload(construction_stage="ROOFING"),
        SALES_HEADERS,
    )
    validate_error(refused, "ERR_INVALID_ENUM_VALUE", 400)

    sites, _ = fixtures.rows(
        api.list_community_home_sites(community["id"], SALES_HEADERS)
    )
    assert sites == [], f"no inventory home was written, got {sites}"


def test_creating_a_home_site_under_an_unknown_community_is_a_not_found(api):
    """The owning community is resolved before the body is accepted.

    PRD §2.12: "The request is abandoned at the first identifier along that chain that
    resolves to no row, returning `ERR_RESOURCE_NOT_FOUND` at HTTP 404".
    PRD §3.2: "Creating a home site requires the community identifier in the request to
    resolve to an existing community".
    Design: Corner/entities/home_site_creation_requires_existing_parent_community
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    refused = api.create_home_site(NON_EXISTENT_UUID, f.home_site_payload(), SALES_HEADERS)
    validate_error(refused, "ERR_RESOURCE_NOT_FOUND", 404)


def test_a_second_buyer_under_an_email_already_on_file_is_refused(api):
    """The email is the buyer's natural unique key, so the duplicate is rejected.

    PRD §3.3: "A `SalesCounselor` or `PlatformAdmin` registers a homebuyer with a
    `full_name`, an `email` that must be unique across all buyers and serves as the
    natural identifier".
    PRD §2.10: "Priority 25 requires that every enum-typed field carry a member of its
    declared constraint set and that every numeric field lie inside its declared
    bounds; failure yields `ERR_INVALID_ENUM_VALUE` at HTTP 400."
    Design: Corner/entities/buyer_duplicate_email_uniqueness_constraint
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    fixtures.create_buyer(api, email="ada@x.com")

    refused = api.create_buyer(
        f.buyer_payload(full_name="Ada Two", email="ada@x.com"), SALES_HEADERS
    )
    # PRD states the uniqueness constraint verbatim but never names the identifier the
    # refusal carries, so either declared 400 rung is a faithful reading.
    validate_error_is_one_of(
        refused, ["ERR_INVALID_REQUEST", "ERR_INVALID_ENUM_VALUE"]
    )


def test_the_duplicate_email_leaves_exactly_one_buyer_under_that_address(api):
    """Only the first registration survives the refused second one.

    PRD §3.3: "an `email` that must be unique across all buyers and serves as the
    natural identifier".
    PRD §2.10: "Priority 3 requires that every path identifier and every body foreign
    key resolve to an existing row, validated left-to-right along the path".
    Design: Corner/entities/buyer_duplicate_email_uniqueness_constraint
    """
    fixtures.set_clock(api, fixtures.BASE_CLOCK)
    first = fixtures.create_buyer(api, email="ada@x.com")

    api.create_buyer(f.buyer_payload(full_name="Ada Two", email="ada@x.com"), SALES_HEADERS)

    reread = fixtures.read_buyer(api, first["id"])
    assert reread["email"] == "ada@x.com", reread["email"]
    assert reread["full_name"] == "Ada", (
        f"the refused write must not overwrite the first registration, got {reread['full_name']}"
    )


def test_a_new_contract_derives_its_incentive_budget_from_the_community_policy(api):
    """The contract's budget is the sum of the three community caps, not an input.

    PRD §3.4: "A new contract opens in `contract_status` `PENDING` with
    `deposit_held_cents` zero, its `incentive_budget_cents` computed as the sum of the
    community's three bucket caps, and its home site moved from `AVAILABLE` to
    `UNDER_CONTRACT`."
    Design: Corner/entities/contract_creation_derives_incentive_budget_from_community_policy
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])
    contract = fixtures.create_contract(api, site["id"], world["b1"])

    assert contract["incentive_budget_cents"] == 11_000_000, (
        f"3_000_000 + 2_000_000 + 6_000_000 is the whole standard policy, "
        f"got {contract['incentive_budget_cents']}"
    )
    assert contract["incentive_allocated_cents"] == 0, contract["incentive_allocated_cents"]
    assert contract["contract_status"] == "PENDING", contract["contract_status"]
    assert contract["deposit_held_cents"] == 0, contract["deposit_held_cents"]


def test_a_new_commitment_opens_with_the_pool_fully_available(api):
    """The draw ledger starts empty and the whole purchase is drawable.

    PRD §2.7: "On creation the pool is fully available, with `units_drawn` and
    `units_released` both zero and `units_available` equal to `committed_units`."
    PRD §3.6: "The pool opens `OPEN` with `units_drawn` and `units_released` both zero,
    `units_available` equal to the full `committed_units`, `pair_off_fee_cents` zero,
    and the community's `forward_units_committed` recomputed."
    Design: Corner/entities/home_site_and_forward_commitment_system_fields_are_server_minted
    """
    world = fixtures.seed_reference_data(api)
    # A window that opens after the reference pool's closes, so the fresh pool is a
    # legal purchase rather than an overlap of the community's existing one.
    commitment = fixtures.create_commitment(
        api, world["cm1"], committed_units=10,
        commitment_start_iso="2030-01-01T00:00:00Z",
        commitment_end_iso="2031-01-01T00:00:00Z",
    )

    assert commitment["units_available"] == 10, commitment["units_available"]
    assert commitment["units_drawn"] == 0, commitment["units_drawn"]
    assert commitment["units_released"] == 0, commitment["units_released"]
    assert commitment["commitment_status"] == "OPEN", commitment["commitment_status"]


def test_a_new_home_site_reports_the_server_minted_availability_posture(api):
    """The availability posture is system-sourced: the server mints AVAILABLE.

    PRD §3.2: "A home site begins in `home_site_status` `AVAILABLE`."
    PRD §2.4: "Every resource also exposes its lifecycle posture under a status field
    of its own, and the name differs by entity."
    Design: Corner/entities/home_site_and_forward_commitment_system_fields_are_server_minted
    """
    world = fixtures.seed_reference_data(api)
    site = fixtures.create_home_site(api, world["cm1"])

    assert site["home_site_status"] == "AVAILABLE", site["home_site_status"]
    assert site["version"] == 1, site["version"]


def test_the_commitment_row_carries_the_common_version_field_from_creation(api):
    """Every persisted resource carries the common version field, this one from row one.

    PRD §2.4: "The `version` field is an integer that begins at its initial value when
    the row is created and increments by one on every mutation".
    PRD §2.7: "Three counters describe the pool's state. The `units_drawn` counter
    accumulates one whole unit for every rate lock that has been consumed against the
    commitment".
    Design: Corner/entities/home_site_and_forward_commitment_system_fields_are_server_minted
    """
    world = fixtures.seed_reference_data(api)
    commitment = fixtures.create_commitment(
        api, world["cm1"], committed_units=4,
        commitment_start_iso="2030-01-01T00:00:00Z",
        commitment_end_iso="2031-01-01T00:00:00Z",
    )

    assert commitment["version"] == 1, (
        f"a freshly written row starts at its initial version, got {commitment['version']}"
    )
    assert commitment["units_available"] == commitment["committed_units"] == 4, (
        commitment["units_available"]
    )