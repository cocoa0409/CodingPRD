"""The declared field set of each record, the defaults it mints, and the
system- and formula-sourced fields a caller never supplies.
"""
from test_helpers import (
    PRACTICE_ADMIN,
    api_client,
    assert_client,
    assert_common_fields,
    assert_envelope_meta,
    assert_time_entry,
    assert_vendor,
    create_assessment_payload,
    create_client_payload,
    create_family_contact_payload,
    create_service_authorization_payload,
    create_ratified_decision,
    create_time_entry_payload,
    create_vendor_payload,
    domain_scores,
    make_care_manager_headers,
    read_care_plan,
    read_client,
    read_decision,
    register_care_manager,
    register_client,
    register_client_with_practice_defaults,
    register_surrogate_contact,
    set_logical_clock,
    setup_active_care_plan_scenario,
    uniform_domain_scores,
    validate_error,
    validate_paginated,
    validate_success,
)

_UNKNOWN_CLIENT_ID = "00000000-0000-4000-8000-000000000000"
_UNKNOWN_PARENT_ID = "00000000-0000-4000-8000-0000000000ff"


def test_01_registering_a_client_answers_the_envelope_and_every_declared_field():
    """All six inputs are echoed back inside the standard envelope, and the
    record opens on its declared status, posture and zeroed ledger.

    PRD: "A freshly registered client is in `PROSPECT` status with `capacity_status` at `PRESUMED_CAPABLE`, `capacity_basis` null, `risk_posture` at `ROUTINE`, `acuity_score` at 0, `protective_escalation_status` at `NONE`, and every ledger quantity — `retainer_deposits_total_cents`, `retainer_balance_cents`, `unbilled_accrual_cents` and `authorized_coverage_hours` — at 0."

    Design: Corner/entities/create_client_returns_envelope_and_every_declared_field
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    response = api_client.create_client(
        create_client_payload(
            full_name="Alma Whitcombe",
            residence_setting="ASSISTED_LIVING",
            billing_increment_min=6,
            travel_billing_pct=40,
            retainer_floor_cents=100_000,
            authorized_concurrent_caregivers=3,
        ),
        PRACTICE_ADMIN,
    )
    data = validate_success(response, 201)
    body = response.json()
    assert_envelope_meta(body)
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict)

    assert data["full_name"] == "Alma Whitcombe"
    assert data["residence_setting"] == "ASSISTED_LIVING"
    assert data["billing_increment_min"] == 6
    assert data["travel_billing_pct"] == 40
    assert data["retainer_floor_cents"] == 100_000
    assert data["authorized_concurrent_caregivers"] == 3

    assert data["status"] == "PROSPECT"
    assert data["capacity_status"] == "PRESUMED_CAPABLE"
    assert data["capacity_basis"] is None
    assert data["risk_posture"] == "ROUTINE"
    assert data["acuity_score"] == 0
    assert data["protective_escalation_status"] == "NONE"
    assert data["retainer_deposits_total_cents"] == 0
    assert data["retainer_balance_cents"] == 0
    assert data["unbilled_accrual_cents"] == 0
    assert data["authorized_coverage_hours"] == 0

    assert_client(data)
    assert_common_fields(data, "client")
    assert data["version"] == 1


def test_02_omitting_the_four_commercial_options_stores_the_practice_defaults():
    """Every optional commercial parameter left out comes back as its declared
    default rather than a null or a zero, and the defaults are persisted.

    PRD: "`retainer_floor_cents` is the retainer balance below which the client is automatically suspended for nonpayment; it defaults to 50,000 cents — five hundred dollars — and may not be negative."

    Design: Corner/entities/create_client_applies_declared_defaults_when_optionals_omitted
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    client = register_client_with_practice_defaults(
        full_name="Bruno Kestrel", residence_setting="PRIVATE_HOME"
    )

    assert client["billing_increment_min"] == 15
    assert client["travel_billing_pct"] == 50
    assert client["retainer_floor_cents"] == 50_000
    assert client["authorized_concurrent_caregivers"] == 2

    stored = read_client(client["id"])
    assert stored["billing_increment_min"] == 15
    assert stored["travel_billing_pct"] == 50
    assert stored["retainer_floor_cents"] == 50_000
    assert stored["authorized_concurrent_caregivers"] == 2


