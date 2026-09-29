"""Portfolio foundations: the homeowner registry, the tariff book, booking a deal.

These tests exercise the creation, read, listing and payload-validation contract
that every collection in the servicing API shares.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.assertions import (
    assert_credit_counters,
    assert_identity_fields,
    assert_meta_envelope,
    assert_no_version_fields,
    assert_state_dimensions,
    assert_versioned_entity,
)
from test_helpers.fixtures import (
    activate,
    book_ppa,
    make_homeowner,
    make_successor_tariff,
    make_tariff,
    set_clock,
)

UNKNOWN_ID = "00000000-0000-4000-8000-000000000009"


def test_booking_a_lease_returns_201_with_a_derived_contract_end_date(api):
    """A booked lease echoes its terms and derives its own end date.

    §3.1 pins the derivation: "Its `contract_end_date` is derived as the
    `contract_start_date` advanced by `term_years` years and then pulled back by
    one day". §3.1 also pins the opening posture: "Its `lifecycle_state` is
    `DRAFT`, its `monitoring_status` is `MONITORING_OK` and its `service_status`
    is `IN_SERVICE`", with "`renewal_count`, `open_outage_count` and
    `excused_downtime_minutes` all begin at 0, as do the three credit counters".

    Design: Corner/entities/create_lease_agreement_returns_201_with_computed_contract_end_date
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)

    response = api.create_agreement(
        F.lease_agreement_payload(
            owner["id"],
            schedule["id"],
            site_address="77 Bayside Rd, Alameda CA",
            term_years=20,
            contract_start_date="2025-01-01",
            escalator_pct=0.019,
            guaranteed_annual_kwh=8400,
            system_dc_kw=6.4,
            guarantee_band_pct=0.05,
            base_monthly_lease_cents=12900,
        ),
        U.agent_headers(),
    )

    agreement = validate_success(response, 201)
    assert_meta_envelope(response.json())
    assert response.json()["response_type"] == "object"
    assert_versioned_entity(agreement, expected_version=1)

    assert agreement["product_type"] == C.PRODUCT_LEASE
    assert agreement["base_monthly_lease_cents"] == 12900
    assert agreement["base_ppa_rate_per_kwh_millicents"] is None
    assert agreement["contract_end_date"] == "2044-12-31"

    assert_state_dimensions(
        agreement,
        lifecycle_state=C.LIFECYCLE_DRAFT,
        monitoring_status=C.MONITORING_OK,
        service_status=C.SERVICE_IN_SERVICE,
    )
    assert_credit_counters(agreement, earned=0, applied=0, balance=0)
    assert agreement["renewal_count"] == 0
    assert agreement["open_outage_count"] == 0
    assert agreement["excused_downtime_minutes"] == 0


def test_reading_a_homeowner_returns_the_stored_registration(api):
    """The registry stores the six declared fields and does not re-round the ratio.

    §3.1 lists them: "their legal `full_name` ..., an `email` ..., a `state_code`
    ..., a `fico_score` between 300 and 850 inclusive, a `dti_ratio` expressed as
    a fraction of gross income between 0.0000 and 1.0000 with at most four
    decimal places, and a verified `monthly_income_cents`".

    Design: Corner/entities/get_homeowner_returns_the_stored_record
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    payload = F.homeowner_payload()
    created = validate_success(
        api.create_homeowner(payload, U.admin_headers()), 201
    )

    # The read is authorised for the CreditUnderwriter who has to score a buyer.
    stored = validate_success(
        api.get_homeowner(created["id"], U.underwriter_headers()), 200
    )

    assert stored["full_name"] == payload["full_name"]
    assert stored["email"] == payload["email"]
    assert stored["state_code"] == "CA"
    assert stored["fico_score"] == 742
    assert stored["dti_ratio"] == pytest.approx(0.28)
    assert stored["monthly_income_cents"] == 1150000
    assert_versioned_entity(stored, expected_version=1)


def test_agreement_pages_report_total_count_and_has_more(api):
    """Two pages over three rows report an honest total and an honest has_more.

    §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside `meta`, where `total_count` is the number of rows matching the filters
    before pagination is applied and `has_more` is true when rows remain beyond the
    current page."

    Design: Corner/entities/list_agreements_paginates_with_total_count_and_has_more
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    for street in ("1 Oak St, Fremont CA", "2 Oak St, Fremont CA", "3 Oak St, Fremont CA"):
        book_ppa(api, owner["id"], schedule["id"], site_address=street)

    first_rows, first_meta = validate_paginated(
        api.list_agreements(
            U.admin_headers(),
            {"homeowner_id": owner["id"], "limit": 2, "offset": 0},
        )
    )
    second_rows, second_meta = validate_paginated(
        api.list_agreements(
            U.admin_headers(),
            {"homeowner_id": owner["id"], "limit": 2, "offset": 2},
        )
    )

    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    assert len(second_rows) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2

    ids = [row["id"] for row in first_rows + second_rows]
    assert len(set(ids)) == 3


