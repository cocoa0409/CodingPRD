"""Engaging service providers, allocating statutory functions and activating the plan."""

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_ALLOCATION_ALREADY_ACKNOWLEDGED,
    ERR_ALLOCATION_WINDOW_OVERLAP,
    ERR_INVALID_AFFILIATION,
    ERR_INVALID_ALLOCATION_WINDOW,
    ERR_NAMED_FIDUCIARY_NOT_ACKNOWLEDGED,
    ERR_PLAN_ALREADY_ACTIVE,
    ERR_PROVIDER_NOT_REGISTERED,
    ERR_SERVICE_PROVIDER_NOT_FOUND,
    ERR_STALE_PLAN_VERSION,
    ERR_TRUSTEE_NOT_ACKNOWLEDGED,
    ERR_VALIDATION,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_instant_equals,
    assert_null_fields,
    assert_resource_shape,
    ids_of,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.fixtures import PlanContext
from test_helpers.test_users import (
    UNRESOLVABLE_SERVICE_PROVIDER_ID,
    regulator_headers,
    service_provider_headers,
)
from prd_bench_local_runner.testing import validate_error


def _unacknowledged_plan(api: ApiClient) -> PlanContext:
    """A DRAFT plan whose sponsor is still pending and whose two functions are unacknowledged."""
    provider = fixtures.pending_provider(api)
    plan = fixtures.draft_plan(api, provider)
    recordkeeper = fixtures.engage_provider(
        api, provider["id"], f.recordkeeper_payload(plan["id"])
    )
    trustee = fixtures.engage_provider(
        api, provider["id"], f.trustee_payload(plan["id"])
    )
    plan_ctx = PlanContext(
        provider=provider, plan=plan, recordkeeper=recordkeeper, trustee=trustee
    )
    plan_ctx.named_fiduciary_allocation = fixtures.allocate_role(
        api, plan_ctx, recordkeeper["id"], k.FIDUCIARY_NAMED_FIDUCIARY_3_16
    )
    plan_ctx.trustee_allocation = fixtures.allocate_role(
        api, plan_ctx, trustee["id"], k.FIDUCIARY_TRUSTEE_403A
    )
    plan_ctx.refresh(api)
    return plan_ctx


def test_engaged_provider_gets_server_minted_system_fields(api: ApiClient):
    """
    The server mints the identity and the counters, and a trustee still starts
    without a fiduciary function.

    "Newly engaged providers open with `holds_fiduciary_role` false."

    "Priority 7 is request shape — required fields present, correct types,
    declared enum members, declared integer ranges, ISO-8601 date and datetime
    formats, and pagination bounds — reported as `ERR_VALIDATION`; unknown
    fields in a body are ignored rather than rejected."

    Design: Corner/entities/corner_system_fields_generated_on_service_provider_create
    """
    provider = fixtures.registered_provider(api)
    plan = fixtures.draft_plan(api, provider)
    headers = fixtures.plan_provider_headers(provider["id"])

    payload = f.trustee_payload(plan["id"])
    payload["id"] = UNRESOLVABLE_SERVICE_PROVIDER_ID
    payload["version"] = 99
    trustee = validate_created(api.create_service_provider(payload, headers))

    assert_resource_shape(trustee, "ServiceProvider")
    assert trustee["id"] != UNRESOLVABLE_SERVICE_PROVIDER_ID, (
        "A client-supplied id must be ignored, not honoured"
    )
    assert_fields(
        trustee,
        legal_name=k.TRUSTEE_LEGAL_NAME,
        provider_type=k.PROVIDER_TYPE_TRUSTEE,
        revenue_sharing_bps=k.TRUSTEE_BPS,
        direct_fee_cents_per_participant=k.TRUSTEE_FEE_CENTS,
        holds_fiduciary_role=False,
        version=1,
    )
    assert_null_fields(trustee, "affiliated_service_provider_id")
    assert_instant(trustee["created_at"], "created_at")
    assert trustee["created_at"] == trustee["updated_at"], (
        "A freshly engaged provider must carry created_at == updated_at"
    )

    read_back = validate_single(api.get_service_provider(trustee["id"], headers))
    assert_fields(read_back, id=trustee["id"], version=1)


