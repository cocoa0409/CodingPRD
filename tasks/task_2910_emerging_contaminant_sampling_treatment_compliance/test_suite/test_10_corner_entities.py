"""Entity shape, defaults, derived seeds, retrieval, listing and referential links.

These are the registry-level guarantees every later workflow reads: what a
creation returns, what the server fills in when the client stays silent, and how
the flat collections point at one another.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_ENTRY_POINT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SAMPLE_NOT_FOUND,
    ERR_SAMPLE_NOT_RECEIVED,
)
from test_helpers.assertions import (
    assert_created_defaults,
    assert_decimal,
    assert_entry_point_posture,
    assert_equals,
    assert_is_null,
    assert_money_cents,
    assert_page,
    assert_status,
    assert_three_fractional_digits,
    assert_total_count,
    first_row,
)
from test_helpers.constants import (
    CANONICAL_ANNUAL_BILLED_KGAL,
    CANONICAL_BASELINE_ANNUAL_REVENUE_CENTS,
    CANONICAL_SERVED_ACCOUNT_COUNT,
)
from test_helpers.fixtures import (
    build_registry,
    collect_sample,
    read_sample,
    received_sample,
    register_contaminant,
    register_entry_point,
    register_laboratory,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER_HEADERS,
    SAMPLING_TECHNICIAN_HEADERS,
    UTILITY_ADMIN_HEADERS,
    make_laboratory_manager_headers,
)


def test_registering_a_contaminant_echoes_every_declared_field(api):
    """A hazard-index member comes back with its denominator and its own tier.

    Declaring PFOA as a hazard-index member with a health-based water
    concentration of 10.0 and a TIER_1 notification tier returns all seven
    declared inputs unchanged in the 201 body, at version 1 with a
    three-fractional-digit creation instant.

    PRD: "A contaminant may also participate in the mixture hazard index:
    `hazard_index_member` defaults to false, and `hbwc_ng_per_l` — the
    health-based water concentration that serves as the hazard-index denominator
    — is required and must be greater than zero when membership is true, and must
    be null when membership is false."

    Design: Corner/entities/contaminant_creation_returns_the_full_declared_field_set
    """
    contaminant = validate_success(
        api.create_contaminant(
            f.contaminant_payload(
                code="PFOA",
                mcl_ng_per_l=4.00,
                trigger_level_ng_per_l=2.00,
                required_mrl_ng_per_l=2.00,
                hazard_index_member=True,
                hbwc_ng_per_l=10.0,
                notification_tier="TIER_1",
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )

    assert_equals(contaminant, "code", "PFOA")
    assert_decimal(contaminant["mcl_ng_per_l"], 4.00, label="mcl_ng_per_l")
    assert_decimal(contaminant["trigger_level_ng_per_l"], 2.00, label="trigger_level_ng_per_l")
    assert_decimal(contaminant["required_mrl_ng_per_l"], 2.00, label="required_mrl_ng_per_l")
    assert_equals(contaminant, "hazard_index_member", True)
    assert_decimal(contaminant["hbwc_ng_per_l"], 10.0, label="hbwc_ng_per_l")
    assert_equals(contaminant, "notification_tier", "TIER_1")
    assert_created_defaults(contaminant)
    assert_three_fractional_digits(contaminant["created_at"])


def test_omitting_the_optional_contaminant_inputs_lands_on_the_declared_defaults(api):
    """Silence is not null across the board: two defaults are values, one is null.

    Registering PFBS with only its code and three concentrations leaves
    hazard_index_member false and hbwc_ng_per_l null, but notification_tier is
    filled in as TIER_2 rather than left empty.

    PRD: "Finally, `notification_tier` records the baseline public-notification
    tier the utility owes on a maximum-contaminant-level violation of this
    compound; it defaults to `TIER_2` and must be one of `TIER_1`, `TIER_2` or
    `TIER_3`."

    Design: Corner/entities/contaminant_optional_inputs_fall_back_to_declared_defaults
    """
    contaminant = validate_success(
        api.create_contaminant(
            f.contaminant_payload(
                code="PFBS",
                mcl_ng_per_l=6.00,
                trigger_level_ng_per_l=3.00,
                required_mrl_ng_per_l=2.00,
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )

    assert_equals(contaminant, "hazard_index_member", False)
    assert_is_null(contaminant, "hbwc_ng_per_l")
    assert_equals(contaminant, "notification_tier", "TIER_2")
    assert_decimal(contaminant["mcl_ng_per_l"], 6.00, label="mcl_ng_per_l")
    assert_created_defaults(contaminant)


def test_registering_an_entry_point_freezes_the_rate_base_and_zeroes_the_counters(api):
    """One population figure seeds three billing integers and eight zeroed fields.

    A population of 45000 is the only billing input, and it fixes 18000 accounts,
    1080000 thousand-gallon units and 1026000000 cents of baseline revenue, while
    the monitoring posture starts at INITIAL and COMPLIANT with every derived
    counter at zero.

    PRD: "The utility bills one account for every two and a half residents, so
    `served_account_count` is the population served divided by two and a half and
    then rounded up to the next whole account."

    Design: Corner/entities/entry_point_creation_seeds_the_derived_billing_and_posture_fields
    """
    entry_point = validate_success(
        api.create_entry_point(
            f.entry_point_payload(
                label="EPTDS-01", source_type="GROUNDWATER", population_served=45000
            ),
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )

    assert_equals(entry_point, "served_account_count", CANONICAL_SERVED_ACCOUNT_COUNT)
    assert_equals(entry_point, "annual_billed_kgal", CANONICAL_ANNUAL_BILLED_KGAL)
    assert_money_cents(
        entry_point["baseline_annual_revenue_cents"],
        CANONICAL_BASELINE_ANNUAL_REVENUE_CENTS,
        "baseline_annual_revenue_cents",
    )
    assert_is_null(entry_point, "requested_monitoring_status")
    assert_entry_point_posture(
        entry_point,
        posture="COMPLIANT",
        monitoring_status="INITIAL",
        treatment_status="NONE",
        accepted_result_count=0,
        max_compliance_ratio=0.0,
        hazard_index=0.00,
        consecutive_qualifying_quarters=0,
        consecutive_invalidated_samples=0,
        open_violation_count=0,
    )
    assert_created_defaults(entry_point)


def test_an_entry_point_without_a_population_is_a_request_shape_failure(api):
    """population_served has no default, so omitting it is not a silent zero.

    A body carrying only the label and the source type is missing a required
    field, which is refused as a request-shape failure and leaves the entry-point
    collection empty.

    PRD: "**Request shape** — an unknown enum value, a wrong JSON type, a missing
    required body field, a negative number where non-negative is required, more
    than two decimal places on a two-decimal field, a malformed ISO 8601 instant,
    a malformed period label, or a value outside a declared range:
    `ERR_INVALID_REQUEST` (HTTP 422), on every write endpoint."

    Design: Corner/entities/entry_point_missing_population_served_returns_invalid_request
    """
    validate_error(
        api.create_entry_point(
            {"label": "EPTDS-01", "source_type": "GROUNDWATER"}, UTILITY_ADMIN_HEADERS
        ),
        ERR_INVALID_REQUEST,
        422,
    )

    assert_total_count(api.list_entry_points(COMPLIANCE_OFFICER_HEADERS), 0)


def test_reading_a_laboratory_back_returns_its_certification_verbatim(api):
    """The methods array keeps its order and the unstated throughput takes its default.

    A facility registered for METHOD_533 and METHOD_1633 with no throughput
    supplied reads back with both methods in the submitted order, its certification
    identifier and expiry intact, and a daily analysis capacity of three.

    PRD: "Registration captures a `name` of one to one hundred and twenty
    characters, a state `certification_id` of one to forty characters that must be
    unique across all laboratories — a repeat is refused with
    `ERR_DUPLICATE_CERTIFICATION_ID` — and `certified_methods`, a non-empty array
    of distinct analytical methods drawn from `METHOD_533`, `METHOD_537_1` and
    `METHOD_1633`."

    Design: Corner/entities/laboratory_retrieval_returns_every_stored_certification_field
    """
    created = validate_success(
        api.create_laboratory(
            {
                "name": "Northgate Analytical",
                "certification_id": "CERT-001",
                "certified_methods": ["METHOD_533", "METHOD_1633"],
                "lowest_achievable_dl_ng_per_l": 1.00,
                "certification_expires_on": "2027-12-31T00:00:00.000Z",
            },
            UTILITY_ADMIN_HEADERS,
        ),
        201,
    )

    stored = validate_success(api.get_laboratory(created["id"], COMPLIANCE_OFFICER_HEADERS))

    assert_equals(stored, "name", "Northgate Analytical")
    assert_equals(stored, "certification_id", "CERT-001")
    assert_equals(stored, "certified_methods", ["METHOD_533", "METHOD_1633"])
    assert_decimal(
        stored["lowest_achievable_dl_ng_per_l"], 1.00, label="lowest_achievable_dl_ng_per_l"
    )
    assert_equals(stored, "daily_analysis_capacity", 3)
    assert_created_defaults(stored)


def test_an_unknown_entry_point_path_id_reports_the_addressed_collections_own_code(api):
    """The 404 names the collection in the URL, not a generic not-found.

    A syntactically valid identifier that matches no row is refused with the
    entry-point collection's own not-found code.

    PRD: "Where an endpoint's URL carries an `{id}` path parameter, that segment
    is resolved before any body content is examined, and an unresolvable segment
    yields the 404 of the addressed collection."

    Design: Corner/entities/entry_point_get_with_an_unknown_id_returns_not_found
    """
    validate_error(
        api.get_entry_point(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_HEADERS),
        ERR_ENTRY_POINT_NOT_FOUND,
        404,
    )


def test_the_sample_list_pages_three_rows_as_two_then_one(api):
    """total_count counts the filter matches, not the page, on both pages.

    Three collected samples at one entry point split into a first page of two with
    has_more true and a second page of one with has_more false, while total_count
    reads three throughout and the applied limit and offset are echoed back.

    PRD: "The `meta` object of every list response carries `limit` and `offset` as
    they were applied, `total_count` as the number of rows matching the filters
    before pagination, and `has_more` as a boolean indicating whether rows remain
    beyond the current page."

    Design: Corner/entities/sample_listing_paginates_and_reports_total_count_and_has_more
    """
    contaminant = register_contaminant(api)
    entry_point = register_entry_point(api)
    ids = [
        collect_sample(
            api,
            entry_point["id"],
            [contaminant["id"]],
            monitoring_period=period,
            preservative_lot=lot,
        )["id"]
        for period, lot in (("2025Q4", "LOT-A"), ("2026Q1", "LOT-B"), ("2026Q2", "LOT-C"))
    ]

    first_page = api.list_samples(
        COMPLIANCE_OFFICER_HEADERS,
        params={"entry_point_id": entry_point["id"], "limit": 2, "offset": 0},
    )
    second_page = api.list_samples(
        COMPLIANCE_OFFICER_HEADERS,
        params={"entry_point_id": entry_point["id"], "limit": 2, "offset": 2},
    )

    first_rows = assert_page(first_page, 3, True)
    second_rows = assert_page(second_page, 3, False)
    assert len(first_rows) == 2, f"Expected two rows on the first page, got {len(first_rows)}"
    assert len(second_rows) == 1, f"Expected one row on the second page, got {len(second_rows)}"
    _, first_meta = validate_paginated(first_page)
    _, second_meta = validate_paginated(second_page)
    assert (first_meta["limit"], first_meta["offset"]) == (2, 0), (
        f"Expected limit 2 offset 0, got {first_meta['limit']} {first_meta['offset']}"
    )
    assert (second_meta["limit"], second_meta["offset"]) == (2, 2), (
        f"Expected limit 2 offset 2, got {second_meta['limit']} {second_meta['offset']}"
    )
    paged = [row["id"] for row in first_rows + second_rows]
    assert sorted(paged) == sorted(ids), f"Expected the three collected samples, got {paged}"
    for row in first_rows + second_rows:
        assert_status(row, "COLLECTED")


def test_a_collection_protocol_outside_the_declared_pair_is_rejected(api):
    """Only two protocols exist, and an invented third is a shape failure.

    Every other field of the collection body is valid and the entry point accepts
    samples, but the protocol token is not one of the two declared values, so the
    collection is refused and no sample row is created.

    PRD: "`protocol` as either `LOW_FLOW_GRAB` or `COMPOSITE`"

    Design: Corner/entities/sample_protocol_outside_the_declared_enum_is_rejected
    """
    contaminant = register_contaminant(api)
    entry_point = register_entry_point(api)

    validate_error(
        api.create_sample(
            f.sample_payload(
                entry_point["id"],
                [contaminant["id"]],
                protocol="SCOOP_BUCKET",
                preservative_lot="LOT-BADENUM",
            ),
            SAMPLING_TECHNICIAN_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        422,
    )

    assert_total_count(
        api.list_samples(COMPLIANCE_OFFICER_HEADERS, params={"entry_point_id": entry_point["id"]}),
        0,
    )


def test_a_result_naming_an_unresolvable_sample_reports_the_samples_not_found_code(api):
    """A dangling body foreign key outranks the state gate it would have hit next.

    There is no sample at all behind the identifier, so the refusal is the sample
    collection's 404 rather than the not-received state refusal — there is no state
    to read.

    PRD: "Where a request supplies an identifier in its body or as a list filter,
    resolution failure yields the 404 of the referenced collection instead — so a
    sample creation naming a non-existent entry point reports
    `ERR_ENTRY_POINT_NOT_FOUND`, one naming a non-existent contaminant in its
    panel reports `ERR_CONTAMINANT_NOT_FOUND`, and one whose resample reference
    does not resolve reports `ERR_SAMPLE_NOT_FOUND`."

    Design: Corner/entities/lab_result_with_an_unresolvable_sample_id_returns_not_found
    """
    contaminant = register_contaminant(api)
    laboratory = register_laboratory(api)
    lab_headers = make_laboratory_manager_headers(laboratory["id"])

    response = api.create_lab_result(
        f.lab_result_payload(NON_EXISTENT_UUID, contaminant["id"]), lab_headers
    )

    validate_error(response, ERR_SAMPLE_NOT_FOUND, 404)
    assert response.json()["data"]["error_id"] != ERR_SAMPLE_NOT_RECEIVED, (
        "A missing sample must not be reported as an unreceived sample"
    )
    assert_total_count(
        api.list_lab_results(lab_headers, params={"laboratory_id": laboratory["id"]}), 0
    )


def test_a_result_takes_its_laboratory_from_the_samples_assignment(api):
    """The flat topology means every link is a resolvable foreign key.

    The created result points back at its sample and its contaminant, and its
    laboratory is the one the sample was assigned to rather than an independently
    supplied identifier; both directions of the relationship are then discoverable
    through the filtered lists.

    PRD: "Relationships are instead discovered through filtered list queries on
    the child collection, and every list endpoint accepts the foreign-key filters
    relevant to its own rows in addition to `limit` and `offset`."

    Design: Corner/entities/lab_result_inherits_the_flat_topology_links_of_its_sample
    """
    registry = build_registry(api)
    sample = received_sample(
        api,
        registry["entry_point_id"],
        [registry["contaminant_id"]],
        registry["laboratory_id"],
        preservative_lot="LOT-FK",
    )

    result = validate_success(
        api.create_lab_result(
            f.lab_result_payload(sample["id"], registry["contaminant_id"]), registry["lab_headers"]
        ),
        201,
    )

    assert_equals(result, "sample_id", sample["id"])
    assert_equals(result, "contaminant_id", registry["contaminant_id"])
    assert_equals(result, "laboratory_id", registry["laboratory_id"])
    assert_equals(read_sample(api, sample["id"]), "assigned_laboratory_id", registry["laboratory_id"])
    assert_equals(
        first_row(
            api.list_lab_results(COMPLIANCE_OFFICER_HEADERS, params={"sample_id": sample["id"]})
        ),
        "id",
        result["id"],
    )
    assert_equals(
        first_row(
            api.list_samples(
                COMPLIANCE_OFFICER_HEADERS,
                params={"assigned_laboratory_id": registry["laboratory_id"]},
            )
        ),
        "id",
        sample["id"],
    )
