"""Row shapes: what a create defaults, what a read echoes and what a list pages."""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_common_fields,
    assert_created_at_ascending,
    assert_id_order,
    assert_ledger_entry_shape,
    assert_null_fields,
    assert_page,
    assert_zero_fields,
)
from test_helpers.test_users import ACTUARY, MANAGER, UNDERWRITER
from test_helpers.types import Ledger

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"
UNKNOWN_PART_ID = "00000000-0000-0000-0000-0000000000aa"


def test_a_bare_policy_create_defaults_the_floor_and_computes_the_term(api):
    """Four fields in, and everything else is the service's own answer.

    PRD: The submission may also carry `minimum_premium_cents`, the policy's premium floor; when omitted it is 250,000 cents, that is $2,500, and it may not be negative.
    PRD: The new policy opens in `status` `DRAFT` with `referral_status` `NOT_REQUIRED`, `referral_required` false, `referred_by_user_id` and `referral_decided_by_user_id` both null, `cancellation_reason` and `cancel_effective_date` both null, `quoted_at`, `bound_at` and `in_force_at` all null, `occupancy_termination_count` at 0, and every money roll-up — `sum_of_part_premiums_cents`, `scheduled_basis_premium_cents`, `blanket_basis_premium_cents`, `written_premium_cents`, `premium_balance_cents`, `incurred_loss_cents` and `total_insured_value_cents` — at 0.
    Design: Corner/entities/corner_policy_creation_applies_defaults_and_computes_term_days
    """
    created = validate_success(api.create_policy(
        factories.policy(policyholder_name="Default Draft Co",
                         territory_code="T3_INLAND", minimum_premium_cents=None),
        UNDERWRITER), 201)

    assert created["status"] == "DRAFT"
    assert created["term_days"] == 365
    assert created["minimum_premium_cents"] == 250000
    assert created["referral_required"] is False
    assert created["referral_status"] == "NOT_REQUIRED"
    assert created["occupancy_termination_count"] == 0
    assert_null_fields(created, ["referred_by_user_id", "referral_decided_by_user_id",
                                "cancellation_reason", "cancel_effective_date",
                                "quoted_at", "bound_at", "in_force_at"])
    assert_zero_fields(created, ["sum_of_part_premiums_cents",
                                "scheduled_basis_premium_cents",
                                "blanket_basis_premium_cents",
                                "written_premium_cents", "premium_balance_cents",
                                "incurred_loss_cents", "total_insured_value_cents"])
    assert_common_fields(created)
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])


def test_reading_a_policy_back_echoes_the_term_it_was_opened_on(api):
    """A six-month coastal term reads back with its own 184-day denominator.

    PRD: On creation the service computes `term_days` as the number of whole days from `effective_date` to `expiration_date`.
    PRD: Four rating territories exist and every territory-valued field in the domain draws from the same four: `T1_COASTAL`, `T2_URBAN`, `T3_INLAND` and `T4_REMOTE`.
    Design: Corner/entities/corner_policy_retrieval_returns_stored_state
    """
    created = fixtures.create_policy(api, policyholder_name="Coastal Readback Co",
                                     territory_code="T1_COASTAL",
                                     effective_date="2026-08-01",
                                     expiration_date="2027-02-01",
                                     minimum_premium_cents=100000)

    read = validate_success(api.get_policy(created["id"], MANAGER))

    assert read["policyholder_name"] == "Coastal Readback Co"
    assert read["territory_code"] == "T1_COASTAL"
    assert read["effective_date"] == "2026-08-01"
    assert read["expiration_date"] == "2027-02-01"
    assert read["term_days"] == 184
    assert read["minimum_premium_cents"] == 100000
    assert read["id"] == created["id"]