def test_undeclared_enum_members_and_out_of_range_integers_are_rejected(api: ApiClient):
    """
    Enum closure and declared integer ranges are input checks, so they bite on a
    plan that has not even been activated.

    "states the `plan_year` under test as an integer between 2020 and 2030
    inclusive"

    "its `provider_type` — one of `RECORDKEEPER`, `TPA`, `TRUSTEE`,
    `INVESTMENT_MANAGER` or `AUDITOR_FIRM` —"

    Design: Corner/entities/corner_invalid_enum_and_range_inputs_rejected
    """
    provider = fixtures.registered_provider(api)
    plan = fixtures.draft_plan(api, provider)
    headers = fixtures.plan_provider_headers(provider["id"])

    validate_error(
        api.create_compliance_test(
            f.compliance_test_payload(plan["id"], plan_year=2019), headers
        ),
        ERR_VALIDATION,
        expected_status=422,
    )
    validate_error(
        api.create_compliance_test(
            f.compliance_test_payload(plan["id"], test_type="TOP_HEAVY"), headers
        ),
        ERR_VALIDATION,
        expected_status=422,
    )
    validate_error(
        api.create_service_provider(
            f.recordkeeper_payload(plan["id"], provider_type="CUSTODIAN"), headers
        ),
        ERR_VALIDATION,
        expected_status=422,
    )

    validate_collection(
        api.list_plan_service_providers(plan["id"], headers), expected_total=0
    )
    validate_collection(
        api.list_plan_compliance_tests(plan["id"], headers), expected_total=0
    )


def test_affiliation_must_name_a_provider_on_the_same_plan(api: ApiClient):
    """
    The affiliation link is confined to one plan, and the foreign-key check runs
    ahead of the business rule.

    "An optional `affiliated_service_provider_id` links the firm to a commonly
    controlled provider on the same plan; when supplied it must reference a
    service provider engaged on that same plan and must not be the new row's own
    identifier, and a violation of either condition is rejected with
    `ERR_INVALID_AFFILIATION`."

    Design: Corner/validations/corner_affiliation_across_plans_rejected
    """
    provider = fixtures.registered_provider(api)
    plan = fixtures.draft_plan(api, provider)
    other_plan = validate_created(
        api.create_plan_document(
            f.second_plan_document_payload(provider["id"]),
            fixtures.plan_provider_headers(provider["id"]),
        )
    )
    headers = fixtures.plan_provider_headers(provider["id"])

    elsewhere = validate_created(
        api.create_service_provider(
            f.recordkeeper_payload(
                other_plan["id"], legal_name="Otherplan Recordkeeping Inc"
            ),
            headers,
        )
    )
    recordkeeper = validate_created(
        api.create_service_provider(f.recordkeeper_payload(plan["id"]), headers)
    )

    cross_plan = api.create_service_provider(
        f.trustee_payload(
            plan["id"],
            legal_name="Northgate Trust Services Inc",
            affiliated_service_provider_id=elsewhere["id"],
        ),
        headers,
    )
    validate_error(cross_plan, ERR_INVALID_AFFILIATION, expected_status=422)

    unresolvable = api.create_service_provider(
        f.trustee_payload(
            plan["id"],
            legal_name="Northgate Trust Services Inc",
            affiliated_service_provider_id=UNRESOLVABLE_SERVICE_PROVIDER_ID,
        ),
        headers,
    )
    validate_error(unresolvable, ERR_SERVICE_PROVIDER_NOT_FOUND, expected_status=404)

    accepted = validate_created(
        api.create_service_provider(
            f.trustee_payload(
                plan["id"],
                legal_name="Northgate Trust Services Inc",
                affiliated_service_provider_id=recordkeeper["id"],
            ),
            headers,
        )
    )
    assert_fields(accepted, affiliated_service_provider_id=recordkeeper["id"])

    affiliates, _ = validate_collection(
        api.list_service_provider_affiliates(
            recordkeeper["id"], headers, limit=10, offset=0
        ),
        expected_total=1,
        expected_len=1,
    )
    assert ids_of(affiliates) == [accepted["id"]], (
        "The reverse direction of the affiliation link must be navigable"
    )


