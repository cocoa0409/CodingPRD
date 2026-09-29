"""Entity-level breadth: creation defaults, retrieval, listing, and shape rules."""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    assert_acre_feet,
    assert_append_only_row,
    assert_cents,
    assert_created_at_ascending,
    assert_freeboard,
    assert_instant,
    assert_server_minted_id,
    assert_storage_conservation,
    assert_versioned_row,
)
from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    ALERT_NORMAL,
    ALERT_WATCH,
    CLOCK_ORIGIN,
    DELINQUENCY_CURRENT,
    DELINQUENCY_DELINQUENT,
    EAP_NONE,
    ENTRY_ANNUAL_REGISTRATION_FEE,
    ENTRY_PERMIT_REVIEW_FEE,
    EVENT_MONITORING,
    HAZARD_UNCLASSIFIED,
    LICENSE_ACTIVE,
    LICENSE_EXPIRED,
    OWNER_TYPE_PRIVATE,
    REG_REGISTERED,
    SAFETY_UNRATED,
)
from test_helpers.test_users import TEST_USERS


UNKNOWN_PATH_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_OWNER_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_REACH_ID = "00000000-0000-4000-8000-0000000000bb"


# ---------------------------------------------------------------------------
# Owner creation defaults
# ---------------------------------------------------------------------------
def test_a_new_owner_lands_on_every_declared_fiscal_default(program):
    """The four inputs echo back and every computed field takes its default.

    PRD 3.1: "A freshly registered owner starts with `fee_balance_cents` of 0, a `delinquency_status` of `CURRENT`, and a `registered_dam_count` of 0."

    Design: Corner/entities/owner_creation_populates_system_and_default_fields
    """
    owner = program.create_owner()

    assert owner["legal_name"] == "Cascade Hydro LLC"
    assert owner["owner_type"] == OWNER_TYPE_PRIVATE
    assert owner["contact_email"] == "ops@cascadehydro.example"
    assert_cents(
        owner["financial_assurance_bond_cents"],
        50_000_000,
        "financial_assurance_bond_cents",
    )

    assert_cents(owner["fee_balance_cents"], 0, "fee_balance_cents")
    assert owner["delinquency_status"] == DELINQUENCY_CURRENT
    assert owner["registered_dam_count"] == 0

    assert_server_minted_id(owner)
    assert_instant(owner["created_at"], CLOCK_ORIGIN, "created_at")
    assert_versioned_row(owner, 1)


def test_a_new_owner_has_no_ledger_rows_to_replay(program):
    """The zero balance is the replay of an empty ledger, not a stored default.

    PRD 3.8: "An owner's money position is not a stored number that the program edits; it is the replay of an append-only ledger."

    Design: Corner/entities/owner_creation_populates_system_and_default_fields
    """
    owner = program.create_owner()

    rows, meta = program.ledger(owner["id"])
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Dam retrieval: stored inputs plus derived program state
# ---------------------------------------------------------------------------
def test_a_never_classified_dam_reads_back_its_inputs_and_derived_schedule(
    program, base
):
    """Sixty months after a 2019-04-15 registration the dam is already overdue.

    PRD 3.1: "Its inspection clock starts immediately on the unclassified interval: `next_inspection_due_at` is `registered_at` advanced by 60 calendar months, and `inspection_overdue` is derived from that against the current logical clock."

    Design: Corner/entities/dam_retrieval_returns_stored_inputs_and_derived_program_state
    """
    dam = program.get_dam(base.dam_id, base.engineer_a_headers)

    assert dam["owner_id"] == base.owner_id
    assert dam["river_reach_id"] == base.reach_id
    assert dam["nid_code"] == "ST00123"
    assert dam["height_ft"] == 62
    assert dam["gross_storage_acre_ft"] == 1500
    assert dam["crest_elevation_ft"] == pytest.approx(1042.5, abs=0.005)
    assert dam["normal_pool_elevation_ft"] == pytest.approx(1038.0, abs=0.005)
    assert dam["year_completed"] == 1968

    assert dam["hazard_class"] == HAZARD_UNCLASSIFIED
    assert dam["current_consequence_score"] is None
    assert dam["safety_status"] == SAFETY_UNRATED
    assert dam["regulatory_status"] == REG_REGISTERED
    assert_instant(
        dam["next_inspection_due_at"], "2024-04-15T00:00:00Z", "next_inspection_due_at"
    )
    assert dam["inspection_overdue"] is True


