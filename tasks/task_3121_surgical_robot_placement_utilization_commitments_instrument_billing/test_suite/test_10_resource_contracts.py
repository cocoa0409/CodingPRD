"""Resource creation, catalog retrieval and child-parent addressing."""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_hospital_account,
    assert_system_configuration,
    create_account,
    create_configuration,
    create_loaner_dispatch_payload,
    create_review,
    create_training_record,
    draft_agreement,
    drive_account_to_readiness,
    get_success_data,
    set_clock,
    setup_commissioned_system,
    submit_agreement,
    validate_error,
    validate_success,
)


def test_account_creation_returns_system_fields_and_the_onboarding_gate(api):
    """PRD §3.1.1: "The account is born in `PROSPECT`, `hospital_owner_user_id` is stamped
    from the caller's `X-User-ID`, and its `account_posture` computes to `ONBOARDING_GATE` —
    there is no readiness review on file yet, and that alone is enough to hold the gate closed."

    Design: Corner/entities/account_create_returns_system_fields_and_onboarding_posture
    """
    set_clock("2026-09-01T00:00:00Z")

    res = api_client.create_account(
        {"account_name": "Corner General Hospital", "idn_group_code": "IDN-CORNER",
         "region_code": "WEST", "placement_cap": 6, "maximum_procedure_commitment": 40},
        TEST_USERS["regional_sales_director_headers"])
    account = validate_success(res, 201)

    assert_hospital_account(account)
    assert account["account_name"] == "Corner General Hospital"
    assert account["idn_group_code"] == "IDN-CORNER"
    assert account["account_status"] == "PROSPECT"
    assert account["account_posture"] == "ONBOARDING_GATE", (
        "an account with no readiness review on file is held at the gate"
    )
    assert account["version"] == 1


def test_configuration_retrieval_round_trips_the_whole_catalog_entry(api):
    """PRD §3.1.1: "Physically it declares `min_operating_room_length_cm`,
    `min_operating_room_width_cm`, `min_table_throw_radius_cm` and `min_ceiling_clearance_cm`,
    plus `integration_tier` (a depth from 1 to 3), `requires_dark_fiber` and
    `requires_dedicated_power_circuit`. Commercially it declares `base_placement_fee_cents`,
    `max_instrument_lives`, and a `feature_entitlements` array pairing each `feature_code`
    with the `min_release_index` at which it unlocks."

    Design: Corner/entities/configuration_get_round_trips_the_dimensional_catalog
    """
    set_clock("2026-09-01T00:00:00Z")
    config = create_configuration(
        model_code="DA_V2", base_placement_fee_cents=6000000, max_instrument_lives=12,
        feature_entitlements=[{"feature_code": "FIREFLY", "min_release_index": 1},
                              {"feature_code": "FORCE_FEEDBACK", "min_release_index": 3}],
        requires_dark_fiber=True, requires_dedicated_power_circuit=True, integration_tier=2)

    fetched = validate_success(api_client.get_configuration(
        config["id"], TEST_USERS["regional_sales_director_headers"]), 200)

    assert_system_configuration(fetched)
    assert fetched["model_code"] == "DA_V2"
    assert fetched["base_placement_fee_cents"] == 6000000
    assert fetched["integration_tier"] == 2
    assert fetched["max_instrument_lives"] == 12
    assert len(fetched["feature_entitlements"]) == 2
    assert fetched["requires_dark_fiber"] is True
    assert fetched["requires_dedicated_power_circuit"] is True
    assert fetched["status"] == "ACTIVE"


def test_agreement_retrieval_with_an_unallocated_id_reports_its_own_not_found_code(api):
    """PRD §2.5: "an `agreementId` yields `ERR_AGREEMENT_NOT_FOUND`".

    Design: Corner/entities/agreement_get_with_an_unallocated_id_returns_agreement_not_found
    """
    set_clock("2026-09-01T00:00:00Z")

    res = api_client.get_agreement(NON_EXISTENT_UUID,
                                   TEST_USERS["regional_sales_director_headers"])

    validate_error(res, "ERR_AGREEMENT_NOT_FOUND", expected_status=404)
    body = res.json()
    assert body["response_type"] == "error"
    assert len(body["data"]["message"].strip()) > 0


def test_configuration_creation_without_a_model_code_is_a_bad_request(api):
    """PRD §3.1.2: "The interface also exposes a generic `ERR_INVALID_REQUEST` (HTTP 400)
    for a body that is missing a required field, unparseable, or of the wrong JSON type".
    PRD §3.1.1: "It also names its `model_code`, drawn from the closed set `DA_V1`, `DA_V2`,
    `SP_V1`, `SP_V2`, `SP_V3`".

    Design: Corner/entities/configuration_create_missing_model_code_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")

    res = api_client.create_configuration(
        {"base_placement_fee_cents": 4800000, "max_instrument_lives": 10,
         "feature_entitlements": [], "requires_dark_fiber": False,
         "requires_dedicated_power_circuit": False, "integration_tier": 1,
         "min_operating_room_length_cm": 780, "min_operating_room_width_cm": 700,
         "min_table_throw_radius_cm": 320, "min_ceiling_clearance_cm": 280},
        TEST_USERS["platform_admin_headers"])

    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_omitted_agreement_terms_materialize_the_declared_defaults(api):
    """PRD §2.12: "The commitment is `minimum_procedures_per_cycle` procedures per interval
    of `interval_months` months, with an interval length of 1 month and a committed count of
    0 as the defaults".
    PRD §3.1.2: "The agreement opens in `DRAFT` with `compliance_status` `MEETS_COMMITMENT`,
    and no system, contract or cycle exists yet."

    Design: Corner/entities/agreement_optional_defaults_materialize_on_draft
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    config = create_configuration()
    review = create_review(account["id"], config["id"], verdict="PASSED")
    create_training_record(account["id"])
    account = drive_account_to_readiness(account)

    agreement = validate_success(api_client.create_agreement(
        {"hospital_account_id": account["id"], "system_configuration_id": config["id"],
         "site_readiness_review_id": review["id"], "arrangement_type": "LEASE",
         "base_monthly_fee_cents": 900000, "lease_monthly_amount_cents": 1200000},
        TEST_USERS["regional_sales_director_headers"]), 201)

    assert agreement["minimum_procedures_per_cycle"] == 0
    assert agreement["interval_months"] == 1
    assert agreement["is_shortfall_waived"] is False
    assert agreement["compliance_status"] == "MEETS_COMMITMENT"
    assert agreement["agreement_status"] == "DRAFT"
    assert agreement["net_placement_fee_cents"] is None, (
        "the net fee is null until the agreement reaches ACTIVE"
    )