def test_03_reading_a_client_back_returns_the_stored_row_without_mutating_it():
    """The record addressed by id is the record that was registered, and a read
    is not a mutation — the version stands still.

    PRD: "`version` is an integer that begins at 1 when the record is created and increases by exactly 1 on every mutation of that record, including mutations the record suffers as a cascade from some other operation."

    Design: Corner/entities/get_client_by_id_returns_the_stored_row
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    care_manager = register_care_manager()
    created = register_client(
        full_name="Cordelia Nkemdi", residence_setting="SKILLED_NURSING"
    )

    response = api_client.get_client(
        created["id"], make_care_manager_headers(care_manager["id"])
    )
    data = validate_success(response, 200)

    assert data["id"] == created["id"]
    assert data["version"] == created["version"]
    assert data["full_name"] == "Cordelia Nkemdi"
    assert data["residence_setting"] == "SKILLED_NURSING"


def test_04_the_client_roster_reports_the_filtered_total_and_whether_more_remain():
    """Two pages over three clients: the first is full and reports more to come,
    the second holds the remainder and reports none, and the two are disjoint.

    PRD: "Both `limit` and `offset` are echoed in the `meta` object of the response together with `total_count` — the number of records matching the filters before pagination is applied — and `has_more`, which is true exactly when records matching the filters remain beyond the current page."

    Design: Corner/entities/list_clients_pagination_reports_total_count_and_has_more
    """
    set_logical_clock("2026-08-01T10:00:00Z")
    register_client(full_name="Dorothea Vasquez", residence_setting="PRIVATE_HOME")
    set_logical_clock("2026-08-01T11:00:00Z")
    register_client(full_name="Emeka Balogun", residence_setting="ASSISTED_LIVING")
    set_logical_clock("2026-08-01T12:00:00Z")
    register_client(full_name="Faye Lindqvist", residence_setting="PRIVATE_HOME")

    first_rows, first_meta = validate_paginated(
        api_client.list_clients(PRACTICE_ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    last_rows, last_meta = validate_paginated(
        api_client.list_clients(PRACTICE_ADMIN, {"limit": 2, "offset": 2})
    )
    assert len(last_rows) == 1
    assert last_meta["total_count"] == 3
    assert last_meta["has_more"] is False
    assert last_meta["offset"] == 2

    first_ids = {row["id"] for row in first_rows}
    assert last_rows[0]["id"] not in first_ids

    all_rows, all_meta = validate_paginated(api_client.list_clients(PRACTICE_ADMIN))
    assert all_meta["limit"] == 10
    assert all_meta["offset"] == 0
    assert len(all_rows) == 3
    assert all_meta["total_count"] == 3


def test_05_an_unstored_client_id_is_a_not_found_error_not_an_empty_success():
    """A syntactically valid identifier that matches no client answers with the
    client-specific not-found code inside the declared error envelope.

    PRD: "Each resolves to its own not-found error: a `clientId` or a body-carried `client_id` that matches no client yields `ERR_CLIENT_NOT_FOUND`; a `careManagerId` or a referenced `care_manager_id` yields `ERR_CARE_MANAGER_NOT_FOUND`; a `vendorId` or referenced `vendor_id` yields `ERR_VENDOR_NOT_FOUND`"

    Design: Corner/entities/get_client_with_unknown_id_returns_client_not_found
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    response = api_client.get_client(_UNKNOWN_CLIENT_ID, PRACTICE_ADMIN)
    validate_error(response, "ERR_CLIENT_NOT_FOUND", 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_CLIENT_NOT_FOUND"
    assert isinstance(body["data"]["message"], str)
    assert body["data"]["message"] != ""
    assert "meta" in body


def test_06_an_assessment_without_domain_scores_is_refused_and_persists_nothing():
    """The six-domain score object is required, so an assessment posted without
    it never becomes a row and never fires the first-assessment side effect.

    PRD: "A care manager opens an assessment by naming the `client_id` under assessment and the `care_manager_id` authoring it, and by supplying `domain_scores`: an object carrying exactly six integer keys — `adl`, `cognition`, `medical_complexity`, `social_support`, `safety` and `finances` — each valued between 0 and 5 inclusive."

    Design: Corner/entities/create_assessment_missing_required_domain_scores_returns_invalid_request
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    care_manager = register_care_manager()
    client = register_client(full_name="Ilse Marchetti", residence_setting="PRIVATE_HOME")

    payload = create_assessment_payload(client["id"], care_manager["id"])
    payload.pop("domain_scores")
    response = api_client.create_assessment(
        payload, make_care_manager_headers(care_manager["id"])
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api_client.list_assessments(PRACTICE_ADMIN, {"client_id": client["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_client(client["id"])["status"] == "PROSPECT"


def test_07_a_domain_score_outside_zero_to_five_and_a_short_key_set_are_both_refused():
    """A score of 6 is out of range and a five-key object is short of the declared
    six, and neither is clamped or completed — both are malformed payloads.

    PRD: "A missing key, an extra key, a non-integer value or a value outside that range is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_assessment_with_out_of_range_domain_score_returns_invalid_request
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    care_manager = register_care_manager()
    client = register_client(full_name="Jorunn Aaltonen", residence_setting="PRIVATE_HOME")
    headers = make_care_manager_headers(care_manager["id"])

    out_of_range = api_client.create_assessment(
        create_assessment_payload(
            client["id"], care_manager["id"], scores=domain_scores(adl=6)
        ),
        headers,
    )
    validate_error(out_of_range, "ERR_INVALID_REQUEST", 400)

    five_keys = domain_scores()
    five_keys.pop("social_support")
    short_set = api_client.create_assessment(
        create_assessment_payload(client["id"], care_manager["id"], scores=five_keys),
        headers,
    )
    validate_error(short_set, "ERR_INVALID_REQUEST", 400)

    rows, meta = validate_paginated(
        api_client.list_assessments(PRACTICE_ADMIN, {"client_id": client["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_08_a_vendor_type_outside_the_four_verticals_is_refused_while_housing_mints_defaults():
    """`DENTAL` is not one of the four verticals the practice works in, while a
    housing provider is accepted and opens on its declared standing and fee.

    PRD: "Registration takes a `name` of 1 to 160 characters, a `vendor_type` of `HOME_CARE`, `MEDICAL`, `LEGAL` or `HOUSING`, and the disclosure-critical `has_referral_relationship` flag, which is true whenever the practice receives any consideration from — or shares ownership with — that provider."

    Design: Corner/entities/create_vendor_with_invalid_vendor_type_enum_returns_invalid_request
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    rejected = api_client.create_vendor(
        create_vendor_payload(
            name="Bayside Dental", vendor_type="DENTAL", has_referral_relationship=False
        ),
        PRACTICE_ADMIN,
    )
    validate_error(rejected, "ERR_INVALID_REQUEST", 400)

    accepted = api_client.create_vendor(
        create_vendor_payload(
            name="Bayside Housing Advisors",
            vendor_type="HOUSING",
            has_referral_relationship=False,
        ),
        PRACTICE_ADMIN,
    )
    vendor = validate_success(accepted, 201)
    assert vendor["vendor_type"] == "HOUSING"
    assert vendor["standing"] == "APPROVED"
    assert vendor["referral_fee_pct"] == 0
    assert_vendor(vendor)

    rows, meta = validate_paginated(
        api_client.list_vendors(PRACTICE_ADMIN, {"vendor_type": "HOUSING"})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1
    assert rows[0]["id"] == vendor["id"]


def test_09_an_engagements_money_fields_are_derived_from_the_coverage_it_describes():
    """Nothing about the cost is declared by the caller: the whole-hour count, the
    base cost, the tier-one coordination fee and the projected total are computed
    from the window, the caregiver count and the vendor's hourly cost.

    PRD: "First, `coverage_hours` is the number of whole hours between `coverage_start` and `coverage_end`, with any partial hour discarded downward, multiplied by `concurrent_caregivers`."

    Design: Corner/entities/service_authorization_computed_money_fields_input_ignored
    """
    scenario = setup_active_care_plan_scenario(
        clock="2026-09-01T09:00:00Z",
        client_overrides={
            "full_name": "Ines Baumgartner",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        vendor_overrides={
            "name": "Northgate Home Care",
            "vendor_type": "HOME_CARE",
            "has_referral_relationship": False,
        },
        scores=uniform_domain_scores(2),
    )
    plan = read_care_plan(scenario.care_plan_id)

    response = api_client.create_service_authorization(
        create_service_authorization_payload(
            scenario.care_plan_id,
            scenario.vendor_id,
            plan["version"],
            coverage_start="2026-09-07T08:00:00Z",
            coverage_end="2026-09-07T18:00:00Z",
            concurrent_caregivers=1,
            hourly_cost_cents=4_000,
        ),
        make_care_manager_headers(scenario.care_manager_id),
    )
    data = validate_success(response, 201)

    assert data["coverage_hours"] == 10
    assert data["base_cost_cents"] == 40_000
    assert data["coordination_fee_cents"] == 3_200
    assert data["total_projected_cost_cents"] == 43_200
    assert data["auth_status"] == "PROPOSED"
    assert data["coi_status"] == "NOT_REQUIRED"
    assert data["disclosure_text"] is None
    assert data["suspension_reason"] == "NONE"
    assert data["termination_reason"] == "NONE"
    assert data["client_id"] == scenario.client_id


def test_10_a_logged_interval_generates_its_own_identity_date_and_rating():
    """The caller supplies only the interval and its context; the service date,
    the minute figures, the two factors and the money are all derived, and the
    entry opens unapproved and uninvoiced.

    PRD: "`raw_minutes` is the number of whole minutes between `start_at` and `end_at`, with any partial minute discarded downward."

    Design: Corner/entities/time_entry_system_fields_generated_and_client_input_ignored
    """
    set_logical_clock("2026-08-20T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Whitfield", hourly_rate_cents=22_500
    )
    client = register_client(
        full_name="Jorah Adeyemi",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
    )

    response = api_client.create_time_entry(
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-20T09:05:00Z",
            "2026-08-20T09:52:00Z",
            service_type="CARE_COORDINATION",
            service_location_id="CLIENT_HOME",
            note="Pharmacy reconciliation",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    data = validate_success(response, 201)

    assert data["status"] == "DRAFT"
    assert data["approved_by_care_manager_id"] is None
    assert data["invoice_id"] is None
    assert data["service_date"] == "2026-08-20"
    assert data["raw_minutes"] == 47
    assert data["rounded_minutes"] == 60
    assert float(data["rate_multiplier"]) == 1.0
    assert float(data["after_hours_factor"]) == 1.00
    assert data["billable_amount_cents"] == 22_500
    assert_time_entry(data)
    assert_common_fields(data, "time_entry")
    assert data["version"] == 1

    assert read_client(client["id"])["unbilled_accrual_cents"] == 22_500


def test_11_attaching_a_contact_to_an_unstored_client_is_a_client_not_found():
    """A family contact hangs off a client, so naming a client that does not exist
    resolves to the client's own not-found code and stores nothing.

    PRD: "The payload names the `client_id` the contact belongs to, the person's `full_name` of 1 to 120 characters, and a `contact_role` drawn from `POA_HEALTHCARE`, `POA_FINANCIAL`, `GUARDIAN`, `RESPONSIBLE_PARTY` and `INTERESTED_FAMILY`."

    Design: Corner/entities/create_family_contact_for_unknown_client_returns_client_not_found
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    response = api_client.create_family_contact(
        create_family_contact_payload(
            _UNKNOWN_PARENT_ID,
            full_name="Nobody Nowhere",
            contact_role="INTERESTED_FAMILY",
        ),
        PRACTICE_ADMIN,
    )
    validate_error(response, "ERR_CLIENT_NOT_FOUND", 404)

    _rows, meta = validate_paginated(api_client.list_family_contacts(PRACTICE_ADMIN))
    assert meta["total_count"] == 0


def test_12_an_authorizing_decision_reached_at_another_familys_conference_is_refused():
    """The named decision exists and is ratified, but its conference belongs to a
    different client, so the pairing is illegal rather than missing.

    PRD: "Existence is a weaker claim than parentage. Two records may both exist and still be an illegal pairing — a source assessment belonging to a different client, an authorizing decision reached at another family's conference, an attending contact who was never invited."

    Design: Corner/entities/flat_topology_authorizing_decision_from_another_client_rejected
    """
    kira = setup_active_care_plan_scenario(
        clock="2026-09-01T09:00:00Z",
        client_overrides={
            "full_name": "Kira Hallgrimsson",
            "residence_setting": "PRIVATE_HOME",
            "retainer_floor_cents": 0,
        },
        scores=uniform_domain_scores(2),
    )
    leon = register_client(full_name="Leon Okonkwo", residence_setting="ASSISTED_LIVING")
    leon_surrogate = register_surrogate_contact(leon["id"], full_name="Marta Okonkwo")
    borrowed = create_ratified_decision(
        leon["id"],
        leon_surrogate["id"],
        kira.care_manager_id,
        kira.supervisor_id,
        decision_type="VENDOR_ENGAGEMENT",
    )
    assert borrowed["status"] == "RATIFIED"

    plan_before = read_care_plan(kira.care_plan_id)
    response = api_client.create_service_authorization(
        create_service_authorization_payload(
            kira.care_plan_id,
            kira.vendor_id,
            plan_before["version"],
            coverage_start="2026-09-07T08:00:00Z",
            coverage_end="2026-09-07T16:00:00Z",
            concurrent_caregivers=1,
            hourly_cost_cents=4_000,
            authorizing_decision_id=borrowed["id"],
        ),
        make_care_manager_headers(kira.care_manager_id),
    )
    validate_error(response, "ERR_ENTITY_RELATIONSHIP_INVALID", 422)

    rows, meta = validate_paginated(
        api_client.list_service_authorizations(
            PRACTICE_ADMIN, {"care_plan_id": kira.care_plan_id}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_care_plan(kira.care_plan_id)["version"] == plan_before["version"]
    assert read_decision(borrowed["id"])["status"] == "RATIFIED"