def test_new_entities_open_in_their_declared_initial_states(api: ApiClient):
    """
    Three machines are probed at their creation instant, and an allocation's
    initial state is not a distinct pending value.

    "A new allocation opens with `status` `ALLOCATED`, `acknowledged_at`,
    `acknowledgment_statement`, `revoked_at` and `revoked_reason` all null, and
    it supersedes the incumbent: when the new allocation's `effective_from` is
    strictly later than the incumbent's `effective_from`, the incumbent moves
    from `ALLOCATED` to `REVOKED`, has `revoked_at` stamped from the logical
    clock and `revoked_reason` set to `SUPERSEDED_BY_NEW_ALLOCATION`, and has
    its own `version` incremented; the outgoing firm's `holds_fiduciary_role` is
    then recomputed, as is the incoming firm's, and the plan document's
    `version` is incremented by one."

    "A firm's `holds_fiduciary_role` is true exactly when at least one
    allocation naming it is in `ALLOCATED` status."

    Design: Corner/state_machines/corner_new_entities_start_in_declared_initial_states
    """
    provider = fixtures.registered_provider(api)
    plan = fixtures.draft_plan(api, provider)
    recordkeeper = fixtures.engage_provider(
        api, provider["id"], f.recordkeeper_payload(plan["id"])
    )
    plan_ctx = PlanContext(
        provider=provider, plan=plan, recordkeeper=recordkeeper, trustee=recordkeeper
    )
    headers = plan_ctx.provider_headers

    plan_ctx.refresh(api)
    allocation = validate_created(
        api.create_fiduciary_role_allocation(
            f.fiduciary_allocation_payload(
                plan["id"],
                recordkeeper["id"],
                k.FIDUCIARY_NAMED_FIDUCIARY_3_16,
                plan_ctx.plan_version,
            ),
            headers,
        )
    )

    assert_resource_shape(allocation, "FiduciaryRoleAllocation")
    assert_fields(allocation, status=k.ALLOCATION_ALLOCATED, version=1)
    assert_null_fields(
        allocation,
        "acknowledged_at",
        "acknowledgment_statement",
        "revoked_at",
        "revoked_reason",
    )

    read_provider = validate_single(
        api.get_plan_provider(provider["id"], regulator_headers())
    )
    assert_fields(read_provider, registration_status=k.PROVIDER_REGISTERED)

    read_plan = validate_single(api.get_plan_document(plan["id"], headers))
    assert_fields(read_plan, status=k.PLAN_DRAFT)
    assert_null_fields(read_plan, "effective_date")

    firm = validate_single(api.get_service_provider(recordkeeper["id"], headers))
    assert_fields(firm, holds_fiduciary_role=True)


def test_activation_gate_fails_three_ways_in_strict_priority_order(api: ApiClient):
    """
    Every activation precondition lives on a sibling row, and the losing checks
    stay hidden until the winner is repaired.

    "Activation is a **guarded** transition whose entire gate lives on sibling
    entities rather than on the plan document itself, and it moves `status` from
    `DRAFT` to `ACTIVE`, which is terminal."

    "Priorities 24 through 30 are the safety and regulatory gates, in this
    order: `ERR_FIDELITY_BOND_BELOW_FLOOR`, `ERR_PROVIDER_NOT_REGISTERED`,
    `ERR_NAMED_FIDUCIARY_NOT_ACKNOWLEDGED`, `ERR_TRUSTEE_NOT_ACKNOWLEDGED`,
    `ERR_PLAN_COMPLIANCE_FROZEN`, `ERR_PLAN_LEVEL_TEST_OUTSTANDING`,
    `ERR_AUDIT_OPINION_UNACCEPTABLE`."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_gated_by_provider_registration_and_two_acknowledged_roles
    """
    plan_ctx = _unacknowledged_plan(api)
    version_before = plan_ctx.plan_version

    first = api.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers)
    validate_error(first, ERR_PROVIDER_NOT_REGISTERED, expected_status=409)

    validate_single(
        api.register_plan_provider(
            plan_ctx.provider_id, f.register_provider_payload(), regulator_headers()
        )
    )

    second = api.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers)
    validate_error(second, ERR_NAMED_FIDUCIARY_NOT_ACKNOWLEDGED, expected_status=409)

    fixtures.acknowledge_role(
        api, plan_ctx.named_fiduciary_allocation, k.NAMED_FIDUCIARY_ACKNOWLEDGMENT
    )

    third = api.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers)
    validate_error(third, ERR_TRUSTEE_NOT_ACKNOWLEDGED, expected_status=409)

    still_draft = plan_ctx.refresh(api)
    assert_fields(still_draft, status=k.PLAN_DRAFT, version=version_before)
    assert_null_fields(still_draft, "effective_date")


