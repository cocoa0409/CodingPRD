"""What an endpoint hands back, and what a listing narrows to.

The logical clock decides the instant stamped on every later write. An action
endpoint answers with the whole entity whose state changed, refreshed to include
everything the action recomputed, and a following read agrees with it exactly.
Every listing echoes its effective page window, reports the pre-pagination total,
and combines its optional filters conjunctively — which is what makes a child
collection reachable from its parent without a nested route.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    DEFAULT_CLOCK_INSTANT,
    DISPOSITION_ESCROWED,
    DISPOSITION_EXCLUDED,
    DISPOSITION_UNASSIGNED,
    DOMAIN_BY_TASK_CODE,
    LIABILITY_EQUIPMENT_LEASE,
    LIABILITY_PAYER_REFUND_EXPOSURE,
    LIABILITY_STARK_SELF_DISCLOSURE,
    MEDICARE_RETRO_WINDOW_DAYS,
    PACKAGE_STATUS_DRAFT,
    PAYER_TYPE_COMMERCIAL,
    PAYER_TYPE_MEDICARE,
    STRUCTURE_ASSET,
    TASK_COMPLIANCE_TRAINING,
    TASK_IT_DATA_MIGRATION,
    TASK_PATIENT_NOTIFICATION,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_OPEN,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    DEAL_LEAD,
    INTEGRATION_MANAGER,
    create_acquisition,
    create_liability,
    create_package,
    create_payer_contract,
    create_physician,
    create_task,
    park_clock_on_date,
    read_acquisition,
    read_task,
    reset_clock,
    second_physician,
    set_disposition,
    set_task_status,
)
from test_helpers.test_users import make_practice_physician_headers

MOVED_DATE = "2026-09-05"
MOVED_TIME = "14:30:00"
MOVED_INSTANT = "2026-09-05T14:30:00Z"

TRAINING_DUE_ON = "2026-10-25"
MIGRATION_DUE_ON = "2026-10-20"
NOTIFICATION_DUE_ON = "2026-10-28"
SECOND_DEAL_TRAINING_DUE_ON = "2026-11-25"
SECOND_PRACTICE_NAME = "Brookvale Internal Medicine"

ACTION_DATE = "2026-08-02"
ACTION_TIME = "09:00:00"
ACTION_INSTANT = "2026-08-02T09:00:00Z"


# ---------------------------------------------------------------------------
# The clock endpoint and the instants it decides
# ---------------------------------------------------------------------------


def test_a_write_that_follows_the_clock_is_stamped_at_the_new_instant(api: ApiClient):
    """Rows opened before and after the move carry their own logical instants.

    PRD: "An administrative test-driving capability sets the clock to an
    arbitrary instant supplied as `to_iso8601` and returns the new value as
    `current_utc`. It is available to `IntegrationManager`, `DealLead`, and
    `ComplianceOfficer`. Once set, all subsequent reads of "the current logical
    date" and "the current logical instant" use that value. Where a rule speaks
    of a *date* comparison, the logical clock's calendar date in UTC is used;
    where it speaks of an *instant*, the full ISO 8601 UTC value with three
    fractional digits is used."

    Design: Corner/endpoints/clock_endpoint_sets_the_instant_stamped_on_later_writes
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    a.assert_common_fields(acquisition, 1)
    a.assert_instant_equals(acquisition["created_at"], DEFAULT_CLOCK_INSTANT, "created_at")

    park_clock_on_date(api, MOVED_DATE, MOVED_TIME)
    task = create_task(
        api,
        acquisition["id"],
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )

    a.assert_common_fields(task, 1)
    a.assert_instant_equals(task["created_at"], MOVED_INSTANT, "created_at")
    a.assert_instant_equals(task["updated_at"], MOVED_INSTANT, "updated_at")
    assert task["due_on"] == TRAINING_DUE_ON

    reread = read_acquisition(api, acquisition["id"])
    a.assert_instant_equals(reread["created_at"], DEFAULT_CLOCK_INSTANT, "created_at")
    assert reread["created_at"] == acquisition["created_at"]


