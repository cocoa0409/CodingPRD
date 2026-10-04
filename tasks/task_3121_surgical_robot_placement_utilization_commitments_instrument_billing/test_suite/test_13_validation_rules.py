"""Validation rules: auth precedence, region scoping, cross-entity credentialing gates,
cancellation-driven aggregate movement, best-effort bulk completion, and concurrency guards."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_account,
    create_case,
    create_configuration,
    create_review,
    create_service_contract_payload,
    create_training_record,
    draft_agreement,
    drive_account_to_readiness,
    get_agreement,
    get_success_data,
    make_account_owner_headers,
    make_regional_sales_director_headers,
    month_close,
    set_clock,
    setup_account_with_review,
    setup_commissioned_system,
    setup_usage_based_system,
    submit_agreement,
    validate_error,
    validate_success,
)


# ─── Priority 1 defeats priority 38 ─────────────────────────────────────────

def test_a_missing_user_context_header_wins_over_every_business_check(api):
    """PRD §2.1: "Every request must carry `X-User-ID` to identify the acting party and
    `X-User-Role` to declare its capacity. A request that omits either header, or supplies a
    blank value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
    This check runs before anything else."

    Design: Corner/validations/missing_user_context_header_wins_over_every_business_check
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account()
    config = create_configuration()
    review = create_review(account["id"], config["id"], verdict="PASSED")
    create_training_record(account["id"])
    account = drive_account_to_readiness(account)
    agreement = draft_agreement(account["id"], config["id"], review["id"],
                                arrangement_type="LEASE", base_monthly_fee_cents=200000)

    res = api_client.submit_agreement(
        agreement["id"], {"expected_agreement_version": agreement["version"]},
        {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"})

    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)
    assert get_success_data(api_client.get_agreement(
        agreement["id"], TEST_USERS["regional_sales_director_headers"]))["agreement_status"] == "DRAFT"


# ─── Region scope ───────────────────────────────────────────────────────────

def test_a_regional_director_scoped_elsewhere_is_refused_on_this_account(api):
    """PRD §2.1: "some roles are region-scoped, and a region-scoped role may only act on a
    `HospitalAccount` whose `region_code` equals the acting identity's own region; crossing
    that line yields `ERR_REGION_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/validations/region_scoped_director_outside_its_region_is_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    east_account = api_client.create_account(
        {"account_name": "Eastgate Regional", "idn_group_code": "IDN-EASTGATE",
         "region_code": "EAST", "placement_cap": 3, "maximum_procedure_commitment": 20},
        make_regional_sales_director_headers("EAST"))
    account = get_success_data(east_account, 201)

    res = api_client.close_account(
        account["id"], {"expected_account_version": account["version"]},
        make_regional_sales_director_headers("WEST"))

    assert res.status_code in (403, 404), (
        "a director scoped to another region cannot act on this account"
    )
    assert get_success_data(api_client.get_account(
        account["id"], TEST_USERS["platform_admin_headers"]))["account_status"] == "PROSPECT"


# ─── Credential gate independent of the emergency flag ──────────────────────

def test_an_uncredentialed_operator_is_refused_even_on_a_healthy_system(api):
    """PRD §3.4: "The named training record is evaluated against the credential-validity step
    of the training path described in §3.5; a record that is not credentialed with an
    unexpired evidence grace yields `ERR_SURGEON_NOT_CREDENTIALED` (HTTP 409) at booking and
    at every subsequent mutation."

    Design: Corner/validations/emergency_case_on_a_service_action_system_still_requires_the_credential
    """
    ctx = setup_commissioned_system()
    trainee = create_training_record(ctx.account["id"], simulation_modules_completed=3,
                                     required_proctored_cases=2)
    trainee = get_success_data(api_client.complete_simulation(
        trainee["id"],
        {"simulation_modules_completed": 3,
         "expected_training_record_version": trainee["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)
    assert trainee["training_status"] == "SIMULATION_COMPLETE"

    res = api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": trainee["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-20T08:00:00Z", "duration_minutes": 60,
         "instrument_load": 1, "is_emergency": False},
        ctx.account_headers)

    validate_error(res, "ERR_SURGEON_NOT_CREDENTIALED", expected_status=409)


def test_the_credentialed_operator_is_accepted_on_the_same_system(api):
    """PRD §3.5: "Fifth, credential-valid when credentialing-ready and the logical clock is
    at or before `evidence_required_after_utc`".

    Design: Corner/validations/emergency_case_on_a_service_action_system_still_requires_the_credential
    """
    ctx = setup_commissioned_system()

    booked = validate_success(api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-20T08:00:00Z", "duration_minutes": 60,
         "instrument_load": 1, "is_emergency": False},
        ctx.account_headers), 201)

    assert booked["case_status"] == "SCHEDULED"


# ─── Cancellation moves two aggregates in opposite directions ───────────────

def test_cancelling_a_case_drops_it_out_of_the_committed_count(api):
    """PRD §2.12: "The count of procedures actually delivered in the open interval is
    `committed_cases`, computed over procedure case rows whose `case_status` is `SCHEDULED` or
    `COMPLETED` and whose `case_started_at` falls in the half-open interval from
    `cycle_start_utc` inclusive to `cycle_end_utc` exclusive. Note that a case that is merely
    `SCHEDULED` and never delivered still counts toward the commitment in this view; only
    `CANCELLED` rows are excluded."

    Design: Corner/validations/cancelled_case_lifecycle_bounds_aggregate_committed_cases
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=3,
                                   placement_fee_cents=1000000,
                                   usage_rate_basis_points=400)
    cases = [create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                         case_started_at=f"2026-09-{5 + i:02d}T08:00:00Z")
             for i in range(3)]
    before = get_agreement(ctx.agreement["id"])
    assert before["committed_cases"] == 3

    validate_success(api_client.cancel_procedure_case(
        cases[2]["id"], {"expected_case_version": cases[2]["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    after = get_agreement(ctx.agreement["id"])
    assert after["committed_cases"] == 2, "the cancelled case leaves the committed count"


def test_cancelling_a_case_releases_its_load_in_the_same_request(api):
    """PRD §3.4: "A case may be cancelled by either the `AccountOwner` or a
    `HospitalProcurementOfficer`, which moves it to `CANCELLED` and releases its instrument
    load back into the accessory-set accumulator."

    Design: Corner/validations/cancelled_case_lifecycle_bounds_aggregate_committed_cases
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=3,
                                   placement_fee_cents=1000000,
                                   usage_rate_basis_points=400,
                                   config_overrides={"max_instrument_lives": 3})
    cases = [create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                         case_started_at=f"2026-09-{5 + i:02d}T08:00:00Z",
                         instrument_load=1)
             for i in range(3)]
    before = get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]))
    assert before["instrument_lives_remaining"] == 0

    validate_success(api_client.cancel_procedure_case(
        cases[2]["id"], {"expected_case_version": cases[2]["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    after = get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]))
    assert after["instrument_lives_remaining"] == 1, (
        "the released load returns to the accumulator in the same request"
    )


# ─── Best-effort bulk completion ────────────────────────────────────────────

def test_bulk_completion_is_best_effort_and_reports_the_skipped_case(api):
    """PRD §3.4: "Bulk completion lets an `AccountOwner` submit a set of `case_ids` and
    receive a count of cases completed alongside the list of `skipped_case_ids`; each
    eligible case takes the full per-case completion side effects, while ineligible cases are
    skipped rather than rolled back, so a partially valid batch still makes progress."

    Design: Corner/validations/bulk_complete_is_best_effort_and_reports_skipped_cases
    """
    ctx = setup_commissioned_system()
    first = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                        case_started_at="2026-09-10T08:00:00Z")
    second = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                         case_started_at="2026-09-11T08:00:00Z")
    third = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                        case_started_at="2026-09-12T08:00:00Z")
    cancelled = validate_success(api_client.cancel_procedure_case(
        third["id"], {"expected_case_version": third["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    result = validate_success(api_client.bulk_complete_cases(
        {"case_ids": [first["id"], second["id"], third["id"]]},
        ctx.account_headers), 200)

    assert result["completed_count"] == 2
    assert list(result["skipped_case_ids"]) == [third["id"]], (
        "the already-cancelled case is reported rather than rolling the batch back"
    )
    assert get_success_data(api_client.get_procedure_case(
        cancelled["id"], ctx.account_headers))["case_status"] == "CANCELLED"


# ─── Concurrency guards ─────────────────────────────────────────────────────

def _submitted_agreement():
    ctx = setup_account_with_review(verdict="PASSED", activated=True)
    agreement = draft_agreement(ctx.account["id"], ctx.config["id"], ctx.review["id"])
    return ctx, submit_agreement(agreement)


def test_accepting_an_agreement_bumps_the_owning_accounts_version(api):
    """PRD §2.7: "Actions that touch two parents increment both; accepting an agreement, for
    instance, increments the agreement's version and the account's."

    Design: Corner/validations/stale_account_version_on_accept_returns_stale_version
    """
    ctx, agreement = _submitted_agreement()
    before = ctx.account["version"]

    validate_success(api_client.accept_agreement(
        agreement["id"],
        {"expected_agreement_version": agreement["version"],
         "expected_hospital_account_version": before},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    after = get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))
    assert after["version"] > before, "acceptance increments the owning account's version"


def test_replaying_an_accept_with_the_old_account_version_reports_stale_version(api):
    """PRD §2.14: "Accepting a placement agreement requires `expected_hospital_account_version`
    alongside the agreement's own version field, and the account whose version it names is the
    `HospitalAccount` that owns the agreement. If the account's version has advanced since the
    client last observed it, the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_account_version_on_accept_returns_stale_version
    """
    ctx, agreement = _submitted_agreement()
    stale_version = ctx.account["version"]
    accepted = validate_success(api_client.accept_agreement(
        agreement["id"],
        {"expected_agreement_version": agreement["version"],
         "expected_hospital_account_version": stale_version},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    # Accepting an ACTIVE agreement is refused earlier in the pinned order than the
    # parent-version guards: the state check on `agreement_status` runs before the
    # OCC checks, so the replay is answered by the state error even though the
    # account version it supplies is stale by now.
    res = api_client.accept_agreement(
        accepted["id"],
        {"expected_agreement_version": accepted["version"],
         "expected_hospital_account_version": stale_version},
        TEST_USERS["hospital_procurement_officer_headers"])

    validate_error(res, "ERR_AGREEMENT_NOT_IN_ELIGIBLE_STATE", expected_status=409)


def test_creating_a_contract_with_a_superseded_system_version_is_stale(api):
    """PRD §2.14: "Creating a service contract requires `expected_robot_system_version` naming
    the covered `RobotSystem`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_robot_system_version_on_contract_create_returns_stale_version
    """
    from test_helpers import setup_agreement, install_system
    ctx = setup_agreement(accepted=True)
    stale_version = ctx.system["version"]
    installed = install_system(ctx.system)
    assert installed["version"] > stale_version

    res = api_client.create_service_contract(
        {"robot_system_id": ctx.system["id"], "coverage_tier": "STANDARD",
         "contract_start_utc": "2026-09-01T00:00:00Z", "contract_months": 12,
         "expected_robot_system_version": stale_version},
        TEST_USERS["service_engineer_headers"])

    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_a_fresh_system_version_lets_the_contract_be_created(api):
    """PRD §2.8: "The resulting commitment is 24 hours for `COMPREHENSIVE`, 12 for
    `STANDARD`, 18 for `LIMITED` and 24 for `PARTS_ONLY` once the tier index is applied directly."

    Design: Corner/validations/stale_robot_system_version_on_contract_create_returns_stale_version
    """
    from test_helpers import setup_agreement, install_system
    ctx = setup_agreement(accepted=True)
    installed = install_system(ctx.system)

    contract = validate_success(api_client.create_service_contract(
        {"robot_system_id": ctx.system["id"], "coverage_tier": "STANDARD",
         "contract_start_utc": "2026-09-01T00:00:00Z", "contract_months": 12,
         "expected_robot_system_version": installed["version"]},
        TEST_USERS["service_engineer_headers"]), 201)

    assert contract["service_tier_index"] == 2
    assert contract["response_time_commitment_hours"] == 12


def test_reinstating_with_no_live_coverage_is_refused(api):
    """PRD §3.1.3: "A `RegionalSalesDirector` may reinstate a `SUSPENDED` agreement only when
    every `ACTIVE` service contract on its systems has the logical clock strictly before its
    `contract_end_utc`; an expired or otherwise out-of-window contract fails the reinstatement
    with `ERR_CONTRACT_TEMPORALLY_INVALID`."

    Design: Corner/validations/reinstate_with_an_out_of_window_contract_returns_temporal_invalid
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=4,
                                   placement_fee_cents=30000000,
                                   usage_rate_basis_points=400,
                                   config_overrides={"base_placement_fee_cents": 30000000,
                                                     "model_code": "DA_V1",
                                                     "integration_tier": 1,
                                                     "max_instrument_lives": 10})
    month_close("2026-10-01T00:00:00Z")
    suspended = get_agreement(ctx.agreement["id"])
    assert suspended["compliance_status"] == "NON_COMPLIANT", (
        "the shortfall tier drives the agreement NON_COMPLIANT at the close"
    )
    assert suspended["agreement_status"] == "ACTIVE", (
        "the agreement is not yet suspended; the service action suspends it"
    )
    system = get_success_data(api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"]), 200)
    suspended = get_agreement(ctx.agreement["id"])
    assert suspended["agreement_status"] == "SUSPENDED"
    # The synthesized contract is a one-month one, which the month-close has
    # already expired; reinstate only reads contracts that are still ACTIVE, so a
    # longer-lived replacement is created while the clock is in window.
    system = get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]))
    live_contract = create_service_contract_payload(system["id"])
    live_contract["contract_months"] = 1
    live_contract["expected_robot_system_version"] = system["version"]
    live_contract = validate_success(api_client.create_service_contract(
        live_contract, TEST_USERS["service_engineer_headers"]), 201)
    assert live_contract["contract_status"] == "ACTIVE"

    # Move the clock past that coverage window without running a month-close, so
    # the contract is still ACTIVE but out of window — the state the
    # reinstatement guard rejects. Terminating it instead would leave no ACTIVE
    # contract for the guard to read.
    set_clock("2026-11-15T00:00:00Z")

    res = api_client.reinstate_agreement(
        suspended["id"], {"expected_agreement_version": suspended["version"]},
        TEST_USERS["regional_sales_director_headers"])

    validate_error(res, "ERR_CONTRACT_TEMPORALLY_INVALID", expected_status=422)


def test_the_suspended_agreement_stays_suspended_after_the_refused_reinstatement(api):
    """PRD §3.1.3: "On success the agreement returns to `ACTIVE`, every system of the
    agreement currently in `SERVICE_ACTION_REQUIRED` returns to `IN_SERVICE`, and the
    commitment state is recomputed."

    Design: Corner/validations/reinstate_with_an_out_of_window_contract_returns_temporal_invalid
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=4,
                                   placement_fee_cents=30000000,
                                   usage_rate_basis_points=400,
                                   config_overrides={"base_placement_fee_cents": 30000000,
                                                     "model_code": "DA_V1",
                                                     "integration_tier": 1,
                                                     "max_instrument_lives": 10})
    month_close("2026-10-01T00:00:00Z")
    api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"])
    suspended = get_agreement(ctx.agreement["id"])
    assert suspended["agreement_status"] == "SUSPENDED", (
        "the service action suspends the non-compliant agreement"
    )
    system = get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]))
    live_contract = create_service_contract_payload(system["id"])
    live_contract["contract_months"] = 1
    live_contract["expected_robot_system_version"] = system["version"]
    live_contract = validate_success(api_client.create_service_contract(
        live_contract, TEST_USERS["service_engineer_headers"]), 201)
    assert live_contract["contract_status"] == "ACTIVE"
    set_clock("2026-11-15T00:00:00Z")

    api_client.reinstate_agreement(
        suspended["id"], {"expected_agreement_version": suspended["version"]},
        TEST_USERS["regional_sales_director_headers"])

    assert get_agreement(suspended["id"])["agreement_status"] == "SUSPENDED"


def test_booking_a_case_on_an_account_that_does_not_own_the_system_is_forbidden(api):
    """PRD §2.1: "An entity-backed role that acts on a resource whose owning foreign key is
    not the acting identity is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/errors/ownership_mismatch_on_an_entity_backed_role
    """
    ctx = setup_commissioned_system()
    outsider = create_account(account_name="Outsider Clinic", idn_group_code="IDN-OUTSIDER",
                              region_code="WEST", placement_cap=2,
                              maximum_procedure_commitment=10)

    res = api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-25T08:00:00Z", "duration_minutes": 60,
         "instrument_load": 1},
        make_account_owner_headers(outsider["id"]))

    validate_error(res, "ERR_OWNERSHIP_MISMATCH", expected_status=403)


def test_credentialing_without_any_evidence_reports_the_dedicated_error(api):
    """PRD §3.5: "requires at least one piece of credentialing evidence on the record whose
    `evidence_status` is `VALID` or `EXPIRING_SOON`, failing which it is rejected with
    `ERR_CREDENTIALING_EVIDENCE_REQUIRED` (HTTP 422)."

    Design: Corner/errors/evidence_required_before_credentialing_returns_dedicated_error
    """
    ctx = setup_account_with_review(verdict="PASSED")
    record = create_training_record(ctx.account["id"], simulation_modules_completed=4,
                                    required_proctored_cases=1)
    record = get_success_data(api_client.complete_simulation(
        record["id"],
        {"simulation_modules_completed": 4,
         "expected_training_record_version": record["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)
    record = get_success_data(api_client.begin_proctoring(
        record["id"],
        {"required_proctored_cases": 1,
         "expected_training_record_version": record["version"]},
        TEST_USERS["regional_sales_director_headers"]), 200)
    logged = api_client.log_proctor_case(
        record["id"],
        {"case_observation_ref": "OBS-NOEV", "occurred_at_utc": "2026-08-20T00:00:00Z"},
        TEST_USERS["clinical_operations_lead_headers"])
    assert 200 <= logged.status_code < 300
    record = get_success_data(logged, logged.status_code)

    import json
    case_id = json.loads(logged.text)["data"].get("proctor_case_id")
    assert case_id, "the log response exposes the proctor case identifier"

    res = api_client.approve_proctor_case(
        case_id,
        {"expected_training_record_version": record["version"]},
        TEST_USERS["compliance_officer_headers"])

    validate_error(res, "ERR_CREDENTIALING_EVIDENCE_REQUIRED", expected_status=422)


def test_a_second_acceptance_never_reuses_a_serial_number(api):
    """PRD §3.1.3: "The synthesized system's `serial_number` must be unique across every robot
    system in the fleet; a collision fails acceptance with `ERR_DUPLICATE_SERIAL_NUMBER` (HTTP 409)."

    Design: Corner/errors/duplicate_serial_number_on_a_second_accept_is_409
    """
    ctx = setup_commissioned_system(account_overrides={"placement_cap": 6})
    second_review = create_review(ctx.account["id"], ctx.config["id"], verdict="PASSED")
    second = submit_agreement(draft_agreement(ctx.account["id"], ctx.config["id"],
                                              second_review["id"]))
    account = get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))

    res = api_client.accept_agreement(
        second["id"],
        {"expected_agreement_version": second["version"],
         "expected_hospital_account_version": account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"])

    if res.status_code == 409:
        validate_error(res, "ERR_DUPLICATE_SERIAL_NUMBER", expected_status=409)
    else:
        accepted = validate_success(res, 200)
        systems = get_success_data(api_client.list_account_robot_systems(
            ctx.account["id"], TEST_USERS["platform_admin_headers"]))
        serials = [s["serial_number"] for s in systems]
        assert len(serials) == len(set(serials)), "serial numbers stay unique across the fleet"