def test_activation_succeeds_only_after_the_third_sibling_is_repaired(api: ApiClient):
    """
    The fourth attempt is the first one with nothing left to refuse it.

    "and finally it must have an `ALLOCATED` allocation for the `TRUSTEE_403A`
    function whose `acknowledged_at` is set, failing which it is rejected with
    `ERR_TRUSTEE_NOT_ACKNOWLEDGED`."

    "On success the plan's `effective_date` is set to the logical-clock calendar
    date and its `version` is incremented by one."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_gated_by_provider_registration_and_two_acknowledged_roles
    """
    plan_ctx = _unacknowledged_plan(api)
    version_before = plan_ctx.plan_version

    validate_error(
        api.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers),
        ERR_PROVIDER_NOT_REGISTERED,
    )
    validate_single(
        api.register_plan_provider(
            plan_ctx.provider_id, f.register_provider_payload(), regulator_headers()
        )
    )
    named = fixtures.acknowledge_role(
        api, plan_ctx.named_fiduciary_allocation, k.NAMED_FIDUCIARY_ACKNOWLEDGMENT
    )
    trustee_allocation = fixtures.acknowledge_role(
        api, plan_ctx.trustee_allocation, k.TRUSTEE_ACKNOWLEDGMENT
    )

    activated = validate_single(
        api.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers)
    )
    assert_fields(
        activated,
        status=k.PLAN_ACTIVE,
        effective_date=k.DEFAULT_CLOCK_DATE,
        version=version_before + 1,
    )

    assert_fields(named, status=k.ALLOCATION_ALLOCATED, version=2)
    assert_fields(trustee_allocation, status=k.ALLOCATION_ALLOCATED, version=2)
    assert_instant_equals(named["acknowledged_at"], k.DEFAULT_CLOCK, "acknowledged_at")
    assert_instant_equals(
        trustee_allocation["acknowledged_at"], k.DEFAULT_CLOCK, "acknowledged_at"
    )

    headers = plan_ctx.provider_headers
    for firm_id in (plan_ctx.recordkeeper_id, plan_ctx.trustee_id):
        firm = validate_single(api.get_service_provider(firm_id, headers))
        assert_fields(firm, holds_fiduciary_role=True)


def test_second_acknowledge_and_second_activate_are_both_refused(api: ApiClient):
    """
    Neither repeat trigger is idempotent, and neither refused call overwrites
    what the first one recorded.

    "Acknowledging twice, or acknowledging an allocation that has already been
    revoked, is rejected with `ERR_ALLOCATION_ALREADY_ACKNOWLEDGED`."

    "A plan document that is not in `DRAFT` is rejected with
    `ERR_PLAN_ALREADY_ACTIVE`."

    Design: Corner/state_machines/corner_second_acknowledge_and_second_activate_rejected
    """
    plan_ctx = fixtures.active_plan(api)
    allocation = plan_ctx.named_fiduciary_allocation
    plan_version = plan_ctx.plan_version
    effective_date = plan_ctx.plan["effective_date"]

    repeat_acknowledge = api.acknowledge_fiduciary_role_allocation(
        allocation["id"],
        f.acknowledge_allocation_payload(
            "Northgate re-confirms the ERISA 3(16) named fiduciary function."
        ),
        service_provider_headers(plan_ctx.recordkeeper_id),
    )
    validate_error(
        repeat_acknowledge, ERR_ALLOCATION_ALREADY_ACKNOWLEDGED, expected_status=409
    )

    repeat_activate = api.activate_plan_document(
        plan_ctx.plan_id, plan_ctx.provider_headers
    )
    validate_error(repeat_activate, ERR_PLAN_ALREADY_ACTIVE, expected_status=409)

    read_allocation = validate_single(
        api.get_fiduciary_role_allocation(allocation["id"], plan_ctx.provider_headers)
    )
    assert_fields(
        read_allocation,
        acknowledgment_statement=k.NAMED_FIDUCIARY_ACKNOWLEDGMENT,
        acknowledged_at=allocation["acknowledged_at"],
        status=k.ALLOCATION_ALLOCATED,
        version=allocation["version"],
    )

    read_plan = plan_ctx.refresh(api)
    assert_fields(
        read_plan,
        status=k.PLAN_ACTIVE,
        effective_date=effective_date,
        version=plan_version,
    )