def test_only_the_three_administrative_roles_may_move_the_clock(api: ApiClient):
    """A provider's refusal leaves the clock exactly where it was.

    PRD: "An administrative test-driving capability sets the clock to an
    arbitrary instant supplied as `to_iso8601` and returns the new value as
    `current_utc`. It is available to `IntegrationManager`, `DealLead`, and
    `ComplianceOfficer`. Once set, all subsequent reads of "the current logical
    date" and "the current logical instant" use that value. Where a rule speaks
    of a *date* comparison, the logical clock's calendar date in UTC is used;
    where it speaks of an *instant*, the full ISO 8601 UTC value with three
    fractional digits is used."

    Design: Corner/endpoints/clock_endpoint_sets_the_instant_stamped_on_later_writes
    """
    reset_clock(api)
    acquisition = create_acquisition(api)
    physician = create_physician(api, acquisition["id"])
    provider = make_practice_physician_headers(physician["id"])

    refused = api.set_clock(f.make_clock_instant(MOVED_DATE, MOVED_TIME), provider)
    validate_error(refused, ApiErrorId.FORBIDDEN_ROLE, 403)

    unmoved = create_task(
        api,
        acquisition["id"],
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )
    a.assert_instant_equals(unmoved["created_at"], DEFAULT_CLOCK_INSTANT, "created_at")

    for administrator in (INTEGRATION_MANAGER, DEAL_LEAD, COMPLIANCE_OFFICER):
        accepted = api.set_clock(f.make_clock_instant(MOVED_DATE, MOVED_TIME), administrator)
        validate_success(accepted, 200)

    later = create_task(
        api,
        acquisition["id"],
        task_code=TASK_IT_DATA_MIGRATION,
        is_blocking=True,
        due_on=MIGRATION_DUE_ON,
    )
    a.assert_instant_equals(later["created_at"], MOVED_INSTANT, "created_at")


# ---------------------------------------------------------------------------
# The action envelope: the whole refreshed entity, and a read that agrees
# ---------------------------------------------------------------------------