def test_case_billing_and_lives_are_derived_server_side_not_client_supplied(api):
    """PRD §3.4: "The attempted load is stored as submitted and the load actually authorized
    is recorded separately as `approved_instrument_load`; the amount the case will bill is
    carried as `instrument_billing_cents`".
    PRD §3.4: "If the parent agreement's `arrangement_type` is `PURCHASE`, the amount is the
    approved instrument-and-accessory load priced at 125000 cents per whole load."

    Design: Corner/entities/procedure_case_computed_billing_and_lives_are_not_client_settable
    """
    ctx = setup_commissioned_system(config_overrides={"model_code": "DA_V2",
                                                      "max_instrument_lives": 40})

    case = validate_success(api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-10T08:00:00Z", "duration_minutes": 90,
         "instrument_load": 2, "is_emergency": False},
        ctx.account_headers), 201)

    assert case["instrument_billing_cents"] == 250000, "2 loads at 125000 per whole load"
    assert case["approved_instrument_load"] == 2
    assert case["case_status"] == "SCHEDULED"
    assert isinstance(case["commitment_cycle_index"], int)
    assert get_success_data(api_client.get_robot_system(
        ctx.system["id"], ctx.account_headers))["instrument_lives_remaining"] == 38


def test_an_unknown_arrangement_type_is_refused_at_parse_time(api):
    """PRD §3.1.2: "The agreement names its `arrangement_type` — `PURCHASE`, `LEASE` or
    `USAGE_BASED`".

    Design: Corner/entities/agreement_arrangement_type_rejects_an_unknown_enum_member
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    config = create_configuration()
    review = create_review(account["id"], config["id"], verdict="PASSED")
    create_training_record(account["id"])

    res = api_client.create_agreement(
        {"hospital_account_id": account["id"], "system_configuration_id": config["id"],
         "site_readiness_review_id": review["id"], "arrangement_type": "RENT_TO_OWN",
         "base_monthly_fee_cents": 200000, "placement_fee_cents": 6000000},
        TEST_USERS["regional_sales_director_headers"])

    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_a_loaner_dispatch_is_reachable_only_through_its_own_system(api):
    """PRD §3.3: "A `ServiceEngineer` programs a dispatch naming the displaced
    `robot_system_id`, the `loaner_serial_number`, and a `dispatch_window_start_utc` and
    `dispatch_window_end_utc`."

    Design: Corner/entities/loaner_dispatch_parent_relationship_uses_the_system_in_the_path
    """
    ctx = setup_commissioned_system()
    second_review = create_review(ctx.account["id"], ctx.config["id"], verdict="PASSED")
    second_agreement = submit_agreement(draft_agreement(
        ctx.account["id"], ctx.config["id"], second_review["id"],
        arrangement_type="LEASE", base_monthly_fee_cents=200000,
        lease_monthly_amount_cents=900000))
    account = get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))
    accepted = get_success_data(api_client.accept_agreement(
        second_agreement["id"],
        {"expected_agreement_version": second_agreement["version"],
         "expected_hospital_account_version": account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)
    second_system = get_success_data(api_client.list_agreement_robot_systems(
        accepted["id"], TEST_USERS["regional_sales_director_headers"]))[0]

    dispatch = validate_success(api_client.create_loaner_dispatch(
        create_loaner_dispatch_payload(
            ctx.system["id"], loaner_serial_number="LOAN-CORNER-1",
            dispatch_window_start_utc="2026-09-15T00:00:00Z",
            dispatch_window_end_utc="2026-09-29T00:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)

    assert dispatch["robot_system_id"] == ctx.system["id"]
    mine = get_success_data(api_client.list_system_loaner_dispatches(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]), 200)
    assert len(mine) == 1 and mine[0]["id"] == dispatch["id"]
    theirs = get_success_data(api_client.list_system_loaner_dispatches(
        second_system["id"], TEST_USERS["service_engineer_headers"]), 200)
    assert theirs == [], "the other system's sub-resource list is empty"


def test_contract_retrieval_with_an_unknown_id_reports_its_own_not_found_code(api):
    """PRD §2.5: "a `contractId` yields `ERR_CONTRACT_NOT_FOUND`".

    Design: Corner/entities/service_contract_get_with_an_unknown_id_returns_contract_not_found
    """
    set_clock("2026-09-01T00:00:00Z")

    res = api_client.get_service_contract(NON_EXISTENT_UUID,
                                          TEST_USERS["service_engineer_headers"])

    validate_error(res, "ERR_CONTRACT_NOT_FOUND", expected_status=404)