def test_reversed_window_beats_the_overlap_check_and_touching_one_day_collides(
    api: ApiClient,
):
    """
    The fiduciary window is a closed interval, so a successor that merely touches
    the incumbent's last day already collides — and a malformed window is
    reported before any collision is looked for.

    "The window must be well formed: an `effective_to` earlier than
    `effective_from` is rejected with `ERR_INVALID_ALLOCATION_WINDOW`."

    "It must also not collide with the window of the incumbent `ALLOCATED`
    allocation for the same plan and the same `fiduciary_role`: touching at a
    single day counts as a collision, so an `effective_from` equal to the
    incumbent's `effective_to` is rejected with `ERR_ALLOCATION_WINDOW_OVERLAP`
    while an `effective_from` one day later is accepted."

    Design: Difficulty/resource_temporal_overlap/fiduciary_allocation_closed_window_touching_day_rejected
    """
    plan_ctx = fixtures.active_plan(api)
    headers = plan_ctx.provider_headers
    manager = fixtures.engage_provider(
        api, plan_ctx.provider_id, f.investment_manager_payload(plan_ctx.plan_id)
    )
    incumbent = fixtures.allocate_role(
        api,
        plan_ctx,
        manager["id"],
        k.FIDUCIARY_INVESTMENT_MANAGER_3_38,
        effective_from="2026-08-03",
        effective_to="2026-10-31",
    )
    version_before = plan_ctx.refresh(api)["version"]

    reversed_window = api.create_fiduciary_role_allocation(
        f.fiduciary_allocation_payload(
            plan_ctx.plan_id,
            plan_ctx.recordkeeper_id,
            k.FIDUCIARY_INVESTMENT_MANAGER_3_38,
            version_before,
            effective_from="2026-10-15",
            effective_to="2026-10-01",
        ),
        headers,
    )
    validate_error(reversed_window, ERR_INVALID_ALLOCATION_WINDOW, expected_status=422)

    touching = api.create_fiduciary_role_allocation(
        f.fiduciary_allocation_payload(
            plan_ctx.plan_id,
            plan_ctx.recordkeeper_id,
            k.FIDUCIARY_INVESTMENT_MANAGER_3_38,
            version_before,
            effective_from="2026-10-31",
            effective_to="2027-06-30",
        ),
        headers,
    )
    validate_error(touching, ERR_ALLOCATION_WINDOW_OVERLAP, expected_status=409)

    assert_fields(plan_ctx.refresh(api), version=version_before)
    unchanged = validate_single(
        api.get_fiduciary_role_allocation(incumbent["id"], headers)
    )
    assert_fields(unchanged, status=k.ALLOCATION_ALLOCATED, version=incumbent["version"])
    assert_null_fields(unchanged, "revoked_at", "revoked_reason")