def test_the_new_dams_storage_split_starts_whole_and_counts_against_its_owner(
    program, base
):
    """No release is committed yet, so all of the gross storage is available.

    PRD 3.1: "Its storage split starts whole — `committed_drawdown_acre_ft` of 0 and `available_conservation_storage_acre_ft` equal to `gross_storage_acre_ft` — and the owner's `registered_dam_count` is incremented in the same request."

    Design: Corner/entities/dam_retrieval_returns_stored_inputs_and_derived_program_state
    """
    dam = program.get_dam(base.dam_id, base.engineer_a_headers)

    assert_acre_feet(
        dam["committed_drawdown_acre_ft"], 0.000, "committed_drawdown_acre_ft"
    )
    assert_acre_feet(
        dam["available_conservation_storage_acre_ft"],
        1500.000,
        "available_conservation_storage_acre_ft",
    )
    assert_storage_conservation(dam)

    assert dam["open_deficiency_count"] == 0
    assert dam["latest_eap_status"] == EAP_NONE
    assert dam["eap_required"] is False
    assert_versioned_row(dam, 1)

    assert program.get_owner(base.owner_id)["registered_dam_count"] == 1


# ---------------------------------------------------------------------------
# Dam listing: pagination and created_at ordering
# ---------------------------------------------------------------------------
@pytest.fixture()
def three_dams(program, base):
    """Three dams on one reach, created in the order ST00123, ST00124, ST00125."""
    second = program.create_dam(
        base.owner_id,
        base.reach_id,
        name="Bitter Fork Dam",
        nid_code="ST00124",
        height_ft=40,
        gross_storage_acre_ft=600,
        crest_elevation_ft=980.0,
        normal_pool_elevation_ft=976.0,
        year_completed=1974,
        registered_at="2020-06-01T00:00:00Z",
    )
    third = program.create_dam(
        base.owner_id,
        base.reach_id,
        name="Cedar Notch Dam",
        nid_code="ST00125",
        height_ft=55,
        gross_storage_acre_ft=5000,
        crest_elevation_ft=1105.0,
        normal_pool_elevation_ft=1100.0,
        year_completed=1981,
        registered_at="2021-03-10T00:00:00Z",
    )
    return [base.dam_id, second["id"], third["id"]]


