"""Entity contracts: creation, retrieval, listing, defaults and reference integrity.

Every test builds its own registry from scratch — the harness restarts the API
server and empties the database before each test — and pins the logical
compliance clock of PRD §2.5 before writing anything, so every stamped instant
in the assertions below is deterministic.
"""

import re

import pytest

from test_helpers import (
    COMPLIANCE_OFFICER,
    REGISTRY_ADMIN,
    T_ENROLL,
    USDOT_NUMBER_PATTERN,
    ApiErrorId,
    assert_authority_application,
    assert_carrier,
    assert_instant_format,
    assert_process_agent,
    create_carrier,
    create_draft_application,
    create_process_agent,
    factories,
    make_carrier_headers,
    raw_body,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# Ids no row in this system ever carries.
UNKNOWN_CARRIER_ID = "00000000-0000-4000-8000-000000000999"
UNKNOWN_AUTHORITY_ID = "00000000-0000-4000-8000-000000000777"
UNKNOWN_PREDECESSOR_ID = "00000000-0000-4000-8000-000000000888"


def test_carrier_enrollment_returns_201_with_the_full_opening_posture(api):
    """PRD §4: "Nine endpoints create a new resource and answer with HTTP 201 Created:
    `POST /carriers`, `POST /carriers/{id}/fee-payments`, `POST /process-agents`,
    `POST /insurers`, `POST /authority-applications`,
    `POST /operating-authorities/{id}/process-agent-designations`,
    `POST /insurance-filings`, `POST /operating-authorities/{id}/customer-contracts`
    and `POST /customer-contracts/{id}/shipments`."
    PRD §3.1: "A `RegistryAdmin` enrolls a motor carrier by supplying its registered
    `legal_name` (a non-blank string of 1 to 200 characters), an optional `dba_name` (its
    doing-business-as name, which is either null or a string of 1 to 200 characters and
    defaults to null when omitted), the `domicile_state` two-letter code of its principal
    place of business, and three self-reported figures from the unified registration form:
    `self_reported_vehicle_count` (power units, at least 1), `self_reported_driver_count`
    (at least 1) and `self_reported_oos_rate_pct` (the carrier's own estimate of its
    roadside out-of-service percentage, a number from 0.0 through 100.0 carrying at most
    two decimals)."
    PRD §3.1: "Its `usdot_number` is minted, its `unified_registration_status` opens at
    `NOT_REGISTERED` (the only other value is `REGISTERED`), its `entrant_status` opens at
    `NEW_ENTRANT` (the only other value is `PERMANENT`), its `compliance_risk_variant`
    opens at `NONE` (its other values being `SELF_REPORTED` and `AUDITED`) with
    `compliance_risk_score` and `audited_oos_rate_pct` both null, and its four fee
    counters — `fee_balance_cents`, `fees_assessed_total_cents`,
    `fees_reversed_total_cents` and `fees_paid_total_cents` — all open at zero, as does
    `active_authority_count`."
    PRD §3.1: "Registration also opens the MCS-150 clock: `biennial_update_due_at` is set
    to the carrier's `created_at` plus 730 days, `last_biennial_update_at` is null, and
    `biennial_delinquent` is false."
    PRD §2.4: "A `Carrier` receives a `usdot_number` formatted as the literal prefix
    `USDOT-` followed by seven digits, zero-padded, assigned in carrier creation order and
    unique across all carriers."
    PRD §2.4: "Most resources carry the full system-managed set: `id`, `created_at` (the
    instant the record was first written), `updated_at` (the instant of the most recent
    mutation) and `version` (an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of the record)."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/entities/carrier_creation_returns_201_with_every_declared_field
    """
    set_clock(api, T_ENROLL)

    response = api.create_carrier(
        factories.carrier_payload(
            legal_name="Llano Estacado Transport LLC",
            dba_name="Llano Freight",
            domicile_state="TX",
            self_reported_vehicle_count=25,
            self_reported_driver_count=30,
            self_reported_oos_rate_pct=8.0,
        ),
        REGISTRY_ADMIN,
    )
    carrier = validate_success(response, 201)
    assert_carrier(carrier)

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single created resource is response_type 'object', got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert_instant_format(
        raw_body(response)["meta"]["api_request_timestamp"], "api_request_timestamp"
    )

    assert carrier["legal_name"] == "Llano Estacado Transport LLC"
    assert carrier["dba_name"] == "Llano Freight"
    assert carrier["domicile_state"] == "TX"
    assert carrier["self_reported_vehicle_count"] == 25
    assert carrier["self_reported_driver_count"] == 30
    assert float(carrier["self_reported_oos_rate_pct"]) == 8.0

    assert re.match(USDOT_NUMBER_PATTERN, carrier["usdot_number"]), (
        f"usdot_number must be USDOT- plus seven digits, got {carrier['usdot_number']!r}"
    )
    assert carrier["unified_registration_status"] == "NOT_REGISTERED"
    assert carrier["entrant_status"] == "NEW_ENTRANT"
    assert carrier["compliance_risk_variant"] == "NONE"
    assert carrier["compliance_risk_score"] is None
    assert carrier["audited_oos_rate_pct"] is None
    for counter in (
        "fee_balance_cents",
        "fees_assessed_total_cents",
        "fees_reversed_total_cents",
        "fees_paid_total_cents",
    ):
        assert carrier[counter] == 0, f"{counter} opens at zero, got {carrier[counter]}"
    assert carrier["active_authority_count"] == 0

    assert carrier["created_at"] == "2026-08-01T00:00:00.000Z"
    assert carrier["biennial_update_due_at"] == "2028-07-31T00:00:00.000Z", (
        "biennial_update_due_at is created_at plus 730 days, got "
        f"{carrier['biennial_update_due_at']}"
    )
    assert carrier["last_biennial_update_at"] is None
    assert carrier["biennial_delinquent"] is False
    assert carrier["version"] == 1


def test_carrier_read_returns_the_stored_record_without_recomputing_it(api):
    """PRD §2.4: "Neither identifier is ever supplied by a client, and neither is ever
    reused."
    PRD §3.1: "Its `usdot_number` is minted, its `unified_registration_status` opens at
    `NOT_REGISTERED` (the only other value is `REGISTERED`), its `entrant_status` opens at
    `NEW_ENTRANT` (the only other value is `PERMANENT`), its `compliance_risk_variant`
    opens at `NONE` (its other values being `SELF_REPORTED` and `AUDITED`) with
    `compliance_risk_score` and `audited_oos_rate_pct` both null, and its four fee
    counters — `fee_balance_cents`, `fees_assessed_total_cents`,
    `fees_reversed_total_cents` and `fees_paid_total_cents` — all open at zero, as does
    `active_authority_count`."
    PRD §2.1: "Read endpoints are deliberately open: they are granted to the roles listed
    in §4 without any ownership scoping, so an `InsuranceFiler` may read a carrier it does
    not insure and a `CarrierRep` may read another carrier's authority."

    Design: Corner/entities/carrier_retrieval_returns_the_stored_record
    """
    set_clock(api, T_ENROLL)
    created = create_carrier(
        api, legal_name="Guadalupe Valley Haulers LLC", domicile_state="TX"
    )

    fetched = validate_success(api.get_carrier(created["id"], COMPLIANCE_OFFICER))
    assert_carrier(fetched)

    assert fetched["id"] == created["id"]
    assert fetched["usdot_number"] == created["usdot_number"], (
        "usdot_number is minted once and never re-minted on a read"
    )
    assert fetched["legal_name"] == "Guadalupe Valley Haulers LLC"
    assert fetched["domicile_state"] == "TX"
    assert fetched["unified_registration_status"] == "NOT_REGISTERED"
    assert fetched["entrant_status"] == "NEW_ENTRANT"
    assert fetched["compliance_risk_score"] is None
    assert fetched["compliance_risk_variant"] == "NONE"
    assert fetched["fee_balance_cents"] == 0
    assert fetched["fees_assessed_total_cents"] == 0
    assert fetched["version"] == created["version"] == 1
    assert fetched["created_at"] == created["created_at"]


def test_authority_application_listing_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` sets the maximum number of records returned; it defaults to 10,
    may not be smaller than 1 and may not be larger than 100."
    PRD §2.3: "`offset` sets how many records are skipped before the page begins and
    defaults to 0."
    PRD §2.3: "Every list endpoint, without exception, orders its records by `created_at`
    ascending — the same order in which the suspension, restoration and termination
    cascades walk their targets, so a list response can be read as a replay of what a
    cascade will do."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the
    envelope's `meta` object, where `total_count` is the number of records matching the
    filters before the page window is applied and `has_more` is true when records remain
    beyond the current window."

    Design: Corner/entities/authority_application_listing_paginates_with_total_count_and_has_more
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Brazos Bend Logistics LLC")

    # Distinct creation instants so created_at ascending is a total order.
    set_clock(api, "2026-08-01T00:00:00Z")
    first = create_draft_application(
        api, carrier["id"], requested_operating_states=["TX"]
    )
    set_clock(api, "2026-08-02T00:00:00Z")
    create_draft_application(api, carrier["id"], requested_operating_states=["TX", "OK"])
    set_clock(api, "2026-08-03T00:00:00Z")
    third = create_draft_application(
        api, carrier["id"], requested_operating_states=["TX", "OK", "NM"]
    )

    page_one = api.list_applications(REGISTRY_ADMIN, carrier_id=carrier["id"], limit=2, offset=0)
    rows, meta = validate_paginated(page_one)
    assert page_one.json()["response_type"] == "array"
    assert len(rows) == 2, f"limit=2 must return exactly two rows, got {len(rows)}"
    assert meta["total_count"] == 3, (
        f"total_count counts every match before the window, got {meta['total_count']}"
    )
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True, "one record remains beyond the first window"
    assert rows[0]["id"] == first["id"], "the list is ordered created_at ascending"
    assert_authority_application(rows[0])

    rows2, meta2 = validate_paginated(
        api.list_applications(REGISTRY_ADMIN, carrier_id=carrier["id"], limit=2, offset=2)
    )
    assert len(rows2) == 1, f"offset=2 leaves exactly one row, got {len(rows2)}"
    assert meta2["total_count"] == 3
    assert meta2["offset"] == 2
    assert meta2["has_more"] is False, "nothing remains beyond the second window"
    assert rows2[0]["id"] == third["id"]

def test_carrier_read_with_an_unknown_id_reports_carrier_not_found(api):
    """PRD §2.8: "The resources named by `{id}` path segments exist. A missing `Carrier` on
    `GET /carriers/{id}`, `GET /carriers/{id}/safety-audits`,
    `GET /carriers/{id}/fee-ledger-entries`, `POST /carriers/{id}/biennial-update` or
    `POST /carriers/{id}/fee-payments` yields `ERR_CARRIER_NOT_FOUND`."
    PRD §5: "Every failed request answers with the error envelope of §2.2, carrying exactly
    one of the identifiers below in its `error_id`."
    PRD §2.4: "Most resources carry the full system-managed set: `id`, `created_at` (the
    instant the record was first written), `updated_at` (the instant of the most recent
    mutation) and `version` (an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of the record)."

    Design: Corner/entities/carrier_read_with_an_unknown_id_returns_404
    """
    set_clock(api, T_ENROLL)
    existing = create_carrier(api, legal_name="Pecos River Freight LLC")

    validate_error(
        api.get_carrier(UNKNOWN_CARRIER_ID, REGISTRY_ADMIN),
        ApiErrorId.CARRIER_NOT_FOUND,
    )

    # The failed read left the real carrier untouched.
    still_there = validate_success(api.get_carrier(existing["id"], REGISTRY_ADMIN))
    assert still_there["version"] == 1
    assert still_there["legal_name"] == "Pecos River Freight LLC"


@pytest.mark.parametrize(
    "missing_field",
    ["application_kind", "transportation_type", "requested_operating_states"],
)
def test_application_missing_a_required_field_is_rejected(api, missing_field):
    """PRD §2.8: "The request body is structurally valid — `ERR_INVALID_REQUEST` (HTTP 400).
    Applies to every write endpoint. The body must carry all required fields; enum-typed
    fields must hold a value from their declared set; integers declared non-negative must be
    non-negative; instants must be parseable ISO 8601; every state code must be one of the
    51 valid two-letter USPS codes; `requested_operating_states` must be non-empty and free
    of duplicates; `term_start_at` must be strictly before `term_end_at`; and
    `effective_to`, when supplied, must not be earlier than `effective_from`."
    PRD §3.2: "A `CarrierRep` opens an application in `DRAFT` status by naming its own
    carrier through `carrier_id`, choosing the track it follows through `application_kind` —
    one of `NEW`, `NAME_CHANGE`, `REINSTATEMENT` or `SUCCESSOR_IN_INTEREST` — and choosing
    the class of authority requested through `transportation_type`, one of
    `FOR_HIRE_PROPERTY`, `HOUSEHOLD_GOODS`, `PASSENGER`, `PROPERTY_BROKER` or
    `FREIGHT_FORWARDER`. The applicant also lists `requested_operating_states`, between 1
    and 51 distinct valid state codes naming every state in which it will operate."

    Design: Corner/entities/application_missing_a_required_field_is_rejected
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Canadian River Carriers LLC")

    payload = factories.without(
        factories.application_payload(
            carrier["id"],
            application_kind="NEW",
            transportation_type="FOR_HIRE_PROPERTY",
            requested_operating_states=["TX", "OK", "NM"],
        ),
        missing_field,
    )
    assert missing_field not in payload

    validate_error(
        api.create_application(payload, make_carrier_headers(carrier["id"])),
        ApiErrorId.INVALID_REQUEST,
    )

    _rows, meta = validate_paginated(
        api.list_applications(REGISTRY_ADMIN, carrier_id=carrier["id"])
    )
    assert meta["total_count"] == 0, (
        "a rejected create must not leave an application behind, "
        f"got total_count {meta['total_count']}"
    )


def test_omitted_optional_inputs_take_their_declared_defaults(api):
    """PRD §3.1: "A `RegistryAdmin` enrolls a motor carrier by supplying its registered
    `legal_name` (a non-blank string of 1 to 200 characters), an optional `dba_name` (its
    doing-business-as name, which is either null or a string of 1 to 200 characters and
    defaults to null when omitted), the `domicile_state` two-letter code of its principal
    place of business, and three self-reported figures from the unified registration form:
    `self_reported_vehicle_count` (power units, at least 1), `self_reported_driver_count`
    (at least 1) and `self_reported_oos_rate_pct` (the carrier's own estimate of its
    roadside out-of-service percentage, a number from 0.0 through 100.0 carrying at most
    two decimals)."
    PRD §3.1: "it is registered with a `company_name` (non-blank, 1 to 200 characters), a
    `coverage_states` list of 1 to 51 distinct valid state codes naming where it may accept
    service, and a `blanket_agent` flag that defaults to false."
    PRD §3.2: "`hazmat_endorsement_requested` states whether hazardous-materials transport
    authority is requested and defaults to false, and `hazmat_bulk_capable` states whether
    the applicant will move hazardous materials in bulk — in a cargo tank or hopper — and
    also defaults to false."
    PRD §3.2: "`predecessor_authority_id` must be non-null for the `NAME_CHANGE`,
    `REINSTATEMENT` and `SUCCESSOR_IN_INTEREST` tracks and must be null for `NEW`; it names
    an existing `OperatingAuthority`."
    PRD §3.2: "`passenger_seating_capacity` — the designed seating capacity including the
    driver, at least 1 when present — must be non-null when `transportation_type` is
    `PASSENGER` and must be null for every other class."
    PRD §3.2: "`proposed_legal_name` must be non-null when `application_kind` is
    `NAME_CHANGE` and must be null otherwise."
    PRD §3.2: "`submission_count` opens at zero."

    Design: Corner/entities/omitted_optional_inputs_take_their_declared_defaults
    """
    set_clock(api, T_ENROLL)

    # dba_name omitted entirely.
    carrier = validate_success(
        api.create_carrier(
            factories.without(
                factories.carrier_payload(legal_name="Red River Transport LLC"),
                "dba_name",
            ),
            REGISTRY_ADMIN,
        ),
        201,
    )
    assert carrier["dba_name"] is None, "an omitted dba_name defaults to null"

    # blanket_agent omitted entirely.
    agent = validate_success(
        api.create_process_agent(
            factories.without(
                factories.process_agent_payload(
                    company_name="Panhandle Service Agents LLC",
                    coverage_states=["TX", "OK", "NM"],
                ),
                "blanket_agent",
            ),
            REGISTRY_ADMIN,
        ),
        201,
    )
    assert agent["blanket_agent"] is False, "an omitted blanket_agent defaults to false"
    assert agent["coverage_states"] == ["TX", "OK", "NM"]

    # Both hazmat flags and all three conditionally-required inputs omitted.
    payload = factories.without(
        factories.application_payload(
            carrier["id"],
            application_kind="NEW",
            transportation_type="FOR_HIRE_PROPERTY",
            requested_operating_states=["TX", "OK", "NM"],
        ),
        "hazmat_endorsement_requested",
        "hazmat_bulk_capable",
    )
    for omitted in (
        "hazmat_endorsement_requested",
        "hazmat_bulk_capable",
        "predecessor_authority_id",
        "passenger_seating_capacity",
        "proposed_legal_name",
    ):
        assert omitted not in payload

    application = validate_success(
        api.create_application(payload, make_carrier_headers(carrier["id"])), 201
    )
    assert_authority_application(application)
    assert application["hazmat_endorsement_requested"] is False
    assert application["hazmat_bulk_capable"] is False
    assert application["predecessor_authority_id"] is None, (
        "predecessor_authority_id must be null for the NEW track"
    )
    assert application["passenger_seating_capacity"] is None, (
        "passenger_seating_capacity must be null for a non-PASSENGER class"
    )
    assert application["proposed_legal_name"] is None, (
        "proposed_legal_name must be null when application_kind is not NAME_CHANGE"
    )
    assert application["submission_count"] == 0


def test_application_required_limit_fields_are_computed_at_creation(api):
    """PRD §3.2: "Opening the draft immediately previews two calculations, and nothing is
    charged yet."
    PRD §3.2: "These are computed from the application's own input fields alone; no other
    entity is consulted."
    PRD §3.2: "For a `PROPERTY_BROKER` application, the base is zero — a broker arranges
    transportation rather than performing it, so no liability limit is imposed on it."
    PRD §3.2: "An applicant whose base is zero — a property broker with no
    hazardous-materials endorsement — is never uplifted, because the uplift is additive and
    applies only above a positive base."
    PRD §3.2: "Separately, `required_cargo_limit_cents` is $10,000 for a `HOUSEHOLD_GOODS`
    application and zero for every other class, and `required_bond_limit_cents` is $75,000
    for a `PROPERTY_BROKER` or `FREIGHT_FORWARDER` application and zero for every other
    class. All three are stored in cents, and because every constant above is a whole number
    of cents no rounding arises."
    PRD §4: "Open a draft authority application for one transportation type, previewing the
    filing fee and the three insurance minimums without charging anything."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."
    PRD §4: "Read one authority application with its frozen fee breakdown, required minimums
    and vetting findings."

    Design: Corner/entities/application_required_limit_fields_are_computed_at_creation
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Cimarron Brokerage LLC")

    created = validate_success(
        api.create_application(
            factories.application_payload(
                carrier["id"],
                application_kind="NEW",
                transportation_type="PROPERTY_BROKER",
                requested_operating_states=["TX", "OK", "NM"],
                hazmat_endorsement_requested=False,
                hazmat_bulk_capable=False,
            ),
            make_carrier_headers(carrier["id"]),
        ),
        201,
    )
    assert_authority_application(created)

    assert created["required_bipd_limit_cents"] == 0, (
        "a property broker with no hazmat endorsement has a zero liability base and is "
        f"never uplifted, got {created['required_bipd_limit_cents']}"
    )
    assert created["required_cargo_limit_cents"] == 0, (
        "cargo is $10,000 only for HOUSEHOLD_GOODS, got "
        f"{created['required_cargo_limit_cents']}"
    )
    assert created["required_bond_limit_cents"] == 7500000, (
        "a PROPERTY_BROKER bond minimum is $75,000 in cents, got "
        f"{created['required_bond_limit_cents']}"
    )

    # The same three figures come back on the read.
    fetched = validate_success(api.get_application(created["id"], REGISTRY_ADMIN))
    assert fetched["required_bipd_limit_cents"] == 0
    assert fetched["required_cargo_limit_cents"] == 0
    assert fetched["required_bond_limit_cents"] == 7500000


def test_system_minted_identifiers_follow_the_declared_format_and_creation_order(api):
    """PRD §2.4: "A `Carrier` receives a `usdot_number` formatted as the literal prefix
    `USDOT-` followed by seven digits, zero-padded, assigned in carrier creation order and
    unique across all carriers."
    PRD §2.4: "Neither identifier is ever supplied by a client, and neither is ever reused."
    PRD §2.4: "Most resources carry the full system-managed set: `id`, `created_at` (the
    instant the record was first written), `updated_at` (the instant of the most recent
    mutation) and `version` (an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of the record)."
    PRD §2.5: "Before the clock has ever been set, it reads exactly
    `2026-08-01T00:00:00.000Z`. That startup default is fixed: the server must never fall
    back to real wall-clock time, not at boot and not between requests."

    Design: Corner/entities/system_minted_identifiers_follow_the_declared_format_and_creation_order
    """
    set_clock(api, T_ENROLL)

    first_payload = factories.carrier_payload(legal_name="Alpha Freight Lines LLC")
    assert "usdot_number" not in first_payload, "a client never supplies the usdot_number"
    first = validate_success(api.create_carrier(first_payload, REGISTRY_ADMIN), 201)
    second = create_carrier(api, legal_name="Beta Freight Lines LLC")

    for carrier in (first, second):
        assert re.match(USDOT_NUMBER_PATTERN, carrier["usdot_number"]), (
            f"usdot_number must be USDOT- plus seven zero-padded digits, "
            f"got {carrier['usdot_number']!r}"
        )
        assert carrier["created_at"] == "2026-08-01T00:00:00.000Z"
        assert carrier["version"] == 1

    assert first["usdot_number"] != second["usdot_number"], (
        "usdot_number is unique across all carriers"
    )
    first_suffix = int(first["usdot_number"].split("-")[1])
    second_suffix = int(second["usdot_number"].split("-")[1])
    assert second_suffix > first_suffix, (
        "usdot_number is assigned in carrier creation order, got "
        f"{first['usdot_number']} then {second['usdot_number']}"
    )
    assert first["id"] != second["id"]


@pytest.mark.parametrize(
    "target,overrides",
    [
        ("carrier", {"domicile_state": "ZZ"}),
        ("carrier", {"self_reported_vehicle_count": 0}),
        ("carrier", {"self_reported_oos_rate_pct": 150.0}),
        ("application", {"application_kind": "PROVISIONAL"}),
        ("application", {"transportation_type": "AIR_FREIGHT"}),
        ("application", {"requested_operating_states": ["TX", "ZZ"]}),
    ],
)
def test_invalid_enum_and_out_of_range_inputs_are_rejected(api, target, overrides):
    """PRD §2.8: "The request body is structurally valid — `ERR_INVALID_REQUEST` (HTTP 400).
    Applies to every write endpoint. The body must carry all required fields; enum-typed
    fields must hold a value from their declared set; integers declared non-negative must be
    non-negative; instants must be parseable ISO 8601; every state code must be one of the
    51 valid two-letter USPS codes; `requested_operating_states` must be non-empty and free
    of duplicates; `term_start_at` must be strictly before `term_end_at`; and
    `effective_to`, when supplied, must not be earlier than `effective_from`."
    PRD §3.1: "the `domicile_state` two-letter code of its principal place of business, and
    three self-reported figures from the unified registration form:
    `self_reported_vehicle_count` (power units, at least 1), `self_reported_driver_count`
    (at least 1) and `self_reported_oos_rate_pct` (the carrier's own estimate of its
    roadside out-of-service percentage, a number from 0.0 through 100.0 carrying at most
    two decimals)."
    PRD §3.2: "choosing the track it follows through `application_kind` — one of `NEW`,
    `NAME_CHANGE`, `REINSTATEMENT` or `SUCCESSOR_IN_INTEREST` — and choosing the class of
    authority requested through `transportation_type`, one of `FOR_HIRE_PROPERTY`,
    `HOUSEHOLD_GOODS`, `PASSENGER`, `PROPERTY_BROKER` or `FREIGHT_FORWARDER`."
    PRD §5: "Every failed request answers with the error envelope of §2.2, carrying exactly
    one of the identifiers below in its `error_id`."

    Design: Corner/entities/invalid_enum_and_out_of_range_inputs_are_rejected
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Sabine Pass Motor Lines LLC")

    if target == "carrier":
        response = api.create_carrier(
            factories.carrier_payload(legal_name="Rejected Carrier LLC", **overrides),
            REGISTRY_ADMIN,
        )
    else:
        response = api.create_application(
            factories.application_payload(carrier["id"], **overrides),
            make_carrier_headers(carrier["id"]),
        )

    validate_error(response, ApiErrorId.INVALID_REQUEST)

    if target == "application":
        _rows, meta = validate_paginated(
            api.list_applications(REGISTRY_ADMIN, carrier_id=carrier["id"])
        )
        assert meta["total_count"] == 0, (
            f"a rejected create writes no application, got total_count {meta['total_count']}"
        )


def test_process_agent_is_immutable_and_carries_no_version_field(api):
    """PRD §2.4: "Two resources are immutable once written and therefore carry only `id` and
    `created_at` — they have no `updated_at` field and no `version` field at all. The first
    is `ProcessAgent`: a process-agent organization is registered with a `company_name`, a
    `coverage_states` list and a `blanket_agent` flag, and is never edited afterwards."
    PRD §3.1: "A blanket agent is a special case worth stating plainly: when
    `blanket_agent` is true, the organization is treated as covering all fifty-one
    jurisdictions regardless of what its `coverage_states` list actually contains."

    Design: Corner/entities/process_agent_is_immutable_and_carries_no_version_field
    """
    set_clock(api, T_ENROLL)

    agent = validate_success(
        api.create_process_agent(
            factories.process_agent_payload(
                company_name="Gulf Coast Process Agents",
                coverage_states=["TX", "LA"],
                blanket_agent=False,
            ),
            REGISTRY_ADMIN,
        ),
        201,
    )
    assert_process_agent(agent)

    assert agent["company_name"] == "Gulf Coast Process Agents"
    assert agent["coverage_states"] == ["TX", "LA"]
    assert agent["blanket_agent"] is False
    assert "created_at" in agent
    assert "updated_at" not in agent, (
        f"a ProcessAgent has no updated_at field at all, got keys {sorted(agent)}"
    )
    assert "version" not in agent, (
        f"a ProcessAgent has no version field at all, got keys {sorted(agent)}"
    )


def test_designation_write_against_an_unknown_authority_returns_not_found(api):
    """PRD §2.8: "A missing `OperatingAuthority` on `GET /operating-authorities/{id}`,
    `GET /operating-authorities/{id}/revocation-proceedings`,
    `GET /operating-authorities/{id}/customer-contracts`,
    `POST /operating-authorities/{id}/process-agent-designations`,
    `POST /operating-authorities/{id}/activate` or
    `POST /operating-authorities/{id}/customer-contracts` yields
    `ERR_AUTHORITY_NOT_FOUND`."
    PRD §2.9: "Path segments are resolved strictly left to right, so the leftmost identifier
    that names no existing row determines the error: a request for the safety audits of a
    non-existent carrier reports `ERR_CARRIER_NOT_FOUND` and never reaches the audit
    lookup."
    PRD §5: "Every failed request answers with the error envelope of §2.2, carrying exactly
    one of the identifiers below in its `error_id`."

    Design: Corner/entities/designation_write_against_an_unknown_authority_returns_404
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Neches Valley Transport LLC")
    agent = create_process_agent(api, coverage_states=["TX", "OK", "NM"])

    validate_error(
        api.create_designations(
            UNKNOWN_AUTHORITY_ID,
            factories.designation_payload(
                agent["id"],
                state_codes=["TX"],
                effective_from="2026-08-05T00:00:00Z",
            ),
            make_carrier_headers(carrier["id"]),
        ),
        ApiErrorId.AUTHORITY_NOT_FOUND,
    )

    _rows, meta = validate_paginated(
        api.list_designations(REGISTRY_ADMIN, process_agent_id=agent["id"])
    )
    assert meta["total_count"] == 0, (
        "the rejected write designated nothing, got total_count "
        f"{meta['total_count']}"
    )


def test_body_foreign_key_to_an_unknown_predecessor_is_rejected(api):
    """PRD §2.8: "Every foreign key supplied in the request **body** resolves to an existing
    row — `carrier_id`, `predecessor_authority_id`, `authority_id`, `insurer_id`,
    `process_agent_id` — yielding `ERR_REFERENCE_NOT_FOUND`. Applies to
    `POST /authority-applications`, `POST /insurance-filings` and
    `POST /operating-authorities/{id}/process-agent-designations`. Note that this precedes
    the structural check below."
    PRD §3.2: "`predecessor_authority_id` must be non-null for the `NAME_CHANGE`,
    `REINSTATEMENT` and `SUCCESSOR_IN_INTEREST` tracks and must be null for `NEW`; it names
    an existing `OperatingAuthority`."
    PRD §5: "Every failed request answers with the error envelope of §2.2, carrying exactly
    one of the identifiers below in its `error_id`."

    Design: Corner/entities/body_foreign_key_to_an_unknown_predecessor_is_rejected
    """
    set_clock(api, T_ENROLL)
    carrier = create_carrier(api, legal_name="Trinity Bay Motor Freight LLC")

    validate_error(
        api.create_application(
            factories.application_payload(
                carrier["id"],
                application_kind="NAME_CHANGE",
                transportation_type="FOR_HIRE_PROPERTY",
                requested_operating_states=["TX", "OK", "NM"],
                predecessor_authority_id=UNKNOWN_PREDECESSOR_ID,
                proposed_legal_name="Trinity Bay Logistics LLC",
            ),
            make_carrier_headers(carrier["id"]),
        ),
        ApiErrorId.REFERENCE_NOT_FOUND,
    )

    _rows, meta = validate_paginated(
        api.list_applications(REGISTRY_ADMIN, carrier_id=carrier["id"])
    )
    assert meta["total_count"] == 0, (
        f"the rejected create wrote no application, got total_count {meta['total_count']}"
    )