def test_metered_month_status_filter_narrows_the_collection(api):
    """A status filter is applied to the collection, not to the page.

    §2.3: "Each collection accepts the foreign keys and classifying enumerations it
    carries as optional filters, and filters combine conjunctively." §2.3: "Metered
    months accept `agreement_id`, `contract_year`, `period_year`, `period_month` and
    `status`."

    Design: Corner/entities/list_production_periods_filtered_by_status_excludes_other_rows
    """
    set_clock(api, "2026-07-10T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(api, owner["id"], schedule["id"])
    activate(api, agreement["id"])

    left_recorded = validate_success(
        api.create_period(
            F.period_payload(agreement["id"], 2026, 5, 1000), U.agent_headers()
        ),
        201,
    )
    settled = validate_success(
        api.create_period(
            F.period_payload(
                agreement["id"],
                2026,
                6,
                1100,
                auto_reconcile=True,
                auto_issue_credit=False,
            ),
            U.agent_headers(),
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_periods(
            U.agent_headers(),
            {"agreement_id": agreement["id"], "status": C.PERIOD_RECONCILED},
        )
    )

    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [settled["id"]]

    # The month recorded without the convenience flag is still only RECORDED.
    unsettled = validate_success(
        api.get_period(left_recorded["id"], U.agent_headers()), 200
    )
    assert unsettled["status"] == C.PERIOD_RECORDED


def test_limit_above_one_hundred_is_rejected_not_clamped(api):
    """§2.3 declares the range, and rung 3 rejects a value outside it.

    §2.3: "`limit` defaults to 10, may not be lower than 1 and may not exceed 100;
    `offset` defaults to 0 and may not be negative. A `limit` outside 1 through 100,
    or a negative `offset`, is a malformed request and is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/list_with_limit_above_one_hundred_returns_invalid_request
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    make_homeowner(api)

    response = api.list_homeowners(U.admin_headers(), {"limit": 101})

    validate_error(response, E.ERR_INVALID_REQUEST)
    assert response.json()["response_type"] == "error"
    assert "data" in response.json()


def test_unknown_agreement_id_returns_the_agreement_not_found_code(api):
    """Rung 4 answers with "the not-found code of the collection named by the path segment".

    Design: Corner/entities/get_agreement_with_unknown_id_returns_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    response = api.get_agreement(UNKNOWN_ID, U.admin_headers())

    validate_error(response, E.ERR_AGREEMENT_NOT_FOUND)


def test_booking_without_the_annual_guarantee_is_rejected_and_persists_nothing(api):
    """A required input with no default may not be inferred from another field.

    §3.1 requires "a `guaranteed_annual_kwh` that must be strictly positive", and
    §2.10 rung 3 covers "a required input field that is missing or null".

    Design: Corner/entities/create_agreement_missing_required_guaranteed_annual_kwh_returns_invalid_request
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)

    payload = F.ppa_agreement_payload(owner["id"], schedule["id"])
    del payload["guaranteed_annual_kwh"]

    validate_error(
        api.create_agreement(payload, U.agent_headers()), E.ERR_INVALID_REQUEST
    )

    _, meta = validate_paginated(
        api.list_agreements(U.admin_headers(), {"homeowner_id": owner["id"]})
    )
    assert meta["total_count"] == 0


def test_omitted_guarantee_band_defaults_to_five_percent_and_moves_the_floor(api):
    """The default is observable in the floor a month is measured against.

    §3.1 gives the default: "an optional `guarantee_band_pct` between 0.0000 and
    0.2000 with at most four decimal places that defaults to 0.05 when omitted".
    §3.3 turns it into a number: "`guarantee_floor_kwh` is
    `adjusted_expected_kwh` multiplied by one minus `guarantee_band_pct`, rounded
    to a whole kilowatt-hour".

    Design: Corner/entities/omitted_guarantee_band_pct_defaults_to_five_percent
    """
    set_clock(api, "2026-07-10T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    payload = F.ppa_agreement_payload(owner["id"], schedule["id"])
    payload.pop("guarantee_band_pct", None)
    agreement = validate_success(
        api.create_agreement(payload, U.agent_headers()), 201
    )
    agreement = activate(api, agreement["id"])

    assert agreement["guarantee_band_pct"] == pytest.approx(0.05)

    month = validate_success(
        api.create_period(
            F.period_payload(
                agreement["id"],
                2026,
                6,
                1050,
                auto_reconcile=True,
                auto_issue_credit=True,
            ),
            U.agent_headers(),
        ),
        201,
    )

    assert month["gross_expected_kwh"] == 1075
    assert month["adjusted_expected_kwh"] == 1075
    assert month["guarantee_floor_kwh"] == 1021
    assert month["shortfall_kwh"] == 0
    assert month["credit_cents"] == 0
    assert month["status"] == C.PERIOD_RECONCILED


def test_omitted_grandfathering_flag_defaults_to_false(api):
    """A schedule published without the flag cannot grandfather anybody.

    §3.1: "an optional `grandfathers_predecessors` flag that defaults to false".
    §3.2 then requires it: "`tariff_grandfathered` is true only when the
    currently attached tariff has `grandfathers_predecessors` set to true".

    Design: Corner/entities/omitted_grandfathers_predecessors_defaults_to_false
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    legacy = make_tariff(api)
    successor_payload = F.successor_tariff_payload(
        tariff_code="NEM3-NOGF", effective_from_date="2026-04-15"
    )
    successor_payload.pop("grandfathers_predecessors")
    successor = validate_success(
        api.create_tariff(successor_payload, U.admin_headers()), 201
    )

    agreement = book_ppa(api, owner["id"], legacy["id"])
    activate(api, agreement["id"])

    stored_successor = validate_success(
        api.get_tariff(successor["id"], U.admin_headers()), 200
    )
    assert stored_successor["grandfathers_predecessors"] is False

    moved = validate_success(
        api.apply_tariff(
            agreement["id"], {"tariff_id": successor["id"]}, U.admin_headers()
        ),
        200,
    )
    assert moved["tariff_id"] == successor["id"]
    assert moved["tariff_grandfathered"] is False


def test_recording_a_month_derives_its_dates_and_moves_no_money(api):
    """Recording alone derives dates and expectation; it settles nothing.

    §3.3: "Recording alone derives the month's `contract_year`, its `due_date`,
    its `gross_expected_kwh`, its `excused_days` and its
    `adjusted_expected_kwh`", and "The `due_date` is the last calendar day of the
    period month advanced by twenty-one days."

    Design: Corner/entities/production_period_creation_computes_contract_year_and_due_date_only
    """
    set_clock(api, "2026-07-10T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(api, owner["id"], schedule["id"])
    activate(api, agreement["id"])

    month = validate_success(
        api.create_period(
            F.period_payload(agreement["id"], 2026, 6, 950), U.agent_headers()
        ),
        201,
    )

    assert month["contract_year"] == 2
    assert month["due_date"] == "2026-07-21"
    assert month["gross_expected_kwh"] == 1075
    assert month["excused_days"] == 0
    assert month["adjusted_expected_kwh"] == 1075
    assert month["status"] == C.PERIOD_RECORDED
    assert month["gross_due_cents"] == 0
    assert month["credit_cents"] == 0
    assert month["credit_applied_cents"] == 0
    assert month["net_due_cents"] == 0
    assert month["late_fee_cents"] == 0
    assert month["total_invoiced_cents"] == 0

    parent = validate_success(api.get_agreement(agreement["id"], U.agent_headers()), 200)
    assert_credit_counters(parent, earned=0, applied=0, balance=0)


def test_server_owned_agreement_fields_ignore_client_supplied_values(api):
    """§2.4 mints the identity server-side and §3.1 fixes the opening state.

    §2.4: "Each stored resource is addressed by an `id`, which is a server-minted
    UUID carrying no type prefix; clients never supply it." §3.1:
    "Its `relocated_from_agreement_id` is null, because only a successor
    agreement minted by a relocation closing ever carries a predecessor."

    Design: Corner/entities/agreement_system_fields_are_server_owned_and_client_extra_field_input_ignored
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)

    forged_id = "00000000-0000-4000-8000-0000000000ff"
    forged_predecessor = "00000000-0000-4000-8000-0000000000fe"
    response = api.create_agreement(
        F.ppa_agreement_payload(
            owner["id"],
            schedule["id"],
            id=forged_id,
            version=99,
            lifecycle_state=C.LIFECYCLE_ACTIVE,
            relocated_from_agreement_id=forged_predecessor,
            credit_balance_cents=500000,
        ),
        U.agent_headers(),
    )

    if response.status_code == 201:
        agreement = validate_success(response, 201)
        assert agreement["id"] != forged_id
        assert agreement["version"] == 1
        assert agreement["lifecycle_state"] == C.LIFECYCLE_DRAFT
        assert agreement["relocated_from_agreement_id"] is None
        assert agreement["credit_balance_cents"] == 0
        assert_identity_fields(agreement)
    else:
        # §2.10 rung 3 also covers "a field supplied by the client that the
        # endpoint computes or the system owns".
        validate_error(response, E.ERR_INVALID_REQUEST)


def test_unknown_product_type_is_rejected_not_coerced(api):
    """§3.1 closes the enum: "a `product_type` of either `LEASE` or `PPA`".

    §2.10 rung 3 covers "an enumeration value outside its declared set".

    Design: Corner/entities/create_agreement_with_invalid_enum_product_type_returns_invalid_request
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)

    validate_error(
        api.create_agreement(
            F.ppa_agreement_payload(
                owner["id"], schedule["id"], product_type="SUBSCRIPTION"
            ),
            U.agent_headers(),
        ),
        E.ERR_INVALID_REQUEST,
    )

    _, meta = validate_paginated(
        api.list_agreements(U.admin_headers(), {"homeowner_id": owner["id"]})
    )
    assert meta["total_count"] == 0


def test_published_tariff_carries_no_version_and_no_updated_at(api):
    """§2.4 exempts the tariff, and §3.1 makes it immutable once published.

    §2.4: "The one exception is the utility tariff: a published tariff is
    configuration, not state, and it carries only `id` and `created_at` — it has
    neither `updated_at` nor `version`, because no endpoint exists to update or delete
    it." §3.1: "A schedule
    is immutable once published — there is no way to edit or delete it".

    Design: Corner/entities/utility_tariff_is_immutable_with_no_version_field
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    published = make_tariff(api)

    stored = validate_success(api.get_tariff(published["id"], U.agent_headers()), 200)

    assert_no_version_fields(stored)
    assert_identity_fields(stored)
    assert stored["retail_rate_per_kwh_millicents"] == 32500
    assert stored["export_credit_rate_per_kwh_millicents"] == 28000
    assert stored["effective_from_date"] == "2020-04-15"
    assert stored["generation"] == C.GEN_NEM_2


def test_month_naming_an_unknown_agreement_returns_agreement_not_found(api):
    """Rung 5 resolves the body reference before any later rule can fire.

    §2.10 rung 5: "HTTP 404 with the not-found code of the collection named by the
    unresolvable foreign key in the body".

    Design: Corner/entities/production_period_with_unknown_agreement_id_returns_not_found
    """
    set_clock(api, "2026-07-10T00:00:00Z")

    validate_error(
        api.create_period(
            F.period_payload("00000000-0000-4000-8000-00000000000a", 2026, 6, 950),
            U.agent_headers(),
        ),
        E.ERR_AGREEMENT_NOT_FOUND,
    )


def test_unknown_buyer_reference_returns_homeowner_not_found(api):
    """The buyer reference is resolved on its own collection, not the agreement's.

    §2.10 rung 5 resolves body references "in the endpoint's declared input
    order", and §3.8 declares `ASSUMPTION` as requiring "`buyer_homeowner_id`,
    the purchasing homeowner".

    Design: Corner/entities/transfer_case_with_unknown_buyer_homeowner_id_returns_not_found
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    owner = make_homeowner(api)
    schedule = make_tariff(api)
    agreement = book_ppa(api, owner["id"], schedule["id"])
    activate(api, agreement["id"])

    validate_error(
        api.create_transfer_case(
            F.assumption_payload(
                agreement["id"],
                "2026-09-15",
                "00000000-0000-4000-8000-00000000000b",
            ),
            U.agent_headers(),
        ),
        E.ERR_HOMEOWNER_NOT_FOUND,
    )

    _, meta = validate_paginated(
        api.list_transfer_cases(U.agent_headers(), {"agreement_id": agreement["id"]})
    )
    assert meta["total_count"] == 0

    still_active = validate_success(
        api.get_agreement(agreement["id"], U.agent_headers()), 200
    )
    assert still_active["lifecycle_state"] == C.LIFECYCLE_ACTIVE


def test_tariff_filters_narrow_the_same_collection(api):
    """§2.3 declares the tariff filters, and the envelope is computed from the rows.

    §2.3: "Utility tariffs accept `utility_code` and `generation`." §2.3: "List
    responses carry `limit`, `offset`, `total_count` and `has_more` inside `meta`,
    where `total_count` is the number of rows matching the filters before pagination is
    applied".

    Design: Corner/entities/every_declared_collection_endpoint_answers_with_the_same_pagination_envelope
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    legacy = make_tariff(api, tariff_code="NEM2-ETOUC")
    successor = make_successor_tariff(
        api,
        tariff_code="NEM3-NOGF",
        grandfathers_predecessors=False,
        effective_from_date="2026-01-01",
    )

    both, both_meta = validate_paginated(
        api.list_tariffs(U.admin_headers(), {"utility_code": "PGE"})
    )
    assert both_meta["total_count"] == 2
    assert both_meta["has_more"] is False
    assert both_meta["limit"] == C.DEFAULT_LIMIT
    assert both_meta["offset"] == 0
    assert {row["id"] for row in both} == {legacy["id"], successor["id"]}

    narrowed, narrowed_meta = validate_paginated(
        api.list_tariffs(U.admin_headers(), {"generation": C.GEN_NEM_3})
    )
    assert narrowed_meta["total_count"] == 1
    assert [row["id"] for row in narrowed] == [successor["id"]]

    first_page, first_meta = validate_paginated(
        api.list_tariffs(U.admin_headers(), {"limit": 1, "offset": 0})
    )
    assert len(first_page) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["has_more"] is True


EMPTY_COLLECTION_QUERIES = [
    ("guarantee-true-ups", {"contract_year": 2, "method": C.METHOD_ANNUAL_TRUE_UP}),
    (
        "outage-events",
        {
            "outage_type": C.OUTAGE_TYPE_INVERTER_FAULT,
            "severity": C.SEVERITY_HIGH,
            "excused": "false",
        },
    ),
    (
        "truck-rolls",
        {
            "technician_code": "TECH-014",
            "billable_to": C.BILLABLE_WARRANTY,
            "root_cause": C.CAUSE_MODULE_DEFECT,
        },
    ),
    ("roof-work-orders", {"status": C.ROOF_APPROVED, "contract_year": 2}),
    ("transfer-cases", {"transfer_type": C.TYPE_PREPAYMENT, "status": C.TRANSFER_CLOSED}),
    (
        "ucc-filings",
        {"jurisdiction_code": "CA-ALAMEDA", "filing_type": C.FILING_TYPE_FIXTURE},
    ),
    (
        "end-of-term-elections",
        {"election_type": C.ELECTION_RENEW, "status": C.ELECTION_SUBMITTED},
    ),
    (
        "warranty-claims",
        {
            "component_type": C.COMPONENT_MODULE,
            "manufacturer_code": "QCELLS",
            "status": C.CLAIM_APPROVED,
        },
    ),
]


@pytest.mark.parametrize("collection,filters", EMPTY_COLLECTION_QUERIES)
def test_empty_collections_answer_with_an_honest_page(api, collection, filters):
    """An empty collection is an empty page, never a 404, and accepts its filters.

    §2.2: "The `data` field contains the resource object or an array of resource
    objects." §2.3: "Each collection accepts the foreign keys and classifying
    enumerations it carries as optional filters, and filters combine conjunctively."

    Design: Corner/entities/every_declared_collection_endpoint_answers_with_the_same_pagination_envelope
    """
    set_clock(api, "2026-08-01T00:00:00Z")

    response = api.get(f"{C.PREFIX}/{collection}", U.admin_headers(), filters)

    rows, meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == C.DEFAULT_LIMIT
    assert meta["offset"] == 0