def _acquisition_with_a_migration_line(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    task = create_task(
        api,
        acquisition["id"],
        task_code=TASK_IT_DATA_MIGRATION,
        is_blocking=True,
        due_on=MIGRATION_DUE_ON,
    )
    return acquisition, task


def _start_the_line(api: ApiClient, task_id: str):
    return api.set_readiness_task_status(
        task_id, f.task_status_payload(TASK_STATUS_IN_PROGRESS), INTEGRATION_MANAGER
    )


def test_the_action_response_carries_the_whole_refreshed_line(api: ApiClient):
    """The transition answers with every field it recomputed, not a bare status.

    PRD: "Every endpoint listed below sits at the root of the URL space: there is
    no version prefix and no path segment before the collection name. Successful
    creation of a resource returns HTTP 201 with the created resource in `data`.
    Successful reads and successful state-changing actions return HTTP 200 with
    the affected resource — for an action endpoint, the resource whose state
    changed, refreshed to include every field the action recomputed. List
    endpoints return HTTP 200, `response_type` `array`, and the four pagination
    fields in `meta`. Setting the logical clock returns HTTP 200 with an empty
    `data` object."

    Design: Corner/endpoints/action_endpoint_returns_the_whole_updated_entity
    """
    acquisition, task = _acquisition_with_a_migration_line(api)
    a.assert_status(task, TASK_STATUS_OPEN)
    a.assert_common_fields(task, 1)

    park_clock_on_date(api, ACTION_DATE, ACTION_TIME)
    started = validate_success(_start_the_line(api, task["id"]), 200)

    a.assert_common_fields(started)
    a.assert_status(started, TASK_STATUS_IN_PROGRESS)
    assert started["id"] == task["id"]
    assert started["acquisition_id"] == acquisition["id"]
    assert started["task_code"] == TASK_IT_DATA_MIGRATION
    assert started["domain"] == DOMAIN_BY_TASK_CODE[TASK_IT_DATA_MIGRATION]
    assert started["is_blocking"] is True
    assert started["due_on"] == MIGRATION_DUE_ON
    a.assert_version_bumped_by(task, started)
    a.assert_instant_equals(started["updated_at"], ACTION_INSTANT, "updated_at")
    a.assert_instant_equals(started["created_at"], DEFAULT_CLOCK_INSTANT, "created_at")


def test_a_following_read_returns_exactly_what_the_action_returned(api: ApiClient):
    """The read is the same representation, so the action left nothing to fetch.

    PRD: "`updated_at` is refreshed to the current logical instant on every
    mutation, and `version` is bumped, whether the mutation was requested
    directly or arrived as a cascade from another entity's transition."

    Design: Corner/endpoints/action_endpoint_returns_the_whole_updated_entity
    """
    _acquisition, task = _acquisition_with_a_migration_line(api)
    park_clock_on_date(api, ACTION_DATE, ACTION_TIME)
    started = validate_success(_start_the_line(api, task["id"]), 200)

    fetched = read_task(api, task["id"])

    assert fetched == started
    a.assert_status(fetched, TASK_STATUS_IN_PROGRESS)
    assert fetched["version"] == task["version"] + 1
    a.assert_instant_equals(fetched["updated_at"], ACTION_INSTANT, "updated_at")


# ---------------------------------------------------------------------------
# Conjunctive filters over a child collection
# ---------------------------------------------------------------------------


def _checklists_on_two_deals(api: ApiClient):
    reset_clock(api)
    first = create_acquisition(api)
    second = create_acquisition(api, target_practice_name=SECOND_PRACTICE_NAME)
    training = create_task(
        api,
        first["id"],
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=TRAINING_DUE_ON,
    )
    migration = create_task(
        api,
        first["id"],
        task_code=TASK_IT_DATA_MIGRATION,
        is_blocking=True,
        due_on=MIGRATION_DUE_ON,
    )
    started = set_task_status(api, migration["id"], TASK_STATUS_IN_PROGRESS)
    notification = create_task(
        api,
        first["id"],
        task_code=TASK_PATIENT_NOTIFICATION,
        is_blocking=False,
        due_on=NOTIFICATION_DUE_ON,
    )
    elsewhere = create_task(
        api,
        second["id"],
        task_code=TASK_COMPLIANCE_TRAINING,
        is_blocking=True,
        due_on=SECOND_DEAL_TRAINING_DUE_ON,
    )
    return {
        "first": first,
        "second": second,
        "training": training,
        "migration": started,
        "notification": notification,
        "elsewhere": elsewhere,
    }


def test_a_parent_filter_and_a_status_filter_narrow_together(api: ApiClient):
    """Two filters on one request intersect rather than widening the page.

    PRD: "Every list endpoint accepts `limit` and `offset` as described in §2.3,
    and every one of them also accepts a set of exact-match filters, all
    optional, which may be combined freely and are conjunctive when combined."

    Design: Corner/endpoints/filtered_listing_narrows_by_acquisition_and_status_together
    """
    world = _checklists_on_two_deals(api)

    narrowed = api.list_readiness_tasks(
        {"acquisition_id": world["first"]["id"], "status": TASK_STATUS_OPEN},
        INTEGRATION_MANAGER,
    )

    rows = a.assert_total_count(narrowed, 2)
    a.assert_has_more(narrowed, False)
    a.assert_contains_id(rows, world["training"]["id"])
    a.assert_contains_id(rows, world["notification"]["id"])
    a.assert_excludes_id(rows, world["migration"]["id"])
    a.assert_excludes_id(rows, world["elsewhere"]["id"])
    a.assert_ordered_by_created_at(rows)


def test_each_filter_alone_widens_the_page_the_pair_narrowed(api: ApiClient):
    """The parent identifier, the blocking flag and no filter at all each answer differently.

    PRD: "Readiness tasks may be filtered by `acquisition_id`, `status`,
    `task_code`, `domain`, and `is_blocking`."

    Design: Corner/endpoints/filtered_listing_narrows_by_acquisition_and_status_together
    """
    world = _checklists_on_two_deals(api)
    first_id = world["first"]["id"]

    by_parent = api.list_readiness_tasks({"acquisition_id": first_id}, INTEGRATION_MANAGER)
    parent_rows = a.assert_total_count(by_parent, 3)
    a.assert_excludes_id(parent_rows, world["elsewhere"]["id"])

    blocking = api.list_readiness_tasks(
        {"acquisition_id": first_id, "is_blocking": True}, INTEGRATION_MANAGER
    )
    blocking_rows = a.assert_total_count(blocking, 2)
    a.assert_contains_id(blocking_rows, world["training"]["id"])
    a.assert_contains_id(blocking_rows, world["migration"]["id"])
    a.assert_excludes_id(blocking_rows, world["notification"]["id"])

    unfiltered = api.list_readiness_tasks({}, INTEGRATION_MANAGER)
    every_row = a.assert_total_count(unfiltered, 4)
    a.assert_contains_id(every_row, world["elsewhere"]["id"])
    a.assert_has_more(unfiltered, False)


# ---------------------------------------------------------------------------
# The accepted page window
# ---------------------------------------------------------------------------


def _two_deals(api: ApiClient):
    reset_clock(api)
    first = create_acquisition(api)
    second = create_acquisition(api, target_practice_name=SECOND_PRACTICE_NAME)
    return first, second


def test_a_page_size_outside_the_accepted_band_is_refused_not_clamped(api: ApiClient):
    """One above the maximum and one below the minimum are both schema violations.

    PRD: "Every collection-listing endpoint is paginated by two optional query
    parameters. `limit` defaults to 10 when omitted, has a minimum accepted value
    of 1 and a maximum accepted value of 100. `offset` defaults to 0 when omitted
    and has a minimum accepted value of 0, with no upper bound. A `limit` below 1
    or above 100, or a negative `offset`, is a schema violation and is rejected
    with `ERR_INVALID_REQUEST` and HTTP 400 rather than being silently clamped."

    Design: Corner/endpoints/pagination_limit_above_one_hundred_returns_invalid_request
    """
    first, second = _two_deals(api)

    over = api.list_acquisitions({"limit": 101}, DEAL_LEAD)
    validate_error(over, ApiErrorId.INVALID_REQUEST, 400)

    under = api.list_acquisitions({"limit": 0}, DEAL_LEAD)
    validate_error(under, ApiErrorId.INVALID_REQUEST, 400)

    at_the_maximum = api.list_acquisitions({"limit": 100}, DEAL_LEAD)
    rows, meta = a.list_rows_and_meta(at_the_maximum)
    assert meta["total_count"] == 2
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    a.assert_contains_id(rows, first["id"])
    a.assert_contains_id(rows, second["id"])


def test_an_offset_past_the_last_row_returns_an_empty_page_and_the_full_total(api: ApiClient):
    """`total_count` counts the matching rows, not the rows this page happens to carry.

    PRD: "Every list response populates all four pagination fields in `meta`:
    `limit` and `offset` echo the effective values actually applied,
    `total_count` reports the number of rows matching the filter before
    pagination is applied, and `has_more` is true exactly when the sum of
    `offset` and the number of rows returned in this page is less than
    `total_count`."

    Design: Corner/endpoints/pagination_limit_above_one_hundred_returns_invalid_request
    """
    first, second = _two_deals(api)

    beyond = api.list_acquisitions({"offset": 5}, DEAL_LEAD)

    rows, meta = a.list_rows_and_meta(beyond)
    assert rows == []
    assert meta["total_count"] == 2
    assert meta["offset"] == 5
    assert meta["limit"] == 10
    assert meta["has_more"] is False
    a.assert_excludes_id(rows, first["id"])
    a.assert_excludes_id(rows, second["id"])


# ---------------------------------------------------------------------------
# The credentialing junction between a provider and a payer
# ---------------------------------------------------------------------------

MEDICARE_PAYER_NAME = "Medicare Part B"
MEDICARE_REVENUE_SHARE_BPS = 3800
PACKAGE_SUBMITTED_ON = "2026-09-02"
PACKAGE_CYCLE_KEY = "2026-09-15"
MEDICARE_LEAD_DAYS = 60
PACKAGE_PROJECTED_EFFECTIVE_ON = "2026-11-01"


def _one_deal_two_providers_two_payers(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(api)
    provider = create_physician(api, acquisition["id"])
    colleague = second_physician(api, acquisition["id"])
    commercial = create_payer_contract(api, acquisition["id"])
    medicare = create_payer_contract(
        api,
        acquisition["id"],
        payer_name=MEDICARE_PAYER_NAME,
        payer_type=PAYER_TYPE_MEDICARE,
        notice_days_required=0,
        annual_revenue_share_bps=MEDICARE_REVENUE_SHARE_BPS,
    )
    assert commercial["payer_type"] == PAYER_TYPE_COMMERCIAL
    assert medicare["payer_type"] == PAYER_TYPE_MEDICARE
    return {
        "acquisition": acquisition,
        "provider": provider,
        "colleague": colleague,
        "commercial": commercial,
        "medicare": medicare,
    }


def test_the_junction_derives_its_lead_time_from_the_payer_it_names(api: ApiClient):
    """Filing dates are the client's; the cycle, the lead days and the effective date are not.

    PRD: "`lead_days` is the payer's processing lead time, looked up from the
    linked contract's `payer_type`: 90 days for `COMMERCIAL`, 75 for
    `MANAGED_MEDICARE`, 60 for `MEDICARE`, and 120 for `MEDICAID`."

    Design: Corner/endpoints/credentialing_package_links_a_physician_to_a_payer_contract
    """
    world = _one_deal_two_providers_two_payers(api)

    created = api.create_credentialing_package(
        f.credentialing_package_payload(
            world["acquisition"]["id"],
            world["provider"]["id"],
            world["medicare"]["id"],
            submitted_on=PACKAGE_SUBMITTED_ON,
        ),
        INTEGRATION_MANAGER,
    )

    package = validate_success(created, 201)
    a.assert_common_fields(package, 1)
    a.assert_status(package, PACKAGE_STATUS_DRAFT)
    assert package["acquisition_id"] == world["acquisition"]["id"]
    assert package["physician_id"] == world["provider"]["id"]
    assert package["payer_contract_id"] == world["medicare"]["id"]
    assert package["submitted_on"] == PACKAGE_SUBMITTED_ON
    assert package["lead_days"] == MEDICARE_LEAD_DAYS
    assert package["committee_cycle_key"] == PACKAGE_CYCLE_KEY
    assert package["projected_effective_on"] == PACKAGE_PROJECTED_EFFECTIVE_ON
    assert MEDICARE_RETRO_WINDOW_DAYS > 0
    assert package["retro_billing_allowed"] is True


def test_the_junction_row_is_reachable_from_either_parent(api: ApiClient):
    """Each parent identifier finds it, and the wrong parent finds nothing.

    PRD: "Credentialing packages may be filtered by `acquisition_id`,
    `physician_id`, `payer_contract_id`, `status`, `committee_cycle_key`, and
    `retro_billing_allowed`."

    Design: Corner/endpoints/credentialing_package_links_a_physician_to_a_payer_contract
    """
    world = _one_deal_two_providers_two_payers(api)
    package = create_package(
        api,
        world["acquisition"]["id"],
        world["provider"]["id"],
        world["medicare"]["id"],
        submitted_on=PACKAGE_SUBMITTED_ON,
    )

    by_provider = api.list_credentialing_packages(
        {"physician_id": world["provider"]["id"]}, INTEGRATION_MANAGER
    )
    provider_rows = a.assert_total_count(by_provider, 1)
    a.assert_contains_id(provider_rows, package["id"])

    by_colleague = api.list_credentialing_packages(
        {"physician_id": world["colleague"]["id"]}, INTEGRATION_MANAGER
    )
    assert a.assert_total_count(by_colleague, 0) == []

    by_other_payer = api.list_credentialing_packages(
        {"payer_contract_id": world["commercial"]["id"]}, INTEGRATION_MANAGER
    )
    assert a.assert_total_count(by_other_payer, 0) == []

    by_payer = api.list_credentialing_packages(
        {"payer_contract_id": world["medicare"]["id"], "retro_billing_allowed": True},
        INTEGRATION_MANAGER,
    )
    payer_rows = a.assert_total_count(by_payer, 1)
    a.assert_contains_id(payer_rows, package["id"])


# ---------------------------------------------------------------------------
# The parent ledger read against its child rows
# ---------------------------------------------------------------------------

ESCROW_TOTAL_CENTS = 10_000_000
LEASE_CENTS = 2_500_000
REFUND_CENTS = 1_750_000
STARK_CENTS = 900_000
COMMITTED_WITH_TWO_ESCROWED_CENTS = 4_250_000
AVAILABLE_WITH_TWO_ESCROWED_CENTS = 5_750_000
AVAILABLE_AFTER_THE_RELEASE_CENTS = 7_500_000


def _three_exposures_on_an_asset_deal(api: ApiClient):
    reset_clock(api)
    acquisition = create_acquisition(
        api, structure=STRUCTURE_ASSET, escrow_total_cents=ESCROW_TOTAL_CENTS
    )
    lease = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_EQUIPMENT_LEASE,
        description="Imaging equipment lease assumed at close",
        estimated_amount_cents=LEASE_CENTS,
    )
    refund = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_PAYER_REFUND_EXPOSURE,
        description="Open payer refund exposure from the prior audit cycle",
        estimated_amount_cents=REFUND_CENTS,
    )
    stark = create_liability(
        api,
        acquisition["id"],
        category=LIABILITY_STARK_SELF_DISCLOSURE,
        description="Self-disclosed referral arrangement under review",
        estimated_amount_cents=STARK_CENTS,
    )
    for item in (lease, refund, stark):
        assert item["disposition"] == DISPOSITION_UNASSIGNED
        a.assert_money_equals(item["escrowed_amount_cents"], 0, "escrowed_amount_cents")
    a.assert_escrow(acquisition, ESCROW_TOTAL_CENTS, 0, ESCROW_TOTAL_CENTS)
    return {"acquisition": acquisition, "lease": lease, "refund": refund, "stark": stark}