def test_the_equipment_listing_pages_a_filtered_schedule_in_creation_order(api):
    """Two rows then one, disjoint, oldest first, with the count taken before paging.

    PRD: The `meta` object of every list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` counts the rows matching the request's filters before pagination is applied and `has_more` states whether any matching row remains beyond the returned page.
    PRD: Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.
    Design: Corner/entities/corner_equipment_item_listing_paginates_with_filter
    """
    ctx = fixtures.build_scheduled_file(api, policy_kwargs=dict(
        policyholder_name="Fleet Pager Co"), with_item=False)
    ids = [fixtures.schedule_item(api, ctx.part_id, ctx.policy_id,
                                  description=f"Item {index}")["id"]
           for index in (1, 2, 3)]

    first_rows, first_meta = validate_paginated(api.list_equipment_items(
        UNDERWRITER, limit=2, offset=0, coverage_part_id=ctx.part_id))
    second_rows, second_meta = validate_paginated(api.list_equipment_items(
        UNDERWRITER, limit=2, offset=2, coverage_part_id=ctx.part_id))

    assert_page(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert_page(second_meta, limit=2, offset=2, total_count=3, has_more=False)
    assert_id_order(first_rows, ids[:2])
    assert_id_order(second_rows, ids[2:])
    assert_created_at_ascending(first_rows + second_rows)

    sub_rows, sub_meta = validate_paginated(api.list_part_equipment_items(
        ctx.part_id, UNDERWRITER, limit=10, offset=0, status="RATED"))
    assert sub_meta["total_count"] == 3
    assert {row["status"] for row in sub_rows} == {"RATED"}


def test_an_unknown_policy_id_is_a_namespaced_not_found(api):
    """A well-formed identifier that resolves to nothing is 404, never an empty 200.

    PRD: A policy identifier that does not resolve yields `ERR_POLICY_NOT_FOUND`; a coverage part identifier `ERR_COVERAGE_PART_NOT_FOUND`; a rate rule identifier `ERR_RATE_RULE_NOT_FOUND`; an equipment item identifier `ERR_EQUIPMENT_ITEM_NOT_FOUND`; a jobsite identifier `ERR_JOBSITE_NOT_FOUND`; an installation floater identifier `ERR_INSTALLATION_FLOATER_NOT_FOUND`; a vehicle identifier `ERR_VEHICLE_NOT_FOUND`; a transit shipment identifier `ERR_TRANSIT_SHIPMENT_NOT_FOUND`; a value report identifier `ERR_VALUE_REPORT_NOT_FOUND`; and a claim identifier `ERR_CLAIM_NOT_FOUND`.
    PRD: The `message` provides a human-readable explanation of what went wrong.
    Design: Corner/entities/corner_policy_not_found_for_unknown_id
    """
    existing = fixtures.create_policy(api, policyholder_name="Existing Co")

    missing = api.get_policy(UNKNOWN_ID, UNDERWRITER)

    validate_error(missing, "ERR_POLICY_NOT_FOUND", 404)
    body = missing.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"].strip() != ""
    assert get_success_data(api.get_policy(
        existing["id"], UNDERWRITER))["id"] == existing["id"]


def test_a_rate_cell_missing_its_base_rate_is_rejected_and_persists_nothing(api):
    """The shape check refuses the cell, so rating afterwards still finds no cell.

    PRD: Every write endpoint validates its payload: all required fields present; integers actually integers; money and limit fields not negative; rate, factor and basis-point fields not negative; every enum field carrying a declared member; dates formatted `YYYY-MM-DD` and instants formatted as ISO 8601 UTC; a policy's `expiration_date` strictly after its `effective_date`; a rate rule's `age_band_min_years` not greater than its `age_band_max_years`; a floater's `coverage_end_date` not earlier than its `coverage_start_date`; a report's `period_end_date` not earlier than its `period_start_date`; a shipment's `arrival_at` strictly after its `departure_at`; and a claim naming exactly one of `equipment_item_id`, `transit_shipment_id` and `installation_floater_id`.
    PRD: If the candidate set is empty the rating is rejected with `ERR_NO_PUBLISHED_RATE_RULE`.
    Design: Corner/entities/corner_rate_rule_missing_required_field_rejected
    """
    refused = api.create_rate_rule(
        factories.rate_rule(base_rate_bp=factories.DROP), ACTUARY)

    validate_error(refused, "ERR_INVALID_REQUEST", 400)

    policy = fixtures.create_policy(api, policyholder_name="Unrated Co")
    part = fixtures.create_part(api, policy["id"],
                                factories.scheduled_equipment_part())
    unrated = api.create_equipment_item(
        part["id"],
        factories.equipment_item(
            expected_policy_version=fixtures.policy_version(api, policy["id"])),
        UNDERWRITER)

    validate_error(unrated, "ERR_NO_PUBLISHED_RATE_RULE", 422)


def test_an_item_omitting_its_basis_and_its_tracker_inherits_and_forgoes(api):
    """The part's replacement-cost basis is copied on and no credit is earned.

    PRD: Where `geo_tracker_installed` is omitted it is false; where `ownership` is omitted it is `OWNED`; where the item-level `valuation_basis` is omitted the parent part's `valuation_basis` is copied onto the item at creation, so the item always carries an explicit basis afterwards.
    PRD: Under `REPLACEMENT_COST`, `insured_value_cents` is the original cost multiplied by the selected rate cell's `replacement_cost_index_bp`, divided by ten thousand, and rounded half-up once.
    Design: Corner/entities/corner_equipment_item_defaults_inherit_part_basis_and_no_tracker
    """
    fixtures.publish_rate_rule(api, equipment_type="LOADER", age_band_min_years=6,
                               age_band_max_years=12, base_rate_bp=205,
                               theft_hazard_grade="B",
                               replacement_cost_index_bp=11000)
    policy = fixtures.create_policy(api, policyholder_name="Default Basis Co")
    part = fixtures.create_part(api, policy["id"], factories.scheduled_equipment_part(
        valuation_basis="REPLACEMENT_COST"))

    item = validate_success(api.create_equipment_item(
        part["id"],
        factories.equipment_item(
            expected_policy_version=fixtures.policy_version(api, policy["id"]),
            description="E4 loader", equipment_type="LOADER", model_year=2016,
            original_cost_cents=4000000),
        UNDERWRITER), 201)

    assert item["valuation_basis"] == "REPLACEMENT_COST"
    assert item["geo_tracker_installed"] is False
    assert item["ownership"] == "OWNED"
    assert item["age_years_at_rating"] == 10
    assert item["insured_value_cents"] == 4400000
    assert item["applied_credit_bp"] == 0
    assert item["rated_premium_cents"] == 114103
    assert item["status"] == "RATED"
    assert item["removed_at"] is None


def test_the_items_computed_block_comes_from_the_clock_and_the_cell(api):
    """Not one figure in the rating trace was supplied by the client.

    PRD: It then fixes `age_years_at_rating` as the calendar year of the logical clock minus the item's `model_year`, floored at 0.
    PRD: The winner's identifier is stored on the item as `applied_rate_rule_id`, its `base_rate_bp` is copied to the item's `applied_base_rate_bp`, and its `theft_hazard_grade` governs the item's theft loading and its tracker credit.
    Design: Corner/entities/corner_equipment_item_computed_fields_derive_from_rate_cell
    """
    ctx = fixtures.build_scheduled_file(
        api, policy_kwargs=dict(policyholder_name="Computed Fields Co"),
        item_kwargs=dict(geo_tracker_installed=False))

    item = validate_success(api.get_equipment_item(ctx.item_id, UNDERWRITER))

    assert item["age_years_at_rating"] == 4
    assert item["insured_value_cents"] == 8160000
    assert item["applied_base_rate_bp"] == 180
    assert item["applied_rate_rule_id"] == ctx.rule_id
    assert item["applied_credit_bp"] == 0
    assert item["rated_premium_cents"] == 173318
    assert item["assigned_jobsite_id"] is None
    assert get_success_data(api.get_coverage_part(
        ctx.part_id, UNDERWRITER))["rated_premium_cents"] == 173318
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["total_insured_value_cents"] == 8160000


def test_the_bind_time_ledger_row_carries_no_version_and_no_updated_at(api):
    """The one immutable row in the domain is shaped differently from every other.

    PRD: Ledger entries are the one exception. A ledger entry is immutable once written, so it carries only `id` and `created_at`; it has neither `updated_at` nor `version`, and neither field appears in its representation.
    PRD: On success the policy moves `QUOTED` → `BOUND`, `bound_at` is stamped from the logical clock, an `INITIAL_PREMIUM` entry is appended to the premium ledger for the full `written_premium_cents` as a positive amount with its `effective_date` set to the policy's own `effective_date`, and `premium_balance_cents` is recomputed from the ledger.
    Design: Corner/entities/corner_ledger_entry_is_immutable_and_versionless
    """
    ctx = fixtures.build_bound_file(api, policy_kwargs=dict(
        policyholder_name="Ledger Only Co"))

    rows, meta = validate_paginated(api.list_ledger_entries(
        ctx.policy_id, UNDERWRITER, limit=10, offset=0, ledger=Ledger.PREMIUM))

    assert meta["total_count"] == 1
    entry = rows[0]
    assert_ledger_entry_shape(entry)
    assert entry["entry_type"] == "INITIAL_PREMIUM"
    assert entry["ledger"] == "PREMIUM"
    assert entry["amount_cents"] == 180251
    assert entry["effective_date"] == "2026-08-01"
    assert "updated_at" not in entry
    assert "version" not in entry
    assert get_success_data(api.get_policy(
        ctx.policy_id, UNDERWRITER))["premium_balance_cents"] == entry["amount_cents"]


def test_a_bad_enum_a_zero_length_term_and_negative_money_all_stop_at_the_shape(api):
    """Three different malformed submissions, one identifier, one status.

    PRD: The submission carries the `policyholder_name` (1 to 120 characters, not blank), the `territory_code` of the garaging address, and the two ends of the term: `effective_date` and `expiration_date`, both ISO 8601 calendar dates, with the expiration strictly later than the effective date.
    PRD: Any breach is `ERR_INVALID_REQUEST` (400).
    Design: Corner/entities/corner_policy_type_constraints_reject_bad_enum_and_inverted_term
    """
    bad_enum = api.create_policy(factories.policy(
        policyholder_name="Bad Territory Co", territory_code="T9_ORBITAL"),
        UNDERWRITER)
    zero_term = api.create_policy(factories.policy(
        policyholder_name="Zero Term Co", effective_date="2026-08-01",
        expiration_date="2026-08-01"), UNDERWRITER)
    negative_money = api.create_policy(factories.policy(
        policyholder_name="Negative Minimum Co", minimum_premium_cents=-1),
        UNDERWRITER)

    validate_error(bad_enum, "ERR_INVALID_REQUEST", 400)
    validate_error(zero_term, "ERR_INVALID_REQUEST", 400)
    validate_error(negative_money, "ERR_INVALID_REQUEST", 400)

    accepted = validate_success(api.create_policy(
        factories.policy(policyholder_name="Well Formed Co"), UNDERWRITER), 201)
    assert accepted["status"] == "DRAFT"


def test_scheduling_under_an_unknown_part_fails_before_the_version_is_read(api):
    """A perfectly good concurrency token cannot rescue an unresolvable parent.

    PRD: Checks are evaluated in one strict, service-wide order, and the **first** check that fails decides the response; no later check is evaluated and no partial mutation is retained.
    PRD: Each identifier embedded in the request path resolves to a live row, checked left to right so that the outermost identifier is validated first.
    Design: Corner/entities/corner_equipment_item_parent_must_exist
    """
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api, policyholder_name="Orphan Item Co")
    version = fixtures.policy_version(api, policy["id"])

    orphan = api.create_equipment_item(
        UNKNOWN_PART_ID,
        factories.equipment_item(expected_policy_version=version,
                                 description="Orphan"),
        UNDERWRITER)

    validate_error(orphan, "ERR_COVERAGE_PART_NOT_FOUND", 404)
    unchanged = get_success_data(api.get_policy(policy["id"], UNDERWRITER))
    assert unchanged["version"] == version
    assert unchanged["total_insured_value_cents"] == 0