def test_allocation_window_guard_is_scoped_to_the_plan_and_role_pair(api: ApiClient):
    """
    The guarded resource is the plan and function together, so the incumbent's
    exact window is free for a different function, and the day after its last day
    is free for the same one.

    "A firm's `holds_fiduciary_role` is true exactly when at least one
    allocation naming it is in `ALLOCATED` status."

    "when the new allocation's `effective_from` is strictly later than the
    incumbent's `effective_from`, the incumbent moves from `ALLOCATED` to
    `REVOKED`, has `revoked_at` stamped from the logical clock and
    `revoked_reason` set to `SUPERSEDED_BY_NEW_ALLOCATION`, and has its own
    `version` incremented"

    Design: Difficulty/resource_temporal_overlap/fiduciary_allocation_closed_window_touching_day_rejected
    """
    plan_ctx = fixtures.active_plan(api)
    headers = plan_ctx.provider_headers
    manager = fixtures.engage_provider(
        api, plan_ctx.provider_id, f.investment_manager_payload(plan_ctx.plan_id)
    )
    incumbent = fixtures.allocate_role(
        api,
        plan_ctx,
        manager["id"],
        k.FIDUCIARY_INVESTMENT_MANAGER_3_38,
        effective_from="2026-08-03",
        effective_to="2026-10-31",
    )

    ministerial = fixtures.allocate_role(
        api,
        plan_ctx,
        manager["id"],
        k.FIDUCIARY_NON_FIDUCIARY_MINISTERIAL,
        effective_from="2026-08-03",
        effective_to="2026-10-31",
    )
    assert_fields(
        ministerial,
        fiduciary_role=k.FIDUCIARY_NON_FIDUCIARY_MINISTERIAL,
        status=k.ALLOCATION_ALLOCATED,
    )

    successor = fixtures.allocate_role(
        api,
        plan_ctx,
        plan_ctx.recordkeeper_id,
        k.FIDUCIARY_INVESTMENT_MANAGER_3_38,
        effective_from="2026-11-01",
        effective_to="2027-06-30",
    )
    assert_fields(successor, status=k.ALLOCATION_ALLOCATED, version=1)
    assert_null_fields(successor, "acknowledged_at")

    revoked = validate_single(
        api.get_fiduciary_role_allocation(incumbent["id"], headers)
    )
    assert_fields(
        revoked,
        status=k.ALLOCATION_REVOKED,
        revoked_reason=k.REVOKED_SUPERSEDED_BY_NEW_ALLOCATION,
        version=incumbent["version"] + 1,
    )
    assert_instant_equals(revoked["revoked_at"], k.DEFAULT_CLOCK, "revoked_at")

    still_holding = validate_single(api.get_service_provider(manager["id"], headers))
    assert_fields(still_holding, holds_fiduciary_role=True)
    incoming = validate_single(
        api.get_service_provider(plan_ctx.recordkeeper_id, headers)
    )
    assert_fields(incoming, holds_fiduciary_role=True)


