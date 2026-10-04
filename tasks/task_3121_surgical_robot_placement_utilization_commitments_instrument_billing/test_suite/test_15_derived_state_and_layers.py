"""Cascading side effects, derived-field reconciliation, feature entitlement and
immediate-read consistency."""

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_monetary_integer_cents,
    create_case,
    create_credentialed_surgeon,
    create_review,
    create_software_deployment_payload,
    get_agreement,
    get_success_data,
    month_close,
    set_clock,
    setup_account_with_review,
    setup_agreement,
    setup_commissioned_system,
    submit_agreement,
    draft_agreement,
    validate_error,
    validate_success,
)


def test_installation_alone_opens_no_utilization_cycle(api):
    """PRD §3.2: "A `UtilizationCycle` is opened for the system's current commitment
    interval: if none exists for that interval it is created, and if one does exist it is
    reused as the open cycle rather than duplicated."

    Design: Corner/cross_cutting_complexity_layers/cascading_effects_from_commission_are_ordered_and_complete
    """
    ctx = setup_agreement(accepted=True)
    installed = validate_success(api_client.install_robot_system(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)

    assert installed["service_status"] == "INSTALLED"
    assert installed["current_utilization_cycle_id"] is None, (
        "installation mutates only the system, leaving the reporting cycle unopened"
    )


def test_commissioning_opens_exactly_one_cycle_for_the_commitment_interval(api):
    """PRD §3.2: "On success the system moves to `IN_SERVICE`. A `UtilizationCycle` is opened
    for the system's current commitment interval: if none exists for that interval it is
    created, and if one does exist it is reused as the open cycle rather than duplicated."

    Design: Corner/cross_cutting_complexity_layers/cascading_effects_from_commission_are_ordered_and_complete
    """
    ctx = setup_agreement(accepted=True)
    # Commissioning requires a CREDENTIALED surgeon on the account; the base
    # agreement fixture keeps an uncredentialed record, so credential one here.
    create_credentialed_surgeon(ctx.account["id"])
    installed = validate_success(api_client.install_robot_system(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)
    commissioned = validate_success(api_client.commission_robot_system(
        installed["id"], {"expected_robot_system_version": installed["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)

    assert commissioned["service_status"] == "IN_SERVICE"
    assert commissioned["current_utilization_cycle_id"] is not None
    cycles = get_success_data(api_client.list_system_utilization_cycles(
        commissioned["id"], TEST_USERS["platform_admin_headers"]), 200)
    assert len(cycles) == 1, "the cycle is not opened twice"
    assert cycles[0]["utilization_band"] == "UNDERUTILIZED"
    assert cycles[0]["reporting_period_index"] == 0


def test_expansion_eligibility_flips_false_when_the_system_leaves_service(api):
    """PRD §3.7: "A system is expansion-eligible when its `service_status` is `IN_SERVICE`, and
    its `ACTIVE` service contract carries a `service_tier_index` of at least 2 — that is,
    `STANDARD` or `COMPREHENSIVE` coverage but not `LIMITED` or `PARTS_ONLY` — and the
    completed-case count of its current utilization cycle has reached the parent agreement's
    `minimum_procedures_per_cycle`."

    Design: Corner/cross_cutting_complexity_layers/derived_expansion_eligible_reconciles_after_every_input_moves
    """
    ctx = setup_commissioned_system()
    assert ctx.contract["coverage_tier"] == "COMPREHENSIVE"

    in_action = get_success_data(api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    assert in_action["service_status"] == "SERVICE_ACTION_REQUIRED"
    assert in_action["expansion_eligible"] is False
    assert get_success_data(api_client.get_robot_system(
        ctx.system["id"], TEST_USERS["service_engineer_headers"]))["expansion_eligible"] is False


def test_expansion_eligibility_returns_after_service_is_restored(api):
    """PRD §3.2: "On success the system returns to `IN_SERVICE` and the posture recomputes —
    which, if no other system is in service-action-required, lets the account out of
    `EXPANSION_BLOCKED`."

    Design: Corner/cross_cutting_complexity_layers/derived_expansion_eligible_reconciles_after_every_input_moves
    """
    ctx = setup_commissioned_system()
    in_action = get_success_data(api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"]), 200)
    assert in_action["expansion_eligible"] is False

    restored = validate_success(api_client.restore_system_service(
        in_action["id"], {"expected_robot_system_version": in_action["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    assert restored["service_status"] == "IN_SERVICE"
    assert restored["expansion_eligible"] is True, (
        "the coverage tier and the vacuous utilization conjunct still hold"
    )


def _entitlement_scenario():
    """A commissioned system on a configuration with two releases and two entitlements."""
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_account_with_review(verdict="PASSED", activated=True)
    # Commissioning requires at least one CREDENTIALED surgeon on the account
    # (ERR_NO_CREDENTIALED_SURGEON), so the scenario credentials one.
    create_credentialed_surgeon(ctx.account["id"])
    config = get_success_data(api_client.update_configuration(
        ctx.config["id"],
        {"feature_entitlements": [{"feature_code": "FIREFLY", "min_release_index": 1},
                                  {"feature_code": "FORCE_FEEDBACK", "min_release_index": 3}]},
        TEST_USERS["platform_admin_headers"]), 200)
    release_one = get_success_data(api_client.create_software_release(
        config["id"], {"release_index": 1, "feature_codes": ["FIREFLY"]},
        TEST_USERS["platform_admin_headers"]), 201)
    release_three = get_success_data(api_client.create_software_release(
        config["id"], {"release_index": 3, "feature_codes": ["FORCE_FEEDBACK"]},
        TEST_USERS["platform_admin_headers"]), 201)
    agreement = submit_agreement(draft_agreement(
        ctx.account["id"], config["id"], ctx.review["id"],
        arrangement_type="LEASE", base_monthly_fee_cents=200000,
        minimum_procedures_per_cycle=0, interval_months=1,
        lease_monthly_amount_cents=900000))
    account = get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))
    accepted = get_success_data(api_client.accept_agreement(
        agreement["id"],
        {"expected_agreement_version": agreement["version"],
         "expected_hospital_account_version": account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)
    system = get_success_data(api_client.list_agreement_robot_systems(
        accepted["id"], TEST_USERS["regional_sales_director_headers"]))[0]
    system = validate_success(api_client.install_robot_system(
        system["id"], {"expected_robot_system_version": system["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)
    system = validate_success(api_client.commission_robot_system(
        system["id"], {"expected_robot_system_version": system["version"]},
        TEST_USERS["clinical_operations_lead_headers"]), 200)
    return system, release_one, release_three


def test_completing_a_deployment_raises_the_installed_index_and_entitles_one_feature(api):
    """PRD §3.5: "the deployment moves to `COMPLETED`, the release is marked deployed, the
    target system's `installed_software_release_index` is raised to the delivered release's
    index, and the system's `entitled_feature_codes` is recomputed to the feature codes of its
    configuration whose `min_release_index` has been reached by that installed index."

    Design: Corner/cross_cutting_complexity_layers/release_entitlement_reconciles_on_deployment_completion
    """
    system, release_one, _ = _entitlement_scenario()
    assert system["installed_software_release_index"] == 0
    assert system["entitled_feature_codes"] == []

    deployment = get_success_data(api_client.create_software_deployment(
        system["id"], create_software_deployment_payload(release_one["id"]),
        TEST_USERS["service_engineer_headers"]), 201)
    validate_success(api_client.complete_software_deployment(
        deployment["id"], {"expected_deployment_version": deployment["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    raised = get_success_data(api_client.get_robot_system(
        system["id"], TEST_USERS["service_engineer_headers"]))
    assert raised["installed_software_release_index"] == 1
    assert raised["entitled_feature_codes"] == ["FIREFLY"]


def test_a_release_of_a_higher_index_grows_the_entitled_set(api):
    """PRD §3.5: "the release's `release_index` must be strictly greater than the target
    system's `installed_software_release_index`, failing which the deployment is refused with
    `ERR_RELEASE_DOWNGRADE` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/release_entitlement_reconciles_on_deployment_completion
    """
    system, release_one, release_three = _entitlement_scenario()
    first = get_success_data(api_client.create_software_deployment(
        system["id"], create_software_deployment_payload(release_one["id"]),
        TEST_USERS["service_engineer_headers"]), 201)
    validate_success(api_client.complete_software_deployment(
        first["id"], {"expected_deployment_version": first["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    second = validate_success(api_client.create_software_deployment(
        system["id"], create_software_deployment_payload(
            release_three["id"],
            scheduled_window_start_utc="2026-09-20T00:00:00Z",
            scheduled_window_end_utc="2026-09-20T04:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)
    validate_success(api_client.complete_software_deployment(
        second["id"], {"expected_deployment_version": second["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    raised = get_success_data(api_client.get_robot_system(
        system["id"], TEST_USERS["service_engineer_headers"]))
    assert raised["installed_software_release_index"] == 3
    assert sorted(raised["entitled_feature_codes"]) == ["FIREFLY", "FORCE_FEEDBACK"]


def test_replaying_a_lower_release_after_the_upgrade_is_refused(api):
    """PRD §3.5: "the release's `release_index` must be strictly greater than the target
    system's `installed_software_release_index`, failing which the deployment is refused with
    `ERR_RELEASE_DOWNGRADE` (HTTP 409)."

    Design: Corner/cross_cutting_complexity_layers/release_entitlement_reconciles_on_deployment_completion
    """
    system, release_one, release_three = _entitlement_scenario()
    first = get_success_data(api_client.create_software_deployment(
        system["id"], create_software_deployment_payload(release_three["id"]),
        TEST_USERS["service_engineer_headers"]), 201)
    validate_success(api_client.complete_software_deployment(
        first["id"], {"expected_deployment_version": first["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    res = api_client.create_software_deployment(
        system["id"], create_software_deployment_payload(release_one["id"]),
        TEST_USERS["service_engineer_headers"])

    validate_error(res, "ERR_RELEASE_DOWNGRADE", expected_status=409)


def test_bulk_completion_partitions_the_requested_ids_without_overlap_or_omission(api):
    """PRD §3.4: "Bulk completion lets an `AccountOwner` submit a set of `case_ids` and
    receive a count of cases completed alongside the list of `skipped_case_ids`; each eligible
    case takes the full per-case completion side effects, while ineligible cases are skipped
    rather than rolled back".

    Design: Corner/cross_cutting_complexity_layers/bulk_completion_leaves_the_non_cancelled_cases_untouched
    """
    ctx = setup_commissioned_system()
    first = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                        case_started_at="2026-09-10T08:00:00Z")
    second = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                         case_started_at="2026-09-11T08:00:00Z")
    third = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                        case_started_at="2026-09-12T08:00:00Z")
    validate_success(api_client.cancel_procedure_case(
        third["id"], {"expected_case_version": third["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)

    result = validate_success(api_client.bulk_complete_cases(
        {"case_ids": [first["id"], second["id"], third["id"]]}, ctx.account_headers), 200)

    assert result["completed_count"] + len(result["skipped_case_ids"]) == 3
    assert list(result["skipped_case_ids"]) == [third["id"]]


def test_a_repeated_bulk_completion_skips_the_already_completed_cases(api):
    """PRD §3.4: "each eligible case takes the full per-case completion side effects, while
    ineligible cases are skipped rather than rolled back".

    Design: Corner/cross_cutting_complexity_layers/bulk_completion_leaves_the_non_cancelled_cases_untouched
    """
    ctx = setup_commissioned_system()
    first = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                        case_started_at="2026-09-10T08:00:00Z")
    second = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                         case_started_at="2026-09-11T08:00:00Z")
    validate_success(api_client.bulk_complete_cases(
        {"case_ids": [first["id"], second["id"]]}, ctx.account_headers), 200)

    replay = validate_success(api_client.bulk_complete_cases(
        {"case_ids": [first["id"], second["id"]]}, ctx.account_headers), 200)

    assert replay["completed_count"] == 0
    assert len(replay["skipped_case_ids"]) == 2, "completed cases are no longer eligible"


def test_month_close_advances_the_reporting_period_index(api):
    """PRD §2.11: "it carries `reporting_period_index`, initialized to 0 and advanced by one
    at each month-close run; that index drives the eligibility window for expansion reviews."

    Design: Corner/cross_cutting_complexity_layers/month_close_advanced_clock_rolls_cycles_and_bands
    """
    ctx = setup_commissioned_system()
    assert ctx.cycle["reporting_period_index"] == 0

    month_close("2026-10-05T00:00:00Z")

    after = get_success_data(api_client.get_utilization_cycle(
        ctx.cycle["id"], TEST_USERS["platform_admin_headers"]))
    assert after["reporting_period_index"] == 1


def test_month_close_returns_an_expired_acceptance_window_to_draft(api):
    """PRD §3.1.3: "If nobody accepts in time, the agreement returns to `DRAFT`
    automatically and `acceptance_expires_utc` is cleared."

    Design: Corner/cross_cutting_complexity_layers/month_close_advanced_clock_rolls_cycles_and_bands
    """
    ctx = setup_commissioned_system()
    second_review = create_review(ctx.account["id"], ctx.config["id"], verdict="PASSED")
    pending = submit_agreement(draft_agreement(
        ctx.account["id"], ctx.config["id"], second_review["id"],
        arrangement_type="LEASE", base_monthly_fee_cents=200000,
        lease_monthly_amount_cents=900000))
    assert pending["agreement_status"] == "PENDING_ACCEPTANCE"

    month_close("2026-10-05T00:00:00Z")

    after = get_agreement(pending["id"])
    assert after["agreement_status"] == "DRAFT", (
        "the clock moved past the acceptance expiry stamped at submit"
    )


def test_accepting_the_returned_agreement_reports_the_expired_window(api):
    """PRD §3.1.3: "the logical clock must be strictly before `acceptance_expires_utc` —
    otherwise `ERR_ACCEPTANCE_WINDOW_EXPIRED` (HTTP 409)".

    Design: Corner/cross_cutting_complexity_layers/month_close_advanced_clock_rolls_cycles_and_bands
    """
    ctx = setup_commissioned_system()
    second_review = create_review(ctx.account["id"], ctx.config["id"], verdict="PASSED")
    pending = submit_agreement(draft_agreement(
        ctx.account["id"], ctx.config["id"], second_review["id"],
        arrangement_type="LEASE", base_monthly_fee_cents=200000,
        lease_monthly_amount_cents=900000))
    # Move the clock past the acceptance window without running a month-close: a
    # close would itself return the expired agreement to DRAFT and clear the
    # window, so the accept would then meet the state check rather than the
    # window check this test pins.
    set_clock("2026-10-05T00:00:00Z")
    returned = get_agreement(pending["id"])
    assert returned["agreement_status"] == "PENDING_ACCEPTANCE"

    res = api_client.accept_agreement(
        returned["id"],
        {"expected_agreement_version": returned["version"],
         "expected_hospital_account_version": get_success_data(
             api_client.get_account(ctx.account["id"],
                                    TEST_USERS["platform_admin_headers"]))["version"]},
        TEST_USERS["hospital_procurement_officer_headers"])

    validate_error(res, "ERR_ACCEPTANCE_WINDOW_EXPIRED", expected_status=409)


def test_the_completion_response_itself_carries_the_recomputed_bill(api):
    """PRD §2.7: "Derived fields are mutations for these purposes. When a computed value on a
    parent is reconciled — the account's posture, an agreement's commitment state, a system's
    remaining instrument lives, a cycle's band, a contract's response commitment — the
    parent's `updated_at` is refreshed and its `version` incremented, even though no client
    asked for that specific change."

    Design: Corner/consistency_model/every_mutation_returns_fully_reconciled_state_immediately
    """
    ctx = setup_commissioned_system(config_overrides={"max_instrument_lives": 40})
    case = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                       case_started_at="2026-09-10T08:00:00Z", instrument_load=1)

    completed = validate_success(api_client.mark_case_completed(
        case["id"], {"expected_case_version": case["version"]}, ctx.account_headers), 200)

    assert completed["case_status"] == "COMPLETED"
    assert_monetary_integer_cents(completed["instrument_billing_cents"])
    assert completed["instrument_billing_cents"] == 125000, (
        "the response carries the recomputed amount with no follow-up read required"
    )


def test_the_derived_counts_agree_immediately_with_the_write(api):
    """PRD §2.11: "Two counts live on it: `scheduled_case_count` counts procedure cases on the
    system whose `case_started_at` falls inside the half-open interval from `cycle_start_utc`
    inclusive to `cycle_end_utc` exclusive, in any non-cancelled status; `completed_case_count`
    counts only those with `case_status` `COMPLETED` in the same window."

    Design: Corner/consistency_model/every_mutation_returns_fully_reconciled_state_immediately
    """
    ctx = setup_commissioned_system(config_overrides={"max_instrument_lives": 40})
    case = create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                       case_started_at="2026-09-10T08:00:00Z", instrument_load=1)
    validate_success(api_client.mark_case_completed(
        case["id"], {"expected_case_version": case["version"]}, ctx.account_headers), 200)

    cycle = get_success_data(api_client.get_current_utilization_cycle(
        ctx.system["id"], TEST_USERS["clinical_operations_lead_headers"]))
    assert cycle["completed_case_count"] == 1
    assert cycle["scheduled_case_count"] == 1

    agreement = get_agreement(ctx.agreement["id"])
    assert agreement["committed_cases"] == 1