def test_a_claim_naming_one_part_and_another_parts_unit_is_refused(api):
    """Both identifiers exist and share a policy, and the pairing is still wrong.

    PRD: Finally the named coverage part must belong to the policy in the path and the named subject must belong to that same coverage part, else `ERR_LOSS_SUBJECT_NOT_ON_PART`.
    PRD: A new claim has `adjustment_status` `OPEN` and `salvage_status` `NOT_APPLICABLE`.
    Design: Corner/entities/corner_hybrid_topology_claim_subject_must_belong_to_named_part
    """
    fixtures.publish_rate_rule(api)
    policy = fixtures.create_policy(api, policyholder_name="Cross Part Co")
    part_a = fixtures.create_part(api, policy["id"],
                                  factories.scheduled_equipment_part())
    part_b = fixtures.create_part(api, policy["id"],
                                  factories.scheduled_equipment_part())
    item_b = fixtures.schedule_item(api, part_b["id"], policy["id"],
                                    description="B-side excavator")
    fixtures.quote(api, policy["id"])
    fixtures.bind(api, policy["id"])
    fixtures.activate(api, policy["id"])
    fixtures.activate_item(api, item_b["id"])

    crossed = api.create_claim(
        policy["id"],
        factories.claim(part_a["id"], loss_date="2026-08-10", loss_type="THEFT",
                        equipment_item_id=item_b["id"]),
        UNDERWRITER)

    validate_error(crossed, "ERR_LOSS_SUBJECT_NOT_ON_PART", 422)

    matched = validate_success(api.create_claim(
        policy["id"],
        factories.claim(part_b["id"], loss_date="2026-08-10", loss_type="THEFT",
                        equipment_item_id=item_b["id"]),
        UNDERWRITER), 201)

    assert matched["coverage_part_id"] == part_b["id"]
    assert matched["equipment_item_id"] == item_b["id"]
    assert matched["adjustment_status"] == "OPEN"
    assert matched["salvage_status"] == "NOT_APPLICABLE"
    _, meta = validate_paginated(api.list_claims(
        UNDERWRITER, limit=10, offset=0, coverage_part_id=part_a["id"]))
    assert meta["total_count"] == 0