def test_the_parent_escrow_reading_is_the_sum_of_its_escrowed_children(api: ApiClient):
    """Two of three exposures are committed, and the parent totals exactly those two.

    PRD: "`escrow_committed_cents` is at all times the sum of
    `escrowed_amount_cents` over the acquisition's liability items whose
    `disposition` is `ESCROWED`; `escrow_available_cents` is `escrow_total_cents`
    minus `escrow_committed_cents`."

    Design: Corner/endpoints/acquisition_ledger_read_matches_its_child_liability_rows
    """
    world = _three_exposures_on_an_asset_deal(api)
    acquisition_id = world["acquisition"]["id"]

    escrowed_lease = set_disposition(api, world["lease"]["id"], DISPOSITION_ESCROWED)
    escrowed_refund = set_disposition(api, world["refund"]["id"], DISPOSITION_ESCROWED)

    a.assert_money_equals(
        escrowed_lease["escrowed_amount_cents"], LEASE_CENTS, "escrowed_amount_cents"
    )
    a.assert_money_equals(
        escrowed_refund["escrowed_amount_cents"], REFUND_CENTS, "escrowed_amount_cents"
    )
    still_unassigned = api.get_liability_item(world["stark"]["id"], DEAL_LEAD)
    stark = validate_success(still_unassigned)
    assert stark["disposition"] == DISPOSITION_UNASSIGNED
    a.assert_money_equals(stark["escrowed_amount_cents"], 0, "escrowed_amount_cents")

    ledger = read_acquisition(api, acquisition_id)
    a.assert_escrow(
        ledger,
        ESCROW_TOTAL_CENTS,
        COMMITTED_WITH_TWO_ESCROWED_CENTS,
        AVAILABLE_WITH_TWO_ESCROWED_CENTS,
    )
    assert LEASE_CENTS + REFUND_CENTS == COMMITTED_WITH_TWO_ESCROWED_CENTS

    committed_rows = api.list_liability_items(
        {"acquisition_id": acquisition_id, "disposition": DISPOSITION_ESCROWED}, DEAL_LEAD
    )
    rows = a.assert_total_count(committed_rows, 2)
    a.assert_contains_id(rows, world["lease"]["id"])
    a.assert_contains_id(rows, world["refund"]["id"])
    a.assert_excludes_id(rows, world["stark"]["id"])
    assert (
        sum(row["escrowed_amount_cents"] for row in rows) == ledger["escrow_committed_cents"]
    )


