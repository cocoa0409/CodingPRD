"""Entity-surface compliance tests: creation, retrieval, listing, required fields,
declared defaults, derived fields, system-stamped fields, append-only records,
path-parent scoping and cross-aggregate navigation.

Every test builds its own state from scratch against an empty database.
"""
import pytest

from test_helpers import (
    DEFAULT_CLOCK_INSTANT,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN,
    COMPLIANCE,
    DESK,
    EXAMINER,
    TREASURY,
    USER_IDS,
)


def _bank_baselines(**overrides) -> dict:
    """The four balance baselines supplied at registration (PRD §3.1)."""
    payload = {
        "core_deposits_cents": 30_000_000_000,
        "total_liabilities_cents": 45_000_000_000,
        "tier1_capital_cents": 4_000_000_000,
        "liquidity_buffer_cents": 900_000_000,
    }
    payload.update(overrides)
    return payload


def test_institution_creation_returns_every_declared_field():
    """A bank registration returns the whole record with its derived figures empty.

    PRD §3.1: "A newly registered bank starts with all four derived deposit figures
    at their empty values: `brokered_deposits_cents`, `listing_service_deposits_cents`
    and `reciprocal_deposits_cents` are 0, `total_deposits_cents` equals
    `core_deposits_cents`, `wholesale_funding_ratio_bps` and
    `single_broker_max_ratio_bps` are 0, `breached_metric_count` is 0 and
    `concentration_posture` is `OPEN`."

    PRD §3.1: "From the capital category the system immediately derives
    `rate_cap_regime`, which is `EXEMPT` when the category is `WELL_CAPITALIZED` and
    `CAPPED` for every other category."

    PRD §2.5: "Every resource carries a server-minted `id` that is a UUID string with
    no type prefix, and a `created_at` timestamp in ISO 8601 UTC with exactly three
    fractional digits."

    Design: Corner/entities/corner_institution_creation_returns_every_declared_field
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    payload = f.institution_payload(
        legal_name="Corner Bank NA",
        cert_id="CERT-9001",
        capital_category="WELL_CAPITALIZED",
        **_bank_baselines(),
    )

    data = validate_success(
        api_client.create_institution(payload, ADMIN), expected_status=201
    )

    asserts.assert_institution(data)
    assert data["legal_name"] == "Corner Bank NA", "legal_name must be echoed back"
    assert data["cert_id"] == "CERT-9001", "cert_id must be echoed back"
    assert data["rate_cap_regime"] == "EXEMPT", (
        "rate_cap_regime must be EXEMPT for a WELL_CAPITALIZED bank, got "
        f"{data['rate_cap_regime']}"
    )
    assert data["brokered_deposits_cents"] == 0, "brokered_deposits_cents starts at 0"
    assert data["listing_service_deposits_cents"] == 0, (
        "listing_service_deposits_cents starts at 0"
    )
    assert data["reciprocal_deposits_cents"] == 0, (
        "reciprocal_deposits_cents starts at 0"
    )
    assert data["total_deposits_cents"] == 30_000_000_000, (
        "total_deposits_cents must equal core_deposits_cents on a fresh bank, got "
        f"{data['total_deposits_cents']}"
    )
    assert data["wholesale_funding_ratio_bps"] == 0, (
        "wholesale_funding_ratio_bps starts at 0"
    )
    assert data["single_broker_max_ratio_bps"] == 0, (
        "single_broker_max_ratio_bps starts at 0"
    )
    assert data["breached_metric_count"] == 0, "breached_metric_count starts at 0"
    assert data["concentration_posture"] == "OPEN", (
        f"concentration_posture starts at OPEN, got {data['concentration_posture']}"
    )
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID string"
    assert is_iso8601_timestamp(data["created_at"]), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data["updated_at"]), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert data["version"] == 1, f"version starts at 1, got {data['version']}"


def test_institution_retrieval_returns_stored_row_without_drift():
    """Reading a bank back returns exactly the row the registration created.

    PRD §2.5: "Most resources additionally carry `updated_at`, refreshed to the
    current logical-clock instant whenever any field of the record changes, and
    `version`, an integer that starts at 1 on creation and increases by exactly 1 on
    each mutation of the record."

    Design: Corner/entities/corner_institution_retrieval_returns_stored_row
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    created = validate_success(
        api_client.create_institution(
            f.institution_payload(
                legal_name="Corner Bank NA", cert_id="CERT-9002", **_bank_baselines()
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    read = validate_success(api_client.get_institution(created["id"], TREASURY))

    assert read["id"] == created["id"], "the read must address the same row"
    assert read["cert_id"] == "CERT-9002", "cert_id must round-trip unchanged"
    assert read["total_liabilities_cents"] == 45_000_000_000, (
        "total_liabilities_cents must round-trip unchanged"
    )
    assert read["total_deposits_cents"] == 30_000_000_000, (
        "total_deposits_cents must still be core_deposits_cents"
    )
    assert read["concentration_posture"] == "OPEN", "posture must round-trip unchanged"
    assert read["version"] == 1, (
        f"no write happened between, so version stays 1, got {read['version']}"
    )
    for field, value in created.items():
        assert read[field] == value, (
            f"{field} must not drift between the create response and the read: "
            f"created {value!r}, read {read.get(field)!r}"
        )


def _publish_benchmark_history() -> list:
    """Three successive publications for one maturity bucket, oldest first."""
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    rows = []
    for effective_date, rate_bps in (
        ("2026-05-01", 300),
        ("2026-06-01", 350),
        ("2026-07-01", 400),
    ):
        rows.append(
            validate_success(
                api_client.publish_national_rate_cap(
                    f.national_rate_cap_payload(
                        tenor_bucket="DAYS_31_90",
                        published_national_rate_bps=rate_bps,
                        effective_date=effective_date,
                    ),
                    ADMIN,
                ),
                expected_status=201,
            )
        )
    return rows


def test_national_rate_cap_listing_pagination_envelope():
    """The benchmark listing pages a three-row history and echoes the window.

    PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted
    value is 1 and its maximum accepted value is 100."

    PRD §2.3: "Both are echoed in the `meta` object of the response alongside
    `total_count`, the number of records matching the filter before the page window
    is applied, and `has_more`, which is true when records remain beyond the current
    window."

    PRD §2.3: "published rate benchmarks by `effective_date` descending with ties
    broken by `created_at` descending, which is exactly the ranking the ceiling
    calculation uses to pick the governing publication"

    Design: Corner/entities/corner_national_rate_cap_listing_pagination_envelope
    """
    may, june, july = _publish_benchmark_history()

    first, meta = validate_paginated(
        api_client.list_national_rate_caps(ADMIN, params={"limit": 2, "offset": 0})
    )
    assert [row["id"] for row in first] == [july["id"], june["id"]], (
        "the first page must hold the two most recently effective publications, "
        "newest effective_date first"
    )
    assert meta["limit"] == 2, f"limit must be echoed, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset must be echoed, got {meta['offset']}"
    assert meta["total_count"] == 3, (
        f"total_count counts all matching rows before the window, got {meta['total_count']}"
    )
    assert meta["has_more"] is True, "one row remains beyond the first window"

    second, meta2 = validate_paginated(
        api_client.list_national_rate_caps(ADMIN, params={"limit": 2, "offset": 2})
    )
    assert [row["id"] for row in second] == [may["id"]], (
        "the tail page must hold the oldest publication only"
    )
    assert meta2["offset"] == 2, f"offset must be echoed, got {meta2['offset']}"
    assert meta2["total_count"] == 3, "total_count is window independent"
    assert meta2["has_more"] is False, "nothing remains beyond the final window"


def test_national_rate_cap_listing_defaults_limit_and_exposes_derived_ceilings():
    """An unparameterised benchmark listing defaults its window and carries both
    derived ceilings on every row.

    PRD §2.3: "`limit` controls page size: it defaults to 10, its minimum accepted
    value is 1 and its maximum accepted value is 100."

    PRD §3.1: "Two derived figures are stamped on it for convenience: `cap_bps` is
    the published rate plus 75 basis points, and `non_maturity_cap_bps` is the
    published rate plus 50 basis points, the tighter ceiling that clamps non-maturity
    products."

    Design: Corner/entities/corner_national_rate_cap_listing_pagination_envelope
    """
    _publish_benchmark_history()

    rows, meta = validate_paginated(api_client.list_national_rate_caps(TREASURY))

    assert meta["limit"] == 10, f"limit defaults to 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"offset defaults to 0, got {meta['offset']}"
    assert meta["total_count"] == 3, f"three publications exist, got {meta['total_count']}"
    assert meta["has_more"] is False, "three rows fit inside the default window"
    assert len(rows) == 3, f"the default window returns all three rows, got {len(rows)}"
    for row in rows:
        published = row["published_national_rate_bps"]
        assert row["cap_bps"] == published + 75, (
            f"cap_bps must be {published} + 75, got {row['cap_bps']}"
        )
        assert row["non_maturity_cap_bps"] == published + 50, (
            f"non_maturity_cap_bps must be {published} + 50, got "
            f"{row['non_maturity_cap_bps']}"
        )


@pytest.mark.parametrize(
    "read_call, expected_error_id",
    [
        (
            lambda: api_client.get_institution(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_INSTITUTION_NOT_FOUND,
        ),
        (
            lambda: api_client.get_broker(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_BROKER_NOT_FOUND,
        ),
        (
            lambda: api_client.get_agreement(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_AGREEMENT_NOT_FOUND,
        ),
        (
            lambda: api_client.get_exception(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_EXCEPTION_NOT_FOUND,
        ),
        (
            lambda: api_client.get_program(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        ),
        (
            lambda: api_client.get_classification(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_CLASSIFICATION_NOT_FOUND,
        ),
        (
            lambda: api_client.get_placement(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_PLACEMENT_NOT_FOUND,
        ),
        (
            lambda: api_client.get_contingency_plan(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_PLAN_NOT_FOUND,
        ),
        (
            lambda: api_client.get_call_report_filing(NON_EXISTENT_UUID, ADMIN),
            ApiErrorId.ERR_FILING_NOT_FOUND,
        ),
    ],
    ids=[
        "institution",
        "broker",
        "agreement",
        "exception",
        "program",
        "classification",
        "placement",
        "plan",
        "filing",
    ],
)
def test_unknown_addressed_ids_return_typed_not_found_errors(read_call, expected_error_id):
    """Every addressed read of an absent row answers with its own typed 404.

    PRD §2.7: "Foreign keys travelling in a body or query string are resolved with
    the same not-found codes as their addressed counterparts: an unknown bank
    reference yields `ERR_INSTITUTION_NOT_FOUND`, an unknown counterparty
    `ERR_BROKER_NOT_FOUND`, an unknown agreement `ERR_AGREEMENT_NOT_FOUND`, an
    unknown exception filing `ERR_EXCEPTION_NOT_FOUND`, an unknown program
    `ERR_PROGRAM_NOT_FOUND`, an unknown classification
    `ERR_CLASSIFICATION_NOT_FOUND`, an unknown placement `ERR_PLACEMENT_NOT_FOUND`,
    an unknown contingency plan `ERR_PLAN_NOT_FOUND` and an unknown call report
    filing `ERR_FILING_NOT_FOUND`. All nine are HTTP 404."

    Design: Corner/entities/corner_unknown_ids_return_typed_not_found_errors
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)

    validate_error(read_call(), expected_error_id.value)


def test_unknown_body_foreign_keys_return_the_addressed_not_found_codes():
    """A dangling reference inside a request body earns the same typed 404 as the
    addressed read of that reference.

    PRD §2.7: "Foreign keys travelling in a body or query string are resolved with
    the same not-found codes as their addressed counterparts: an unknown bank
    reference yields `ERR_INSTITUTION_NOT_FOUND`, an unknown counterparty
    `ERR_BROKER_NOT_FOUND`, an unknown agreement `ERR_AGREEMENT_NOT_FOUND`, an
    unknown exception filing `ERR_EXCEPTION_NOT_FOUND`, an unknown program
    `ERR_PROGRAM_NOT_FOUND`, an unknown classification
    `ERR_CLASSIFICATION_NOT_FOUND`, an unknown placement `ERR_PLACEMENT_NOT_FOUND`,
    an unknown contingency plan `ERR_PLAN_NOT_FOUND` and an unknown call report
    filing `ERR_FILING_NOT_FOUND`. All nine are HTTP 404."

    Design: Corner/entities/corner_unknown_ids_return_typed_not_found_errors
    """
    env = fx.setup_bank()
    # PRD §3.4: "Where `broker_id` is present, `agreement_id` is required", so the
    # unknown-counterparty probe must still carry an agreement_id for the request
    # to be well shaped; §2.8 orders counterparty existence (5) ahead of agreement
    # existence (6) and the broker/agreement mismatch check (45).
    cleared = fx.setup_approved_agreement()

    validate_error(
        api_client.create_program(
            f.program_payload(NON_EXISTENT_UUID), DESK
        ),
        ApiErrorId.ERR_INSTITUTION_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_program(
            f.program_payload(
                env["institution"]["id"],
                broker_id=NON_EXISTENT_UUID,
                agreement_id=cleared["agreement"]["id"],
                funding_channel_claim="BROKERED",
            ),
            DESK,
        ),
        ApiErrorId.ERR_BROKER_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_placement(f.placement_payload(NON_EXISTENT_UUID), DESK),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND.value,
    )


@pytest.mark.parametrize(
    "case",
    [
        "institution_missing_cert_id",
        "program_missing_product_type",
        "placement_missing_principal_cents",
        "filing_missing_core_reported_cents",
    ],
)
def test_missing_required_fields_rejected(case):
    """A create that omits a field with no declared default is an invalid request.

    PRD §2.8: "Request shape: every input field that has no declared default is
    present, every enum-typed field carries a declared member, integer fields are
    integers, `_cents` and `_bps` fields are not negative, diligence sub-scores lie
    within 0 to 100 inclusive, calendar-date fields are formatted as year-month-day
    and instant fields are ISO 8601 UTC — `ERR_INVALID_REQUEST`. All write
    endpoints."

    PRD §3.9: "The operator supplies the three figures actually being reported:
    `rc_e_brokered_reported_cents` for the brokered line of schedule RC-E memorandum
    line 1, `rc_o_listing_reported_cents` for listing-service non-brokered deposits,
    and `rc_e_core_reported_cents` for core deposits, each a non-negative whole
    number of cents and all three required at creation."

    Design: Corner/entities/corner_missing_required_fields_rejected
    """
    if case == "institution_missing_cert_id":
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        payload = f.institution_payload(**_bank_baselines())
        payload.pop("cert_id")
        response = api_client.create_institution(payload, ADMIN)
    elif case == "program_missing_product_type":
        env = fx.setup_bank(institution_overrides=_bank_baselines())
        payload = f.program_payload(env["institution"]["id"])
        payload.pop("product_type")
        response = api_client.create_program(payload, DESK)
    elif case == "placement_missing_principal_cents":
        env = fx.setup_open_core_program(institution_overrides=_bank_baselines())
        payload = f.placement_payload(env["program"]["id"])
        payload.pop("principal_cents")
        response = api_client.create_placement(payload, DESK)
    else:
        env = fx.setup_bank(institution_overrides=_bank_baselines())
        payload = f.call_report_filing_payload()
        payload.pop("rc_e_core_reported_cents")
        response = api_client.create_call_report_filing(
            env["institution"]["id"], payload, DESK
        )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_rejected_create_leaves_no_partial_row_behind():
    """A shape-rejected registration writes nothing at all.

    PRD §2.8: "Request shape: every input field that has no declared default is
    present, every enum-typed field carries a declared member, integer fields are
    integers, `_cents` and `_bps` fields are not negative, diligence sub-scores lie
    within 0 to 100 inclusive, calendar-date fields are formatted as year-month-day
    and instant fields are ISO 8601 UTC — `ERR_INVALID_REQUEST`. All write
    endpoints."

    Design: Corner/entities/corner_missing_required_fields_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    good = validate_success(
        api_client.create_institution(
            f.institution_payload(cert_id="CERT-9003", **_bank_baselines()), ADMIN
        ),
        expected_status=201,
    )

    broken = f.institution_payload(cert_id="CERT-9004", **_bank_baselines())
    broken.pop("legal_name")
    validate_error(
        api_client.create_institution(broken, ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(api_client.list_institutions(ADMIN))
    assert meta["total_count"] == 1, (
        f"only the accepted registration may exist, got {meta['total_count']} rows"
    )
    assert [row["id"] for row in rows] == [good["id"]], (
        "the rejected registration must not have created a row"
    )


def test_institution_capital_category_takes_its_declared_default():
    """A registration silent on capital category is booked WELL_CAPITALIZED and
    therefore EXEMPT.

    PRD §3.1: "The prompt-corrective-action capital category may be supplied as
    `capital_category` and defaults to `WELL_CAPITALIZED`; the accepted members are
    `WELL_CAPITALIZED`, `ADEQUATELY_CAPITALIZED`, `UNDERCAPITALIZED`,
    `SIGNIFICANTLY_UNDERCAPITALIZED` and `CRITICALLY_UNDERCAPITALIZED`."

    PRD §3.1: "From the capital category the system immediately derives
    `rate_cap_regime`, which is `EXEMPT` when the category is `WELL_CAPITALIZED` and
    `CAPPED` for every other category."

    Design: Corner/entities/corner_omitted_optional_inputs_take_declared_defaults
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    payload = f.institution_payload(cert_id="CERT-9005", **_bank_baselines())
    payload.pop("capital_category")

    data = validate_success(
        api_client.create_institution(payload, ADMIN), expected_status=201
    )

    assert data["capital_category"] == "WELL_CAPITALIZED", (
        "an omitted capital_category must default to WELL_CAPITALIZED, got "
        f"{data['capital_category']}"
    )
    assert data["rate_cap_regime"] == "EXEMPT", (
        f"the default category derives an EXEMPT regime, got {data['rate_cap_regime']}"
    )


def test_counterparty_omitted_fee_amounts_default_to_zero():
    """A counterparty registration silent on both fee amounts books them at zero and
    starts with an untouched diligence mirror.

    PRD §3.2: "A headline fee construct is also captured: `fee_structure` is one of
    `FLAT_FEE`, `BASIS_POINT_FEE`, `VOLUME_TIERED` or `PER_ACCOUNT_FEE`, with
    `fee_bps` defaulting to 0 and ignored when the structure is `FLAT_FEE`, and
    `fee_flat_cents` defaulting to 0 and ignored whenever the structure is anything
    other than `FLAT_FEE`."

    PRD §3.2: "A fresh counterparty starts with `diligence_status` of `NOT_STARTED`
    and `approved_agreement_count` of 0; the status is a mirror of the counterparty's
    governing agreement and is only ever moved by the diligence cascade below, never
    written directly."

    Design: Corner/entities/corner_omitted_optional_inputs_take_declared_defaults
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    payload = f.broker_payload(fee_structure="VOLUME_TIERED")
    payload.pop("fee_flat_cents", None)
    payload.pop("fee_bps", None)

    data = validate_success(api_client.create_broker(payload, DESK), expected_status=201)

    assert data["fee_bps"] == 0, f"fee_bps defaults to 0, got {data['fee_bps']}"
    assert data["fee_flat_cents"] == 0, (
        f"fee_flat_cents defaults to 0, got {data['fee_flat_cents']}"
    )
    assert data["diligence_status"] == "NOT_STARTED", (
        f"a fresh counterparty is NOT_STARTED, got {data['diligence_status']}"
    )
    assert data["approved_agreement_count"] == 0, (
        f"approved_agreement_count starts at 0, got {data['approved_agreement_count']}"
    )


def test_program_omitted_optional_inputs_take_their_declared_defaults():
    """A program create silent on its optional terms books false, zero and null.

    PRD §3.4: "`early_withdrawal_penalty_days` is the number of days of interest a
    depositor forfeits on early withdrawal, and `principal_erosion_allowed`,
    defaulting to false, records whether the contractual penalty may exceed the
    interest actually earned and bite into principal — it is the flag that selects
    between the two penalty variants in §3.5."

    PRD §3.4: "`pass_through_insurance`, defaulting to false, records reliance on
    pass-through deposit insurance to the underlying customers, and
    `titling_convention` describes how the account is titled at the bank:
    `SINGLE_FIDUCIARY_ACCOUNT`, `FBO_SUBACCOUNTS` or `DIRECT_TITLED`."

    PRD §3.4: "The same rule polices the reciprocal declaration: a
    `funding_channel_claim` of `RECIPROCAL_NETWORK` requires
    `reciprocal_arrangement_cents` — the contractual reciprocal placement capacity,
    defaulting to 0 — to be strictly greater than zero."

    PRD §3.4: "Finally `rollover_enabled`, defaulting to false, decides whether a
    matured placement is automatically rolled into a successor by the sweep."

    PRD §3.4: "`offered_rate_bps` is the rate the program advertises, and
    `local_prevailing_rate_bps` is the prevailing rate in the bank's local market for
    the same bucket; the latter defaults to null, meaning the desk asserts no local
    comparison, and when it is supplied it can lift the ceiling as §3.1 describes."

    Design: Corner/entities/corner_omitted_optional_inputs_take_declared_defaults
    """
    env = fx.setup_bank(institution_overrides=_bank_baselines())

    data = validate_success(
        api_client.create_program(
            f.program_payload(env["institution"]["id"]), DESK
        ),
        expected_status=201,
    )

    assert data["principal_erosion_allowed"] is False, (
        "principal_erosion_allowed defaults to false, got "
        f"{data['principal_erosion_allowed']}"
    )
    assert data["pass_through_insurance"] is False, (
        f"pass_through_insurance defaults to false, got {data['pass_through_insurance']}"
    )
    assert data["rollover_enabled"] is False, (
        f"rollover_enabled defaults to false, got {data['rollover_enabled']}"
    )
    assert data["reciprocal_arrangement_cents"] == 0, (
        "reciprocal_arrangement_cents defaults to 0, got "
        f"{data['reciprocal_arrangement_cents']}"
    )
    assert data["local_prevailing_rate_bps"] is None, (
        "local_prevailing_rate_bps defaults to null, got "
        f"{data['local_prevailing_rate_bps']}"
    )


@pytest.mark.parametrize(
    "product_type, tenor_days, expected_bucket",
    [
        ("TIME_DEPOSIT", 30, "DAYS_1_30"),
        ("TIME_DEPOSIT", 31, "DAYS_31_90"),
        ("TIME_DEPOSIT", 200, "DAYS_181_365"),
        ("TIME_DEPOSIT", 400, "DAYS_366_PLUS"),
        ("MONEY_MARKET", 0, "NON_MATURITY"),
    ],
)
def test_program_tenor_bucket_is_derived_from_product_and_tenor(
    product_type, tenor_days, expected_bucket
):
    """The maturity bucket on a program is assigned by the system from the product
    form and the tenor, never taken from the caller.

    PRD §3.4: "From those two the system assigns `tenor_bucket`: a program whose
    `product_type` is `MONEY_MARKET`, `SAVINGS` or `NOW` is `NON_MATURITY` regardless
    of tenor, and otherwise the bucket follows `tenor_days` with inclusive upper edges
    — up to and including 30 days is `DAYS_1_30`, 31 through 90 days is `DAYS_31_90`,
    91 through 180 days is `DAYS_91_180`, 181 through 365 days is `DAYS_181_365`, and
    anything beyond 365 days is `DAYS_366_PLUS`."

    Design: Corner/entities/corner_computed_fields_derived_not_supplied
    """
    env = fx.setup_bank(institution_overrides=_bank_baselines())

    data = validate_success(
        api_client.create_program(
            f.program_payload(
                env["institution"]["id"],
                product_type=product_type,
                tenor_days=tenor_days,
            ),
            DESK,
        ),
        expected_status=201,
    )

    assert data["tenor_bucket"] == expected_bucket, (
        f"a {product_type} program of {tenor_days} days belongs in {expected_bucket}, "
        f"got {data['tenor_bucket']}"
    )
    asserts.assert_tenor_bucket_matches(product_type, tenor_days, data["tenor_bucket"])


def test_placement_maturity_date_and_bucket_are_derived_at_booking():
    """A tranche's maturity date and bucket are computed from its own inputs and the
    program's product form.

    PRD §3.5: "From those inputs the system derives `maturity_date` as `issue_date`
    advanced by `tenor_days` calendar days — equal to `issue_date` itself when the
    tenor is zero — and assigns `tenor_bucket` by the same rule the program uses,
    reading the program's `product_type` together with this tranche's `tenor_days`."

    Design: Corner/entities/corner_computed_fields_derived_not_supplied
    """
    env = fx.setup_open_core_program(institution_overrides=_bank_baselines())

    data = validate_success(
        api_client.create_placement(
            f.placement_payload(
                env["program"]["id"], issue_date="2026-08-01", tenor_days=60
            ),
            DESK,
        ),
        expected_status=201,
    )

    assert data["maturity_date"] == "2026-09-30", (
        "2026-08-01 advanced by 60 calendar days is 2026-09-30, got "
        f"{data['maturity_date']}"
    )
    assert data["tenor_bucket"] == "DAYS_31_90", (
        f"a 60-day time deposit sits in DAYS_31_90, got {data['tenor_bucket']}"
    )
    asserts.assert_calendar_date(data["maturity_date"], "maturity_date")


def test_bank_wholesale_figures_are_derived_from_live_placements():
    """The bank's deposit buckets, total and funding ratio are rolled up by the
    system rather than supplied by the caller.

    PRD §2.11: "A bank's `brokered_deposits_cents`, `listing_service_deposits_cents`
    and `reciprocal_deposits_cents` are each the sum of `principal_cents` over that
    bank's placements whose `funding_status` is exactly `ACTIVE` and whose
    `classified_as` matches the bucket — `BROKERED` for the first,
    `LISTING_SERVICE_NON_BROKERED` for the second, `RECIPROCAL_EXCLUDED` for the
    third."

    PRD §2.11: "`total_deposits_cents` is `core_deposits_cents` plus those three
    buckets."

    PRD §3.7: "The point-in-time variant is the value carried on
    `wholesale_funding_ratio_bps`: the sum of `brokered_deposits_cents` and
    `listing_service_deposits_cents`, multiplied by 10000 and divided by
    `total_deposits_cents`, discarding the remainder, and 0 when `total_deposits_cents`
    is zero."

    Design: Corner/entities/corner_computed_fields_derived_not_supplied
    """
    env = fx.setup_active_placement(
        institution_overrides=_bank_baselines(),
        placement_overrides={"principal_cents": 2_000_000_000},
    )
    bank = fx.read_institution(env["institution"]["id"])
    placement = fx.read_placement(env["placement"]["id"])

    assert placement["classified_as"] == "BROKERED", (
        "the tranche inherits the BROKERED determination of its program, got "
        f"{placement['classified_as']}"
    )
    assert bank["brokered_deposits_cents"] == 2_000_000_000, (
        "the brokered bucket must hold the live tranche's principal, got "
        f"{bank['brokered_deposits_cents']}"
    )
    assert bank["listing_service_deposits_cents"] == 0, (
        "no listing-service money is live, got "
        f"{bank['listing_service_deposits_cents']}"
    )
    assert bank["reciprocal_deposits_cents"] == 0, (
        f"no reciprocal money is live, got {bank['reciprocal_deposits_cents']}"
    )
    assert bank["total_deposits_cents"] == 32_000_000_000, (
        "total_deposits_cents is core 30,000,000,000 plus the 2,000,000,000 brokered "
        f"bucket, got {bank['total_deposits_cents']}"
    )
    assert bank["wholesale_funding_ratio_bps"] == 625, (
        "2,000,000,000 * 10000 // 32,000,000,000 is 625 basis points, got "
        f"{bank['wholesale_funding_ratio_bps']}"
    )
    asserts.assert_wholesale_buckets_match_active_placements(bank, [placement])


def test_agreement_parent_and_preparer_are_system_sourced():
    """An agreement takes its counterparty from the path and its preparer from the
    acting identity, whatever the body says.

    PRD §2.7: "For those nested creates, the parent identifier is taken from the path
    segment and never from the body, so `institution_id` on a concentration limit, a
    contingency plan and a call report filing, and `broker_id` on a broker agreement,
    are system-sourced rather than client-supplied."

    PRD §3.2: "A new agreement lands in `DRAFT` with `diligence_score` of 0,
    `rfi_round_count` of 0 and `accrued_fee_cents` of 0; the filer's identifier is
    stamped as `prepared_by_user_id`, which is the identity every later approval is
    compared against, and `reviewed_by_user_id` stays null until the first review
    action."

    Design: Corner/entities/corner_system_fields_stamped_from_path_and_headers
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    owner = fx.register_broker(legal_name="Owning Counterparty LLC")
    decoy = fx.register_broker(legal_name="Decoy Counterparty LLC")

    payload = f.agreement_payload(agreement_ref="AGR-PATH-1", broker_id=decoy["id"])
    data = validate_success(
        api_client.create_agreement(owner["id"], payload, DESK), expected_status=201
    )

    assert data["broker_id"] == owner["id"], (
        "broker_id must come from the path segment, not the body: expected "
        f"{owner['id']}, got {data['broker_id']}"
    )
    assert data["prepared_by_user_id"] == USER_IDS["desk"], (
        "prepared_by_user_id must be stamped from the acting identity, got "
        f"{data['prepared_by_user_id']}"
    )
    assert data["reviewed_by_user_id"] is None, (
        "reviewed_by_user_id stays null until the first review action, got "
        f"{data['reviewed_by_user_id']}"
    )
    assert data["diligence_score"] == 0, (
        f"a fresh draft carries a diligence_score of 0, got {data['diligence_score']}"
    )
    assert data["rfi_round_count"] == 0, (
        f"a fresh draft carries no request-for-information rounds, got {data['rfi_round_count']}"
    )
    assert data["accrued_fee_cents"] == 0, (
        f"a fresh draft has accrued no fees, got {data['accrued_fee_cents']}"
    )


def test_contingency_plan_parent_and_drafter_are_system_sourced():
    """A contingency plan takes its bank from the path and its drafter from the
    acting identity.

    PRD §2.7: "For those nested creates, the parent identifier is taken from the path
    segment and never from the body, so `institution_id` on a concentration limit, a
    contingency plan and a call report filing, and `broker_id` on a broker agreement,
    are system-sourced rather than client-supplied."

    PRD §3.7: "A new plan lands in `DRAFT` with `activation_stage` of `NONE`,
    `required_buffer_cents` and `buffer_shortfall_cents` at 0, `prepared_by_user_id`
    stamped from the drafting controller and `approved_by_user_id` null."

    Design: Corner/entities/corner_system_fields_stamped_from_path_and_headers
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    owner = fx.register_institution(cert_id="CERT-9006", **_bank_baselines())
    decoy = fx.register_institution(cert_id="CERT-9007", **_bank_baselines())

    payload = f.contingency_plan_payload(
        plan_version_label="CFP-PATH-1", institution_id=decoy["id"]
    )
    data = validate_success(
        api_client.create_contingency_plan(owner["id"], payload, TREASURY),
        expected_status=201,
    )

    assert data["institution_id"] == owner["id"], (
        "institution_id must come from the path segment, not the body: expected "
        f"{owner['id']}, got {data['institution_id']}"
    )
    assert data["prepared_by_user_id"] == USER_IDS["treasury"], (
        "prepared_by_user_id must be stamped from the drafting controller, got "
        f"{data['prepared_by_user_id']}"
    )
    assert data["approved_by_user_id"] is None, (
        f"approved_by_user_id starts null, got {data['approved_by_user_id']}"
    )
    assert data["activation_stage"] == "NONE", (
        f"a new plan carries an activation_stage of NONE, got {data['activation_stage']}"
    )
    assert data["required_buffer_cents"] == 0, (
        f"required_buffer_cents starts at 0, got {data['required_buffer_cents']}"
    )
    assert data["buffer_shortfall_cents"] == 0, (
        f"buffer_shortfall_cents starts at 0, got {data['buffer_shortfall_cents']}"
    )


@pytest.mark.parametrize(
    "case",
    [
        "undeclared_enum_member",
        "negative_cents",
        "non_integer_cents",
        "subscore_above_100",
        "malformed_calendar_date",
        "malformed_report_period",
    ],
)
def test_type_and_range_violations_rejected(case):
    """Wrong-typed, out-of-range and mis-formatted inputs are all invalid requests.

    PRD §2.8: "Request shape: every input field that has no declared default is
    present, every enum-typed field carries a declared member, integer fields are
    integers, `_cents` and `_bps` fields are not negative, diligence sub-scores lie
    within 0 to 100 inclusive, calendar-date fields are formatted as year-month-day
    and instant fields are ISO 8601 UTC — `ERR_INVALID_REQUEST`. All write
    endpoints."

    PRD §3.9: "A filing is opened for one reporting period, identified by a
    `report_period` label of four digits followed by the letter Q and a quarter number
    1 through 4 — `2026Q3` is well formed, and anything else is refused as an invalid
    request."

    Design: Corner/entities/corner_type_and_range_violations_rejected
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)

    if case == "undeclared_enum_member":
        response = api_client.create_institution(
            f.institution_payload(
                cert_id="CERT-9008",
                capital_category="SUPER_CAPITALIZED",
                **_bank_baselines(),
            ),
            ADMIN,
        )
    elif case == "negative_cents":
        response = api_client.create_institution(
            f.institution_payload(
                cert_id="CERT-9009", **_bank_baselines(core_deposits_cents=-1)
            ),
            ADMIN,
        )
    elif case == "non_integer_cents":
        env = fx.setup_open_core_program(institution_overrides=_bank_baselines())
        response = api_client.create_placement(
            f.placement_payload(env["program"]["id"], principal_cents="2000000000"),
            DESK,
        )
    elif case == "subscore_above_100":
        broker = fx.register_broker()
        response = api_client.create_agreement(
            broker["id"], f.agreement_payload(aml_program_score=101), DESK
        )
    elif case == "malformed_calendar_date":
        response = api_client.publish_national_rate_cap(
            f.national_rate_cap_payload(effective_date="07/01/2026"), ADMIN
        )
    else:
        bank = fx.register_institution(cert_id="CERT-9010", **_bank_baselines())
        response = api_client.create_call_report_filing(
            bank["id"], f.call_report_filing_payload(report_period="2026-Q3"), DESK
        )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_append_only_records_carry_no_version_or_update_timestamp():
    """The three ledger record types expose only an id and a creation timestamp.

    PRD §2.5: "Three record types are append-only ledger entries and deliberately
    carry neither `updated_at` nor `version`: a published national rate benchmark, a
    classification determination and a rate-cap check."

    PRD §2.5: "For those three, only `id` and `created_at` are present."

    Design: Corner/entities/corner_immutable_entities_expose_no_version_or_update_path
    """
    env = fx.setup_active_placement(institution_overrides=_bank_baselines())
    check = fx.record_rate_cap_check(
        env["placement"]["id"], "2026-08-01", COMPLIANCE
    )

    for label, record in (
        ("published national rate benchmark", env["benchmark"]),
        ("classification determination", env["classification"]),
        ("rate-cap check", check),
    ):
        asserts.assert_append_only_fields(record, label)
        assert "updated_at" not in record, (
            f"an append-only {label} must not carry updated_at"
        )
        assert "version" not in record, (
            f"an append-only {label} must not carry version"
        )
        assert is_valid_uuid(record["id"]), f"an append-only {label} carries an id"
        assert is_iso8601_timestamp(record["created_at"]), (
            f"an append-only {label} carries created_at"
        )


def test_benchmark_correction_is_a_new_publication_not_an_edit():
    """A benchmark is corrected by appending a later publication; the earlier row is
    left exactly as published and the same effective date cannot be reused.

    PRD §3.1: "A publication governs the half-open interval that begins on its own
    `effective_date` and ends the day the next publication for the same bucket becomes
    effective, and the pair of `tenor_bucket` and `effective_date` must be unique
    across all publications — a duplicate is refused with `ERR_DUPLICATE_KEY`."

    PRD §3.1: "Publications are immutable; a correction is a new publication with a
    later effective date."

    Design: Corner/entities/corner_immutable_entities_expose_no_version_or_update_path
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    first = validate_success(
        api_client.publish_national_rate_cap(
            f.national_rate_cap_payload(
                tenor_bucket="DAYS_31_90",
                published_national_rate_bps=400,
                effective_date="2026-07-01",
            ),
            ADMIN,
        ),
        expected_status=201,
    )

    validate_error(
        api_client.publish_national_rate_cap(
            f.national_rate_cap_payload(
                tenor_bucket="DAYS_31_90",
                published_national_rate_bps=450,
                effective_date="2026-07-01",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value,
    )

    correction = validate_success(
        api_client.publish_national_rate_cap(
            f.national_rate_cap_payload(
                tenor_bucket="DAYS_31_90",
                published_national_rate_bps=450,
                effective_date="2026-07-15",
            ),
            ADMIN,
        ),
        expected_status=201,
    )
    assert correction["id"] != first["id"], (
        "a correction must be a separate publication row"
    )
    assert correction["cap_bps"] == 525, (
        f"the corrected ceiling is 450 + 75 basis points, got {correction['cap_bps']}"
    )

    rows, meta = validate_paginated(api_client.list_national_rate_caps(ADMIN))
    assert meta["total_count"] == 2, (
        f"both publications must survive, got {meta['total_count']}"
    )
    original = next(row for row in rows if row["id"] == first["id"])
    assert original["published_national_rate_bps"] == 400, (
        "the earlier publication must keep its published rate, got "
        f"{original['published_national_rate_bps']}"
    )
    assert original["cap_bps"] == 475, (
        f"the earlier ceiling stays 400 + 75 basis points, got {original['cap_bps']}"
    )


def test_child_creation_under_an_absent_parent_is_refused_by_the_parent_code():
    """A nested create resolves its path parent first and answers with that parent's
    own not-found code.

    PRD §2.7: "Where a path carries a parent segment, that parent is resolved left to
    right before anything nested is considered: an unknown bank in the path yields
    `ERR_INSTITUTION_NOT_FOUND` and an unknown counterparty yields
    `ERR_BROKER_NOT_FOUND`, in both cases without the nested payload ever being
    validated."

    Design: Corner/entities/corner_child_creation_scoped_to_path_parent
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)

    validate_error(
        api_client.create_agreement(
            NON_EXISTENT_UUID, f.agreement_payload(agreement_ref="AGR-ORPHAN-1"), DESK
        ),
        ApiErrorId.ERR_BROKER_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_concentration_limit(
            NON_EXISTENT_UUID, f.concentration_limit_payload(), TREASURY
        ),
        ApiErrorId.ERR_INSTITUTION_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_contingency_plan(
            NON_EXISTENT_UUID, f.contingency_plan_payload(), TREASURY
        ),
        ApiErrorId.ERR_INSTITUTION_NOT_FOUND.value,
    )
    validate_error(
        api_client.create_call_report_filing(
            NON_EXISTENT_UUID, f.call_report_filing_payload(), DESK
        ),
        ApiErrorId.ERR_INSTITUTION_NOT_FOUND.value,
    )


def test_child_collections_are_scoped_to_their_path_parent():
    """Each nested collection lists only the children of the addressed parent.

    PRD §2.7: "Several collections are addressed underneath a parent — a bank's
    concentration limits, contingency plans and call report filings, and a
    counterparty's agreements — while the rest are flat top-level collections whose
    relationships travel in the request body or query string."

    Design: Corner/entities/corner_child_creation_scoped_to_path_parent
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker_a = fx.register_broker(legal_name="Counterparty A LLC")
    broker_b = fx.register_broker(legal_name="Counterparty B LLC")
    agreement_a = fx.draft_agreement(broker_a["id"], DESK, agreement_ref="AGR-A-1")
    agreement_b = fx.draft_agreement(broker_b["id"], DESK, agreement_ref="AGR-B-1")

    rows_a, meta_a = validate_paginated(
        api_client.list_broker_agreements(broker_a["id"], DESK)
    )
    assert meta_a["total_count"] == 1, (
        f"counterparty A owns exactly one agreement, got {meta_a['total_count']}"
    )
    assert [row["id"] for row in rows_a] == [agreement_a["id"]], (
        "counterparty A's collection must not leak counterparty B's agreement"
    )

    rows_b, meta_b = validate_paginated(
        api_client.list_broker_agreements(broker_b["id"], DESK)
    )
    assert meta_b["total_count"] == 1, (
        f"counterparty B owns exactly one agreement, got {meta_b['total_count']}"
    )
    assert [row["id"] for row in rows_b] == [agreement_b["id"]], (
        "counterparty B's collection must hold only its own agreement"
    )

    bank_a = fx.register_institution(cert_id="CERT-9011", **_bank_baselines())
    bank_b = fx.register_institution(cert_id="CERT-9012", **_bank_baselines())
    plan_a = fx.draft_contingency_plan(bank_a["id"], TREASURY, plan_version_label="CFP-A")
    fx.draft_contingency_plan(bank_b["id"], TREASURY, plan_version_label="CFP-B")

    plans_a, plans_meta = validate_paginated(
        api_client.list_contingency_plans(bank_a["id"], TREASURY)
    )
    assert plans_meta["total_count"] == 1, (
        f"bank A owns exactly one plan, got {plans_meta['total_count']}"
    )
    assert [row["id"] for row in plans_a] == [plan_a["id"]], (
        "bank A's plan collection must not leak bank B's plan"
    )


def test_agreement_reference_uniqueness_is_scoped_to_one_counterparty():
    """The counterparty-assigned reference collides only inside its own
    counterparty.

    PRD §3.2: "A filing supplies the counterparty-assigned `agreement_ref`, which
    must be unique within that one counterparty — a repeat is refused with
    `ERR_DUPLICATE_KEY`"

    Design: Corner/entities/corner_child_creation_scoped_to_path_parent
    """
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker_a = fx.register_broker(legal_name="Counterparty A LLC")
    broker_b = fx.register_broker(legal_name="Counterparty B LLC")

    validate_success(
        api_client.create_agreement(
            broker_a["id"], f.agreement_payload(agreement_ref="AGR-SHARED"), DESK
        ),
        expected_status=201,
    )
    validate_error(
        api_client.create_agreement(
            broker_a["id"], f.agreement_payload(agreement_ref="AGR-SHARED"), DESK
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value,
    )

    twin = validate_success(
        api_client.create_agreement(
            broker_b["id"], f.agreement_payload(agreement_ref="AGR-SHARED"), DESK
        ),
        expected_status=201,
    )
    assert twin["broker_id"] == broker_b["id"], (
        "the same reference under a different counterparty is a legitimate agreement"
    )
    assert twin["agreement_ref"] == "AGR-SHARED", (
        f"agreement_ref must be stored as supplied, got {twin['agreement_ref']}"
    )


def test_program_and_determination_junction_navigates_in_both_directions():
    """A determined program points at its governing determination and the
    determination points back at the program.

    PRD §3.4: "Applying a determination moves the program from
    `PENDING_CLASSIFICATION` (or from `RECLASSIFICATION_PENDING`) to `CLASSIFIED`,
    sets `governing_classification_id` to the new determination's `id`, increments the
    program's `version` by 1, and re-derives `effective_cap_bps`."

    PRD §3.4: "Determinations are listable and can be narrowed by `program_id`,
    `relied_exception_id` and `determined_class`."

    Design: Corner/entities/corner_graph_topology_cross_aggregate_navigation
    """
    env = fx.setup_open_program(institution_overrides=_bank_baselines())
    program = fx.read_program(env["program"]["id"])
    determination = fx.read_classification(env["classification"]["id"], EXAMINER)

    assert program["governing_classification_id"] == determination["id"], (
        "the program must name the determination that governs it, got "
        f"{program['governing_classification_id']}"
    )
    assert determination["program_id"] == program["id"], (
        "the determination must name the program it was made against, got "
        f"{determination['program_id']}"
    )
    assert program["institution_id"] == env["institution"]["id"], (
        "the program must remain attached to its bank"
    )
    assert program["broker_id"] == env["broker"]["id"], (
        "the program must remain attached to its counterparty"
    )
    assert program["agreement_id"] == env["agreement"]["id"], (
        "the program must remain attached to the agreement underwriting it"
    )

    rows, meta = validate_paginated(
        api_client.list_classifications(EXAMINER, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 1, (
        "one determination exists for this program, got "
        f"{meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [determination["id"]], (
        "narrowing determinations by program_id must return this program's own"
    )


def test_exception_reliance_count_follows_the_determination_junction():
    """Reliance is counted through the determination that names the filing.

    PRD §2.11: "A second conserved quantity governs exception reliance:
    `reliant_program_count` on an exception filing equals the number of programs whose
    `governing_classification_id` names a determination whose `relied_exception_id` is
    that filing, so a classification relying on a filing followed by a reclassification
    that does not rely on it must return the count to its exact prior value."

    PRD §3.4: "Each determined class maps one-to-one onto the call report line recorded
    as `call_report_line`: `BROKERED` maps to `RC_E_M1_BROKERED`,
    `LISTING_SERVICE_NON_BROKERED` to `RC_E_M2_LISTING`, `CORE` to `RC_E_CORE` and
    `RECIPROCAL_EXCLUDED` to `RC_O_M_RECIPROCAL`."

    Design: Corner/entities/corner_graph_topology_cross_aggregate_navigation
    """
    env = fx.setup_program_relying_on_exception(institution_overrides=_bank_baselines())
    determination = fx.read_classification(env["classification"]["id"])
    exception = fx.read_exception(env["exception"]["id"])
    program = fx.read_program(env["program"]["id"])

    assert determination["relied_exception_id"] == exception["id"], (
        "the determination must name the filing it leaned on, got "
        f"{determination['relied_exception_id']}"
    )
    assert determination["determined_class"] == "LISTING_SERVICE_NON_BROKERED", (
        "reliance carries the program out of the brokered class, got "
        f"{determination['determined_class']}"
    )
    assert determination["call_report_line"] == "RC_E_M2_LISTING", (
        "LISTING_SERVICE_NON_BROKERED maps to RC_E_M2_LISTING, got "
        f"{determination['call_report_line']}"
    )
    asserts.assert_call_report_line_mapping(
        determination["determined_class"], determination["call_report_line"]
    )
    assert program["governing_classification_id"] == determination["id"], (
        "the relying determination must be the governing one"
    )
    assert exception["reliant_program_count"] == 1, (
        "exactly one program's governing determination leans on this filing, got "
        f"{exception['reliant_program_count']}"
    )

    rows, meta = validate_paginated(
        api_client.list_classifications(
            COMPLIANCE, params={"relied_exception_id": exception["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "one determination names this filing, got "
        f"{meta['total_count']}"
    )
    assert [row["id"] for row in rows] == [determination["id"]], (
        "narrowing determinations by relied_exception_id must return the relying one"
    )