def test_the_dam_listing_walks_its_pages_in_created_at_order(api, program, three_dams):
    """Each window returns the dams in insertion order, never reordered by id.

    PRD 2.3: "List results are ordered by `created_at` ascending in every case — never by `id`, and never by any domain field, even where a domain ordering (such as ledger `sequence_no`) coincides with insertion order."

    Design: Corner/entities/dam_listing_is_paginated_and_ordered_by_created_at
    """
    first_page, _meta = validate_paginated(
        api.list_dams(program.admin, {"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in first_page] == three_dams[:2]
    assert_created_at_ascending(first_page)

    second_page, _m2 = validate_paginated(
        api.list_dams(program.admin, {"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in second_page] == three_dams[2:]


def test_total_count_ignores_the_window_while_has_more_tracks_it(
    api, program, three_dams
):
    """total_count counts the matching rows before the window; has_more tracks the tail.

    PRD 2.3: "The `meta` block of a list response carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters **before** the limit and offset window is applied, and `has_more` as a boolean that is true exactly when rows matching the filters remain beyond the returned window."

    Design: Corner/entities/dam_listing_is_paginated_and_ordered_by_created_at
    """
    assert len(three_dams) == 3

    _rows, first_meta = validate_paginated(
        api.list_dams(program.admin, {"limit": 2, "offset": 0})
    )
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True

    _rows2, last_meta = validate_paginated(
        api.list_dams(program.admin, {"limit": 2, "offset": 2})
    )
    assert last_meta["offset"] == 2
    assert last_meta["total_count"] == 3
    assert last_meta["has_more"] is False


def test_two_filters_narrow_conjunctively_without_disturbing_the_order(
    api, program, base, three_dams
):
    """Owner and hazard class together still return all three, in the same order.

    PRD 2.3: "Filters named on a list endpoint are combined conjunctively: a request for dams filtered by both `hazard_class` and `inspection_overdue` returns only dams satisfying both."

    Design: Corner/entities/dam_listing_is_paginated_and_ordered_by_created_at
    """
    rows, meta = validate_paginated(
        api.list_dams(
            program.admin,
            {"owner_id": base.owner_id, "hazard_class": HAZARD_UNCLASSIFIED},
        )
    )
    assert [row["id"] for row in rows] == three_dams
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Unknown path ids resolve to the entity's own not-found error
# ---------------------------------------------------------------------------
def test_an_unknown_dam_id_on_a_read_returns_the_dam_specific_not_found(api, program):
    """A well-formed but unknown path id is a 404 naming the dam, not a generic error.

    PRD 2.5: "**Path existence** — every `{id}` in the path resolves to an existing row of its expected entity, reported as `ERR_OWNER_NOT_FOUND`, `ERR_ENGINEER_NOT_FOUND`, `ERR_REACH_NOT_FOUND`, `ERR_DAM_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_DEFICIENCY_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_EAP_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_EVENT_NOT_FOUND` or `ERR_DRAWDOWN_NOT_FOUND` as appropriate (all HTTP 404)."

    Design: Corner/entities/dam_fetch_with_unknown_id_returns_dam_not_found
    """
    validate_error(
        api.get_dam(UNKNOWN_PATH_ID, program.admin),
        ApiErrorId.ERR_DAM_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(api.list_dams(program.admin))
    assert meta["total_count"] == 0


def test_the_compliance_snapshot_reports_the_same_missing_dam(api, program):
    """The leftmost path id is resolved before the deeper computed segment.

    PRD 2.4: "Path parameters are validated left to right against the URL hierarchy: the leftmost `{id}` must resolve to an existing row of its expected entity before any deeper segment, body field or business rule is considered."

    Design: Corner/entities/dam_fetch_with_unknown_id_returns_dam_not_found
    """
    validate_error(
        api.get_compliance_summary(UNKNOWN_PATH_ID, program.admin),
        ApiErrorId.ERR_DAM_NOT_FOUND.value,
        404,
    )


# ---------------------------------------------------------------------------
# Syntactic validity outranks every existence, state and business rule
# ---------------------------------------------------------------------------
def test_a_dam_body_missing_its_nid_code_is_a_malformed_request(api, program, base):
    """A required field left out never reaches any business rule.

    PRD 2.5: "**Syntactic validity** of body and query parameters — required fields present, enum members known, numbers within their stated bounds, ISO 8601 instants parseable, `window_start` strictly before `window_end`, `limit` within 1 to 100, `offset` at least 0; otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/dam_creation_missing_required_nid_code_and_invalid_enum_return_invalid_request
    """
    payload = f.dam_payload(
        base.owner_id,
        base.reach_id,
        name="Nameless Dam",
        height_ft=30,
        gross_storage_acre_ft=200,
        crest_elevation_ft=900.0,
        normal_pool_elevation_ft=896.0,
        year_completed=1990,
        registered_at="2022-01-01T00:00:00Z",
    )
    payload.pop("nid_code")

    validate_error(
        api.create_dam(payload, program.admin),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(api.list_dams(program.admin))
    assert meta["total_count"] == 1


def test_an_owner_type_outside_the_enum_is_a_malformed_request(api, program, base):
    """An unknown enum member is caught by the same syntactic layer.

    PRD 2.5: "This layer catches a non-positive `height_ft`, a negative `population_at_risk`, a `requested_release_cfs` that is zero or negative, an `amount_cents` of exactly zero, and any unknown enum member."

    Design: Corner/entities/dam_creation_missing_required_nid_code_and_invalid_enum_return_invalid_request
    """
    validate_error(
        api.create_owner(
            f.owner_payload(
                legal_name="Bad Enum Holdings",
                owner_type="MUNICIPAL_UTILITY_XYZ",
                contact_email="x@example.test",
                financial_assurance_bond_cents=1000,
            ),
            program.admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(api.list_owners(program.admin))
    assert meta["total_count"] == 1
    assert [row["id"] for row in _rows] == [base.owner_id]


def test_a_backwards_window_reports_malformed_and_never_the_unclassified_rule(
    api, program, base
):
    """The dam is also UNCLASSIFIED, yet the higher-priority defect is the one reported.

    PRD 2.5: "This ordering is part of the contract: two defects in a single request always surface as the higher-priority one."

    Design: Corner/entities/dam_creation_missing_required_nid_code_and_invalid_enum_return_invalid_request
    """
    assert program.get_dam(base.dam_id)["hazard_class"] == HAZARD_UNCLASSIFIED

    validate_error(
        api.create_inspection(
            f.inspection_payload(
                base.dam_id,
                base.engineer_a_id,
                window_start="2026-08-06T00:00:00Z",
                window_end="2026-08-04T00:00:00Z",
            ),
            program.admin,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    _rows, meta = validate_paginated(api.list_inspections(program.admin))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# Optional ledger fields default to null
# ---------------------------------------------------------------------------
def test_an_omitted_memo_and_source_ref_come_back_as_nulls(api, program):
    """Only the two mandatory inputs are sent and neither optional becomes an empty string.

    PRD 3.8: "Each ledger entry names the `owner_id` whose balance it moves, carries a `sequence_no`, an `entry_type`, a signed `amount_cents`, an optional `source_ref` free-text reference to the originating permit or order (null when the entry relates to neither), an optional operator `memo` (null when omitted), a derived `balance_after_cents`, and `posted_by_user_id`."

    Design: Corner/entities/optional_fee_adjustment_memo_and_source_ref_default_to_null
    """
    owner = program.create_owner()

    entry = validate_success(
        api.create_fee_adjustment(
            owner["id"],
            f.fee_adjustment_payload(
                entry_type=ENTRY_ANNUAL_REGISTRATION_FEE, amount_cents=5000
            ),
            program.admin,
        ),
        201,
    )
    assert entry["memo"] is None
    assert entry["source_ref"] is None
    assert entry["sequence_no"] == 1
    assert_cents(entry["balance_after_cents"], 5000, "balance_after_cents")


def test_a_five_thousand_cent_charge_leaves_the_owner_below_the_threshold(program):
    """The optional-field posting still writes the owner rollup it is required to write.

    PRD 3.8: "`delinquency_status` is a pure function of the replayed balance and is recomputed on every posting: it reads `DELINQUENT` when `fee_balance_cents` is at or above 25,000 cents — two hundred and fifty dollars, and the threshold is inclusive, so a balance of exactly 25,000 cents is delinquent — and `CURRENT` otherwise."

    Design: Corner/entities/optional_fee_adjustment_memo_and_source_ref_default_to_null
    """
    owner = program.create_owner()
    program.post_ledger_entry(
        owner["id"], entry_type=ENTRY_ANNUAL_REGISTRATION_FEE, amount_cents=5000
    )

    stored = program.get_owner(owner["id"])
    assert_cents(stored["fee_balance_cents"], 5000, "fee_balance_cents")
    assert stored["delinquency_status"] == DELINQUENCY_CURRENT

    _rows, meta = program.ledger(owner["id"])
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Derived licence status against the logical clock
# ---------------------------------------------------------------------------
def test_the_licence_reads_active_before_expiry_and_expired_exactly_at_it(program):
    """The comparison is strict, so the expiry instant itself is already lapsed.

    PRD 2.10: "The derived `license_status` reads `ACTIVE` while `license_expires_at` is strictly later than the current logical clock and `EXPIRED` from the moment the clock reaches it."

    Design: Corner/entities/engineer_license_status_recomputes_to_expired_as_the_clock_advances
    """
    engineer = program.create_engineer(
        full_name="Marta Lund",
        license_number="PE-66301",
        license_expires_at="2026-09-01T00:00:00Z",
        certified_hazard_classes=["LOW", "SIGNIFICANT"],
    )
    assert engineer["license_status"] == LICENSE_ACTIVE
    assert engineer["open_inspection_count"] == 0

    program.set_clock("2026-09-01T00:00:00Z")
    lapsed = program.get_engineer(engineer["id"])
    assert lapsed["license_status"] == LICENSE_EXPIRED
    assert lapsed["open_inspection_count"] == 0


def test_the_expired_filter_finds_the_engineer_without_any_row_being_rewritten(
    api, program
):
    """Nothing was written to the engineer; the status is re-derived on the next read.

    PRD 2.4: "Advancing the clock does not itself mutate any row: an engineer's `license_status` and a dam's `inspection_overdue` are re-derived on the next read, and the enforcement consequences of elapsed time are applied only by the compliance sweep described in §3.9."

    Design: Corner/entities/engineer_license_status_recomputes_to_expired_as_the_clock_advances
    """
    engineer = program.create_engineer(
        full_name="Marta Lund",
        license_number="PE-66301",
        license_expires_at="2026-09-01T00:00:00Z",
        certified_hazard_classes=["LOW", "SIGNIFICANT"],
    )
    before_version = engineer["version"]

    program.set_clock("2026-09-01T00:00:00Z")
    rows, meta = validate_paginated(
        api.list_engineers(program.admin, {"license_status": LICENSE_EXPIRED})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [engineer["id"]]

    assert program.get_engineer(engineer["id"])["version"] == before_version


# ---------------------------------------------------------------------------
# Ledger sequence, balance and poster are all server-assigned
# ---------------------------------------------------------------------------
def test_the_sequence_and_running_balance_are_assigned_by_the_server(program):
    """Two postings take 1 then 2, and the balance is the accumulation of both.

    PRD 3.8: "`sequence_no` is a monotonic per-owner posting sequence starting at 1: a new entry takes the greatest existing `sequence_no` for that owner plus 1, or 1 when the owner has no entries yet."

    Design: Corner/entities/fee_ledger_sequence_balance_and_poster_are_system_assigned
    """
    owner = program.create_owner()
    first = program.post_ledger_entry(
        owner["id"],
        entry_type=ENTRY_ANNUAL_REGISTRATION_FEE,
        amount_cents=20000,
        memo="2026 registration",
    )
    second = program.post_ledger_entry(
        owner["id"],
        entry_type=ENTRY_PERMIT_REVIEW_FEE,
        amount_cents=10000,
        source_ref="manual-adj-2",
    )

    assert first["sequence_no"] == 1
    assert_cents(first["balance_after_cents"], 20000, "balance_after_cents")
    assert second["sequence_no"] == 2
    assert_cents(second["balance_after_cents"], 30000, "balance_after_cents")

    rows, meta = program.ledger(owner["id"])
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert_created_at_ascending(rows)

    stored = program.get_owner(owner["id"])
    assert_cents(stored["fee_balance_cents"], 30000, "fee_balance_cents")
    assert stored["delinquency_status"] == DELINQUENCY_DELINQUENT


def test_the_poster_records_the_acting_administrator_on_a_manual_adjustment(program):
    """A hand-posted adjustment carries the acting identifier, not the system literal.

    PRD 3.8: "Program staff post entries directly through a fee adjustment, supplying `entry_type`, `amount_cents` and optionally `memo` and `source_ref`, and `posted_by_user_id` records the acting administrator's identifier."

    Design: Corner/entities/fee_ledger_sequence_balance_and_poster_are_system_assigned
    """
    owner = program.create_owner()
    entry = program.post_ledger_entry(
        owner["id"],
        entry_type=ENTRY_ANNUAL_REGISTRATION_FEE,
        amount_cents=20000,
        memo="2026 registration",
    )
    assert entry["posted_by_user_id"] == TEST_USERS["program_admin"]["user_id"]
    assert entry["memo"] == "2026 registration"
    assert entry["owner_id"] == owner["id"]
    assert_append_only_row(entry)


# ---------------------------------------------------------------------------
# An elevation reading is an immutable journal row
# ---------------------------------------------------------------------------
@pytest.fixture()
def monitoring_event(program, base):
    """A MONITORING event on the 1042.5-foot-crest dam, clock at the declaration."""
    program.set_clock("2026-08-01T06:00:00Z")
    return program.declare_event(
        base.dam_id,
        declared_at="2026-08-01T06:00:00Z",
        trigger_description="Frontal system, rising inflow",
        declared_inflow_cfs=300,
    )


def test_each_reading_is_a_journal_row_with_no_version_and_no_updated_at(
    program, monitoring_event
):
    """Neither reading response carries the versioning fields a mutable row would.

    PRD 3.7: "Like an exercise, a reading is a journal row carrying `id` and `created_at` only, with no `updated_at` and no `version`."

    Design: Corner/entities/elevation_reading_is_immutable_and_carries_no_version_field
    """
    program.set_clock("2026-08-01T07:00:00Z")
    first = program.add_reading(
        monitoring_event["id"],
        "2026-08-01T07:00:00Z",
        1040.0,
        observed_inflow_cfs=320,
    )
    program.set_clock("2026-08-01T08:00:00Z")
    second = program.add_reading(
        monitoring_event["id"],
        "2026-08-01T08:00:00Z",
        1039.0,
        observed_inflow_cfs=300,
    )

    for reading in (first, second):
        assert_append_only_row(reading)
        assert "version" not in reading
        assert "updated_at" not in reading

    assert_freeboard(first["freeboard_ft"], 2.50, "freeboard_ft")
    assert first["alert_level"] == ALERT_WATCH
    assert first["rising"] is False

    assert_freeboard(second["freeboard_ft"], 3.50, "freeboard_ft")
    assert second["alert_level"] == ALERT_NORMAL
    assert second["rising"] is False


def test_a_later_falling_reading_cannot_rewrite_the_earlier_rows_figures(
    api, program, monitoring_event
):
    """The first row keeps its WATCH band even after a lower pool is recorded.

    PRD 2.4: "Three record types are append-only journal rows and therefore carry **only** `id` and `created_at`: an `EapExercise` (a logged emergency exercise), an `ElevationReading` (a pool observation during a high-water event), and a `FeeLedgerEntry` (a posting on an owner's fee ledger)."

    Design: Corner/entities/elevation_reading_is_immutable_and_carries_no_version_field
    """
    program.set_clock("2026-08-01T07:00:00Z")
    first = program.add_reading(
        monitoring_event["id"],
        "2026-08-01T07:00:00Z",
        1040.0,
        observed_inflow_cfs=320,
    )
    program.set_clock("2026-08-01T08:00:00Z")
    program.add_reading(
        monitoring_event["id"],
        "2026-08-01T08:00:00Z",
        1039.0,
        observed_inflow_cfs=300,
    )

    rows, meta = validate_paginated(
        api.list_readings(monitoring_event["id"], program.admin)
    )
    assert meta["total_count"] == 2
    assert_created_at_ascending(rows)
    assert rows[0]["id"] == first["id"]
    assert_freeboard(rows[0]["freeboard_ft"], 2.50, "freeboard_ft")
    assert rows[0]["alert_level"] == ALERT_WATCH

    event = program.get_event(monitoring_event["id"])
    assert event["reading_count"] == 2
    assert event["peak_pool_elevation_ft"] == pytest.approx(1040.0, abs=0.005)
    assert event["status"] == EVENT_MONITORING


# ---------------------------------------------------------------------------
# Body foreign keys are validated independently
# ---------------------------------------------------------------------------
def test_an_unknown_owner_id_in_the_dam_body_reports_owner_not_found(api, program):
    """A body reference that resolves to nothing is a 404 naming that entity.

    PRD 2.5: "**Body reference existence** — every foreign reference in the request body resolves to an existing row, reported with the same 404 family (`ERR_OWNER_NOT_FOUND`, `ERR_ENGINEER_NOT_FOUND`, `ERR_REACH_NOT_FOUND`, `ERR_DAM_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`)."

    Design: Corner/entities/dam_creation_with_unknown_owner_id_returns_owner_not_found
    """
    owner = program.create_owner()
    reach = program.create_reach()

    validate_error(
        api.create_dam(
            f.dam_payload(
                UNKNOWN_OWNER_ID,
                reach["id"],
                name="Orphan Dam",
                nid_code="ST00900",
                height_ft=30,
                gross_storage_acre_ft=200,
                crest_elevation_ft=900.0,
                normal_pool_elevation_ft=896.0,
                year_completed=1990,
                registered_at="2022-01-01T00:00:00Z",
            ),
            program.admin,
        ),
        ApiErrorId.ERR_OWNER_NOT_FOUND.value,
        404,
    )
    assert program.get_owner(owner["id"])["registered_dam_count"] == 0


def test_an_unknown_reach_id_reports_reach_not_found_and_persists_nothing(api, program):
    """Each foreign key is judged on its own, and the refused dam is never stored.

    PRD 2.5: "Body references are resolved in the order the fields are listed for that operation."

    Design: Corner/entities/dam_creation_with_unknown_owner_id_returns_owner_not_found
    """
    owner = program.create_owner()
    program.create_reach()

    validate_error(
        api.create_dam(
            f.dam_payload(
                owner["id"],
                UNKNOWN_REACH_ID,
                name="Reachless Dam",
                nid_code="ST00901",
                height_ft=30,
                gross_storage_acre_ft=200,
                crest_elevation_ft=900.0,
                normal_pool_elevation_ft=896.0,
                year_completed=1990,
                registered_at="2022-01-01T00:00:00Z",
            ),
            program.admin,
        ),
        ApiErrorId.ERR_REACH_NOT_FOUND.value,
        404,
    )

    _rows, meta = validate_paginated(api.list_dams(program.admin))
    assert meta["total_count"] == 0