def test_releasing_an_escrowed_child_returns_its_amount_to_the_parent(api: ApiClient):
    """The release is in full, so the parent lands back on a clean figure.

    PRD: "Finally, `ESCROWED → EXCLUDED` releases an escrowed item: it checks the
    structure-and-category legality for `EXCLUDED`, subtracts the item's
    `escrowed_amount_cents` from `escrow_committed_cents`, adds the same amount
    back to `escrow_available_cents`, and resets the item's own
    `escrowed_amount_cents` to 0."

    Design: Corner/endpoints/acquisition_ledger_read_matches_its_child_liability_rows
    """
    world = _three_exposures_on_an_asset_deal(api)
    acquisition_id = world["acquisition"]["id"]
    set_disposition(api, world["lease"]["id"], DISPOSITION_ESCROWED)
    set_disposition(api, world["refund"]["id"], DISPOSITION_ESCROWED)

    released = set_disposition(api, world["refund"]["id"], DISPOSITION_EXCLUDED)

    assert released["disposition"] == DISPOSITION_EXCLUDED
    a.assert_money_equals(released["escrowed_amount_cents"], 0, "escrowed_amount_cents")

    ledger = read_acquisition(api, acquisition_id)
    a.assert_escrow(
        ledger, ESCROW_TOTAL_CENTS, LEASE_CENTS, AVAILABLE_AFTER_THE_RELEASE_CENTS
    )
    assert AVAILABLE_WITH_TWO_ESCROWED_CENTS + REFUND_CENTS == AVAILABLE_AFTER_THE_RELEASE_CENTS

    committed_rows = api.list_liability_items(
        {"acquisition_id": acquisition_id, "disposition": DISPOSITION_ESCROWED}, DEAL_LEAD
    )
    rows = a.assert_total_count(committed_rows, 1)
    a.assert_contains_id(rows, world["lease"]["id"])
    a.assert_excludes_id(rows, world["refund"]["id"])

    excluded_rows = api.list_liability_items(
        {"acquisition_id": acquisition_id, "disposition": DISPOSITION_EXCLUDED}, DEAL_LEAD
    )
    excluded = a.assert_total_count(excluded_rows, 1)
    a.assert_contains_id(excluded, world["refund"]["id"])