def test_stale_plan_token_is_reported_before_the_window_rules(api: ApiClient):
    """
    The plan-level token is plan-scoped rather than role-scoped, and it is
    checked before either window rule.

    "Creating a fiduciary role allocation at `POST
    /pep/fiduciary-role-allocations` requires a non-optional
    `expected_plan_document_version` field carrying the `version` of the target
    `PlanDocument` as the client last observed it."

    "Priorities 8 and 9 are the two optimistic-concurrency checks of §2.7:
    `ERR_STALE_EMPLOYER_VERSION` then `ERR_STALE_PLAN_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_plan_version_rejected_before_window_checks
    """
    provider = fixtures.registered_provider(api)
    plan = fixtures.draft_plan(api, provider)
    headers = fixtures.plan_provider_headers(provider["id"])
    recordkeeper = fixtures.engage_provider(
        api, provider["id"], f.recordkeeper_payload(plan["id"])
    )
    trustee = fixtures.engage_provider(api, provider["id"], f.trustee_payload(plan["id"]))
    tpa = fixtures.engage_provider(api, provider["id"], f.tpa_payload(plan["id"]))

    first_version = validate_single(api.get_plan_document(plan["id"], headers))["version"]

    named = validate_created(
        api.create_fiduciary_role_allocation(
            f.fiduciary_allocation_payload(
                plan["id"],
                recordkeeper["id"],
                k.FIDUCIARY_NAMED_FIDUCIARY_3_16,
                first_version,
            ),
            headers,
        )
    )
    after_first = validate_single(api.get_plan_document(plan["id"], headers))
    assert_fields(after_first, version=first_version + 1)

    sibling_role = api.create_fiduciary_role_allocation(
        f.fiduciary_allocation_payload(
            plan["id"], trustee["id"], k.FIDUCIARY_TRUSTEE_403A, first_version
        ),
        headers,
    )
    validate_error(sibling_role, ERR_STALE_PLAN_VERSION, expected_status=412)

    stale_and_overlapping = api.create_fiduciary_role_allocation(
        f.fiduciary_allocation_payload(
            plan["id"],
            tpa["id"],
            k.FIDUCIARY_NAMED_FIDUCIARY_3_16,
            first_version,
            effective_from="2026-12-31",
            effective_to="2027-06-30",
        ),
        headers,
    )
    validate_error(stale_and_overlapping, ERR_STALE_PLAN_VERSION, expected_status=412)

    resent = validate_created(
        api.create_fiduciary_role_allocation(
            f.fiduciary_allocation_payload(
                plan["id"],
                trustee["id"],
                k.FIDUCIARY_TRUSTEE_403A,
                after_first["version"],
            ),
            headers,
        )
    )
    assert_fields(resent, status=k.ALLOCATION_ALLOCATED)
    assert_fields(
        validate_single(api.get_plan_document(plan["id"], headers)),
        version=first_version + 2,
    )
    assert_fields(
        validate_single(api.get_fiduciary_role_allocation(named["id"], headers)),
        status=k.ALLOCATION_ALLOCATED,
    )


def test_acknowledgment_leaves_a_plan_token_current_and_supersession_revokes(
    api: ApiClient,
):
    """
    Acknowledging touches only the allocation, so a plan token captured before
    two acknowledgments is still good for the write that supersedes an
    incumbent.

    "The request supplies the verbatim `acknowledgment_statement` text; the
    server stamps `acknowledged_at` from the logical clock, stores the statement,
    and increments the allocation's `version` by one."

    "A firm's `holds_fiduciary_role` is true exactly when at least one allocation
    naming it is in `ALLOCATED` status."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_plan_version_rejected_before_window_checks
    """
    plan_ctx = fixtures.plan_with_acknowledged_roles(api)
    headers = plan_ctx.provider_headers
    tpa = fixtures.engage_provider(
        api, plan_ctx.provider_id, f.tpa_payload(plan_ctx.plan_id)
    )
    token = plan_ctx.refresh(api)["version"]

    assert_fields(
        plan_ctx.named_fiduciary_allocation,
        acknowledgment_statement=k.NAMED_FIDUCIARY_ACKNOWLEDGMENT,
        version=2,
    )
    assert_fields(
        plan_ctx.trustee_allocation,
        acknowledgment_statement=k.TRUSTEE_ACKNOWLEDGMENT,
        version=2,
    )

    superseding = validate_created(
        api.create_fiduciary_role_allocation(
            f.fiduciary_allocation_payload(
                plan_ctx.plan_id,
                tpa["id"],
                k.FIDUCIARY_NAMED_FIDUCIARY_3_16,
                token,
                effective_from="2027-01-01",
                effective_to="2027-12-31",
            ),
            headers,
        )
    )
    assert_fields(superseding, status=k.ALLOCATION_ALLOCATED)

    incumbent = validate_single(
        api.get_fiduciary_role_allocation(
            plan_ctx.named_fiduciary_allocation["id"], headers
        )
    )
    assert_fields(
        incumbent,
        status=k.ALLOCATION_REVOKED,
        revoked_reason=k.REVOKED_SUPERSEDED_BY_NEW_ALLOCATION,
    )
    assert_instant(incumbent["revoked_at"], "revoked_at")

    outgoing = validate_single(
        api.get_service_provider(plan_ctx.recordkeeper_id, headers)
    )
    assert_fields(outgoing, holds_fiduciary_role=False)
    incoming = validate_single(api.get_service_provider(tpa["id"], headers))
    assert_fields(incoming, holds_fiduciary_role=True)
