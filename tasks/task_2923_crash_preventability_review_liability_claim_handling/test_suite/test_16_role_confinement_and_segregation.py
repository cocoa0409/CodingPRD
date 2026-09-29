"""Who may act, on which path, and never on their own work.

Authorization is settled before existence, shared paths admit each of their
declared roles interchangeably, and the two segregation rules read different
facts about the same operator.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_id_set
from test_helpers.constants import (
    ABSENT_UUIDS,
    ANALYTICS_BASIS_AS_DETERMINED,
    APPEAL_CODE_PROCEDURAL,
    BALLOT_DISPOSITION_PREVENTABLE,
    CLAIMANT_TYPE_PROPERTY,
    DECISION_BASIS_UNWEIGHTED_MAJORITY,
    DETERMINATION_PENDING,
    DETERMINATION_PREVENTABLE,
    EVIDENCE_FORWARD_CAMERA,
    EVIDENCE_TELEMATICS,
    LAYER_KIND_PRIMARY,
    LAYER_KIND_SIR,
    OPERATOR_IDS,
    PRESERVATION_PRESERVED,
    PREVENTABILITY_UNDER_REVIEW,
    REVIEW_STATE_DECIDED,
    REVIEW_STATE_DELIBERATION,
    ROUTE_CLASS_LINEHAUL,
    ROUTE_CLASS_REGIONAL,
    SEVERITY_MINOR,
    SEVERITY_MODERATE,
    SUBROGATION_STATE_DRAFT,
    TOW_REASON_NONE,
)
from test_helpers.fixtures import (
    APPEALS_MANAGER,
    AUDITOR,
    CLAIMS_ADJUSTER,
    CLAIMS_MANAGER,
    COMMITTEE_ONE,
    COMMITTEE_TWO,
    DISPATCHER,
    SAFETY_ADMIN,
    SAFETY_MANAGER,
    build_case_in_deliberation,
    build_claim,
    build_crash,
    build_driver,
    build_preserved_evidence,
    build_statement,
    build_terminal,
    cast_ballot,
    preserve_evidence,
    request_evidence,
)
from test_helpers.test_users import (
    make_blank_user_id_headers,
    make_committee_member_headers,
    make_driver_headers,
)

MARION_MILES = 2.5
ABSENT_DEMAND_ID = ABSENT_UUIDS[33]
ABSENT_CLAIM_ID = ABSENT_UUIDS[34]


def _marion_fleet_with_preserved_evidence(api: ApiClient) -> dict:
    """One terminal, two drivers, and a crash belonging to the first driver."""
    terminal = build_terminal(
        api,
        name="Marion Terminal",
        terminal_code="MAR03",
        region_code="OH",
        annual_miles_millions=MARION_MILES,
    )
    own_driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-6201",
        full_name="Jarno Kivela",
        cdl_number="OH-CDL-6201",
        hire_date="2015-02-02",
    )
    other_driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-6202",
        full_name="Kasia Wrzesniak",
        cdl_number="OH-CDL-6202",
        hire_date="2016-03-03",
    )
    crash = build_crash(
        api,
        own_driver["id"],
        terminal["id"],
        occurred_at="2026-07-28T11:00:00Z",
        notified_at="2026-07-28T11:20:00Z",
        location_text="SR-4 at the rail crossing",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    evidence = build_preserved_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-6201",
        window_start_at="2026-07-28T10:00:00Z",
        window_end_at="2026-07-28T12:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    return {
        "terminal": terminal,
        "own_driver": own_driver,
        "other_driver": other_driver,
        "crash": crash,
        "evidence": evidence,
    }


class TestExclusiveOperationsBelongToExactlyOneRole:
    """A role reaching for another role's operation is refused, and writes nothing."""

    def test_a_blank_identifier_is_refused_before_the_role_is_considered(
        self, api: ApiClient
    ):
        """The correct role for the path cannot rescue an empty identifier.

        PRD: "**Authentication.** Both headers present and non-empty, with
        `X-User-Role` naming one of the eight declared roles — otherwise
        `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/each_role_is_confined_to_its_own_exclusive_operations
        """
        context = _marion_fleet_with_preserved_evidence(api)

        validate_error(
            api.create_terminal(
                factories.terminal_payload(
                    name="Ghost Terminal",
                    terminal_code="GHO03",
                    region_code="OH",
                    annual_miles_millions=1.0,
                ),
                make_blank_user_id_headers(),
            ),
            ApiErrorId.UNAUTHENTICATED.value,
            401,
        )

        terminals, meta = validate_paginated(
            api.list_terminals(AUDITOR, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert_id_set(terminals, [context["terminal"]["id"]])

    def test_four_writes_each_refuse_every_role_but_their_owner(self, api: ApiClient):
        """The read-only observer, and three peers reaching across the boundary.

        PRD: "`Auditor` is a read-only compliance observer with the widest read
        surface in the system and no write authority anywhere: an `Auditor` may read
        every collection, including the ballot ledger and the terminal
        crash-analytics projection, and may write nothing."

        Design: Corner/rbac/each_role_is_confined_to_its_own_exclusive_operations
        """
        context = _marion_fleet_with_preserved_evidence(api)

        validate_error(
            api.create_terminal(
                factories.terminal_payload(
                    name="Ghost Terminal",
                    terminal_code="GHO03",
                    region_code="OH",
                    annual_miles_millions=1.0,
                ),
                AUDITOR,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_driver(
                factories.driver_payload(
                    context["terminal"]["id"],
                    employee_code="D-6203",
                    full_name="Ghost Driver",
                    cdl_number="OH-CDL-6203",
                    hire_date="2017-04-04",
                ),
                DISPATCHER,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_review_case(
                factories.review_case_payload(
                    context["crash"]["id"],
                    committee_name="Marion Safety Review Committee",
                ),
                COMMITTEE_ONE,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.purge_evidence_item(
                context["evidence"]["id"],
                factories.purge_payload(purge_reason="manager housekeeping"),
                SAFETY_MANAGER,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        terminal = validate_success(
            api.get_terminal(context["terminal"]["id"], AUDITOR)
        )
        assert terminal["version"] == context["terminal"]["version"] == 1
        assert terminal["name"] == "Marion Terminal"
        assert terminal["active_driver_count"] == 2

        evidence = validate_success(
            api.get_evidence_item(context["evidence"]["id"], AUDITOR)
        )
        assert evidence["preservation_state"] == PRESERVATION_PRESERVED
        assert evidence["version"] == context["evidence"]["version"]

        _, meta = validate_paginated(
            api.list_terminals(AUDITOR, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1

    def test_authorization_is_settled_before_the_addressed_row_is_looked_up(
        self, api: ApiClient
    ):
        """An unauthorized caller cannot probe which identifiers exist.

        PRD: "Requests are validated in one strict ascending order, and the **first**
        rule that is violated determines the entire response."

        Design: Corner/rbac/each_role_is_confined_to_its_own_exclusive_operations
        """
        _marion_fleet_with_preserved_evidence(api)

        validate_error(
            api.settle_demand(
                ABSENT_DEMAND_ID,
                factories.settle_payload(settlement_reference="SET-GHOST-1"),
                CLAIMS_ADJUSTER,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_demand(
                ABSENT_CLAIM_ID,
                factories.demand_payload(
                    claimant_name="Ghost Claimant",
                    claimant_type=CLAIMANT_TYPE_PROPERTY,
                    demand_amount_cents=100_000,
                    represented_by_counsel=False,
                    demand_received_at="2026-07-30T00:00:00Z",
                ),
                CLAIMS_MANAGER,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

    def test_the_driver_role_reaches_only_its_own_crash_and_nothing_else(
        self, api: ApiClient
    ):
        """A correct role with the wrong identity is still refused.

        PRD: "A driver filing a statement about a crash whose `driver_id` is somebody
        else is rejected with `ERR_UNAUTHORIZED` (HTTP 403), and the server records
        the acting identifier on the statement as `submitted_by_driver_id`."

        Design: Corner/rbac/each_role_is_confined_to_its_own_exclusive_operations
        """
        context = _marion_fleet_with_preserved_evidence(api)
        crash_id = context["crash"]["id"]

        validate_error(
            api.create_driver_statement(
                crash_id,
                factories.driver_statement_payload(
                    narrative="I saw the whole thing from the next lane.",
                    conditions_note=None,
                ),
                make_driver_headers(context["other_driver"]["id"]),
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.list_crashes(
                make_driver_headers(context["own_driver"]["id"]),
                {"terminal_id": context["terminal"]["id"]},
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        statement = build_statement(
            api,
            crash_id,
            context["own_driver"]["id"],
            narrative="The crossing arm dropped on my trailer.",
            conditions_note=None,
        )
        assert statement["submitted_by_driver_id"] == context["own_driver"]["id"]

        rows, meta = validate_paginated(
            api.list_driver_statements(crash_id, AUDITOR, {"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 1
        assert_id_set(rows, [statement["id"]])


NORWALK_MILES = 3.5
NORWALK_SIR_LIMIT_CENTS = 1_000_000
NORWALK_PRIMARY_LIMIT_CENTS = 5_000_000


def _norwalk_crash_with_a_third_party(api: ApiClient) -> dict:
    """A moderate crash whose third party is at fault, and nothing else yet."""
    terminal = build_terminal(
        api,
        name="Norwalk Terminal",
        terminal_code="NOR03",
        region_code="OH",
        annual_miles_millions=NORWALK_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-6301",
        full_name="Liesbeth Vandenberg",
        cdl_number="OH-CDL-6301",
        hire_date="2010-09-09",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-27T14:00:00Z",
        notified_at="2026-07-27T14:30:00Z",
        location_text="US-20 at the truck stop entrance",
        severity=SEVERITY_MODERATE,
        route_class=ROUTE_CLASS_LINEHAUL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
        third_party_at_fault=True,
    )
    return {"terminal": terminal, "driver": driver, "crash": crash}


class TestSharedOperationsAdmitEachDeclaredRole:
    """A shared path is shared among its declared roles and no others."""

    def test_the_policy_tower_may_be_built_by_two_different_roles(
        self, api: ApiClient
    ):
        """One layer from the claims side, the next from the safety side.

        PRD: "That role alone may advance the logical clock, register terminals, hire
        drivers, purge evidence and record retraining completion; it shares crash
        intake, evidence-preservation requests and the preservation action itself with
        `Dispatcher`, and shares maintenance of the policy tower with `ClaimsManager`."

        Design: Corner/rbac/shared_operations_admit_every_declared_role_on_the_same_path
        """
        _norwalk_crash_with_a_third_party(api)

        sir = validate_success(
            api.create_policy_layer(
                factories.policy_layer_payload(
                    program_year=2026,
                    layer_index=1,
                    layer_type=LAYER_KIND_SIR,
                    attachment_point_cents=0,
                    limit_cents=NORWALK_SIR_LIMIT_CENTS,
                    insurer_name="Self-Insured Retention",
                ),
                CLAIMS_MANAGER,
            ),
            201,
        )
        primary = validate_success(
            api.create_policy_layer(
                factories.policy_layer_payload(
                    program_year=2026,
                    layer_index=2,
                    layer_type=LAYER_KIND_PRIMARY,
                    attachment_point_cents=NORWALK_SIR_LIMIT_CENTS,
                    limit_cents=NORWALK_PRIMARY_LIMIT_CENTS,
                    insurer_name="Great Lakes Casualty",
                ),
                SAFETY_ADMIN,
            ),
            201,
        )

        rows, meta = validate_paginated(
            api.list_policy_layers(
                AUDITOR, {"program_year": 2026, "limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [sir["id"], primary["id"]]
        assert [row["layer_index"] for row in rows] == [1, 2]
        assert_cents(rows[0]["attachment_point_cents"], 0, "attachment_point_cents")
        assert_cents(
            rows[1]["attachment_point_cents"],
            NORWALK_SIR_LIMIT_CENTS,
            "attachment_point_cents",
        )

    def test_evidence_custody_crosses_over_between_its_two_declared_roles(
        self, api: ApiClient
    ):
        """Each item is requested by one role and preserved by the other.

        PRD: "Preservation itself — the act that places the artifact under litigation
        hold in the immutable store — is the second stage, again available to a
        `Dispatcher` or a `SafetyAdmin`."

        Design: Corner/rbac/shared_operations_admit_every_declared_role_on_the_same_path
        """
        context = _norwalk_crash_with_a_third_party(api)
        crash_id = context["crash"]["id"]

        telematics = request_evidence(
            api,
            crash_id,
            kind=EVIDENCE_TELEMATICS,
            source_device_id="ECM-6301",
            window_start_at="2026-07-27T13:00:00Z",
            window_end_at="2026-07-27T15:00:00Z",
            retention_deadline_at="2027-06-30T00:00:00Z",
        )
        camera = validate_success(
            api.create_evidence_item(
                crash_id,
                factories.evidence_payload(
                    kind=EVIDENCE_FORWARD_CAMERA,
                    source_device_id="CAM-6301",
                    window_start_at="2026-07-27T13:00:00Z",
                    window_end_at="2026-07-27T15:00:00Z",
                    retention_deadline_at="2027-06-30T00:00:00Z",
                ),
                SAFETY_ADMIN,
            ),
            201,
        )

        preserved_by_admin = validate_success(
            api.preserve_evidence_item(
                telematics["id"],
                factories.preserve_payload(
                    preserved_copy_uri="s3://evidence/2923nor/ecm-6301.json",
                    evidence_hash="5c5c6d6d7e7e8f8f9a9a0b0b1c1c2d2d",
                ),
                SAFETY_ADMIN,
            )
        )
        preserved_by_dispatcher = preserve_evidence(
            api,
            camera["id"],
            preserved_copy_uri="s3://evidence/2923nor/cam-6301.mp4",
            evidence_hash="6d6d7e7e8f8f9a9a0b0b1c1c2d2d3e3e",
        )

        assert preserved_by_admin["preservation_state"] == PRESERVATION_PRESERVED
        assert preserved_by_dispatcher["preservation_state"] == PRESERVATION_PRESERVED

    def test_both_claims_roles_open_subrogation_files_on_one_claim(
        self, api: ApiClient
    ):
        """The adjuster opens one recovery file and the manager the next.

        PRD: "Opening a subrogation demand is shared between `ClaimsAdjuster` and
        `ClaimsManager`."

        Design: Corner/rbac/shared_operations_admit_every_declared_role_on_the_same_path
        """
        context = _norwalk_crash_with_a_third_party(api)
        claim = build_claim(
            api, context["crash"]["id"], claimant_notice_date="2026-07-28"
        )

        by_adjuster = validate_success(
            api.create_subrogation_demand(
                claim["id"],
                factories.subrogation_demand_payload(
                    third_party_name="Maumee Paving LLC",
                    at_fault_percentage=60,
                    basis_note="unsecured load from the paving truck",
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )
        by_manager = validate_success(
            api.create_subrogation_demand(
                claim["id"],
                factories.subrogation_demand_payload(
                    third_party_name="Sandusky Towing Co",
                    at_fault_percentage=15,
                    basis_note="secondary impact during recovery",
                ),
                CLAIMS_MANAGER,
            ),
            201,
        )

        assert by_adjuster["status"] == SUBROGATION_STATE_DRAFT
        assert by_manager["status"] == SUBROGATION_STATE_DRAFT
        assert by_adjuster["recoverable_base_cents"] is None
        assert by_manager["recoverable_base_cents"] is None

        rows, meta = validate_paginated(
            api.list_claim_subrogation_demands(
                claim["id"], AUDITOR, {"limit": 10, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert_id_set(rows, [by_adjuster["id"], by_manager["id"]])

    def test_the_observer_reads_every_shared_row_and_writes_none_of_them(
        self, api: ApiClient
    ):
        """Sharing extends to the declared roles only, and never to the Auditor.

        PRD: "an `Auditor` may read every collection, including the ballot ledger and
        the terminal crash-analytics projection, and may write nothing."

        Design: Corner/rbac/shared_operations_admit_every_declared_role_on_the_same_path
        """
        context = _norwalk_crash_with_a_third_party(api)
        validate_success(
            api.create_policy_layer(
                factories.policy_layer_payload(
                    program_year=2026,
                    layer_index=1,
                    layer_type=LAYER_KIND_SIR,
                    attachment_point_cents=0,
                    limit_cents=NORWALK_SIR_LIMIT_CENTS,
                    insurer_name="Self-Insured Retention",
                ),
                CLAIMS_MANAGER,
            ),
            201,
        )
        claim = build_claim(
            api, context["crash"]["id"], claimant_notice_date="2026-07-28"
        )
        validate_success(
            api.create_subrogation_demand(
                claim["id"],
                factories.subrogation_demand_payload(
                    third_party_name="Maumee Paving LLC",
                    at_fault_percentage=60,
                    basis_note="unsecured load from the paving truck",
                ),
                CLAIMS_ADJUSTER,
            ),
            201,
        )

        analytics = validate_success(
            api.get_crash_analytics(context["terminal"]["id"], AUDITOR)
        )
        assert analytics["basis"] == ANALYTICS_BASIS_AS_DETERMINED

        validate_error(
            api.create_policy_layer(
                factories.policy_layer_payload(
                    program_year=2026,
                    layer_index=3,
                    layer_type="EXCESS",
                    attachment_point_cents=6_000_000,
                    limit_cents=9_000_000,
                    insurer_name="Auditor Excess",
                ),
                AUDITOR,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )
        validate_error(
            api.create_subrogation_demand(
                claim["id"],
                factories.subrogation_demand_payload(
                    third_party_name="Auditor Recovery",
                    at_fault_percentage=5,
                    basis_note="read-only role attempting a shared write",
                ),
                AUDITOR,
            ),
            ApiErrorId.UNAUTHORIZED.value,
            403,
        )

        _, tower_meta = validate_paginated(
            api.list_policy_layers(
                AUDITOR, {"program_year": 2026, "limit": 10, "offset": 0}
            )
        )
        assert tower_meta["total_count"] == 1
        _, sub_meta = validate_paginated(
            api.list_claim_subrogation_demands(
                claim["id"], AUDITOR, {"limit": 10, "offset": 0}
            )
        )
        assert sub_meta["total_count"] == 1


OBERLIN_MILES = 2.0
PROCEDURAL_GROUNDS = "the committee was not shown the guardrail photographs"


def _case_balloted_by_the_deciding_manager(api: ApiClient) -> dict:
    """Three ballots, the third cast by a safety manager under his own identity."""
    terminal = build_terminal(
        api,
        name="Oberlin Terminal",
        terminal_code="OBE03",
        region_code="OH",
        annual_miles_millions=OBERLIN_MILES,
    )
    driver = build_driver(
        api,
        terminal["id"],
        employee_code="D-6401",
        full_name="Mihai Lupescu",
        cdl_number="OH-CDL-6401",
        hire_date="2016-06-06",
    )
    crash = build_crash(
        api,
        driver["id"],
        terminal["id"],
        occurred_at="2026-07-26T09:00:00Z",
        notified_at="2026-07-26T09:15:00Z",
        location_text="SR-58 at the reservoir",
        severity=SEVERITY_MINOR,
        route_class=ROUTE_CLASS_REGIONAL,
        tow_away=False,
        tow_reason=TOW_REASON_NONE,
    )
    build_preserved_evidence(
        api,
        crash["id"],
        kind=EVIDENCE_TELEMATICS,
        source_device_id="ECM-6401",
        window_start_at="2026-07-26T08:00:00Z",
        window_end_at="2026-07-26T10:00:00Z",
        retention_deadline_at="2027-06-30T00:00:00Z",
    )
    build_statement(
        api,
        crash["id"],
        driver["id"],
        narrative="I braked for the deer and slid into the guardrail.",
        conditions_note=None,
    )
    case = build_case_in_deliberation(
        api, crash["id"], committee_name="Oberlin Safety Review Committee"
    )
    manager_as_member = make_committee_member_headers(
        OPERATOR_IDS["safety_manager_decider"]
    )
    current = case
    for headers, scores in (
        (COMMITTEE_ONE, factories.uniform_criterion_scores(3)),
        (COMMITTEE_TWO, factories.uniform_criterion_scores(3)),
        (manager_as_member, factories.criterion_scores(speed_and_spacing=2)),
    ):
        current = cast_ballot(
            api,
            case["id"],
            current["version"],
            headers,
            vote=BALLOT_DISPOSITION_PREVENTABLE,
            scores=scores,
        )
    return {
        "terminal": terminal,
        "driver": driver,
        "crash": crash,
        "review_case": current,
        "manager_as_member": manager_as_member,
    }


class TestTheTwoSegregationRulesReadDifferentFacts:
    """A balloting manager may not decide; a deciding manager may not grant."""

    def test_a_manager_behind_a_live_ballot_may_not_record_the_determination(
        self, api: ApiClient
    ):
        """The bar holds even though deciding is that role's own operation.

        PRD: "**Segregation of duties.** The decider may not be behind any live ballot
        on the case, and the appeal grantor may not be the operator who decided —
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/the_deciding_manager_may_not_grant_the_appeal
        """
        context = _case_balloted_by_the_deciding_manager(api)
        case = context["review_case"]
        assert case["status"] == REVIEW_STATE_DELIBERATION
        assert case["determination"] == DETERMINATION_PENDING
        assert case["active_vote_count"] == 3

        validate_error(
            api.decide_review_case(case["id"], headers=SAFETY_MANAGER),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )

        unmoved = validate_success(api.get_review_case(case["id"], AUDITOR))
        assert unmoved["status"] == REVIEW_STATE_DELIBERATION
        assert unmoved["determination"] == DETERMINATION_PENDING
        assert unmoved["decided_by_user_id"] is None

    def test_recasting_supersedes_the_first_ballot_without_clearing_the_bar(
        self, api: ApiClient
    ):
        """A member always holds exactly one live ballot, so there is no escape.

        PRD: "Every earlier ballot on the same case from the same `member_user_id` is
        marked `superseded`, so a member always has exactly one live ballot no matter
        how many times he votes"

        Design: Corner/rbac/the_deciding_manager_may_not_grant_the_appeal
        """
        context = _case_balloted_by_the_deciding_manager(api)
        case = context["review_case"]

        recast = cast_ballot(
            api,
            case["id"],
            case["version"],
            context["manager_as_member"],
            vote=BALLOT_DISPOSITION_PREVENTABLE,
            scores=factories.uniform_criterion_scores(3),
        )
        assert recast["active_vote_count"] == 3

        dead, dead_meta = validate_paginated(
            api.list_votes(
                case["id"], AUDITOR, {"superseded": "true", "limit": 10, "offset": 0}
            )
        )
        assert dead_meta["total_count"] == 1
        assert dead[0]["member_user_id"] == OPERATOR_IDS["safety_manager_decider"]

        live, live_meta = validate_paginated(
            api.list_votes(
                case["id"], AUDITOR, {"superseded": "false", "limit": 10, "offset": 0}
            )
        )
        assert live_meta["total_count"] == 3
        assert sorted(row["member_user_id"] for row in live) == sorted(
            [
                OPERATOR_IDS["committee_member_one"],
                OPERATOR_IDS["committee_member_two"],
                OPERATOR_IDS["safety_manager_decider"],
            ]
        )

        validate_error(
            api.decide_review_case(case["id"], headers=SAFETY_MANAGER),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )

    def test_the_uninvolved_manager_records_the_determination(self, api: ApiClient):
        """Three live ballots on a complete record decide by simple majority.

        PRD: "On a `COMPLETE` evidence record the basis is `UNWEIGHTED_MAJORITY`: the
        determination is `PREVENTABLE` when the count of live `PREVENTABLE` ballots
        strictly exceeds the count of live `NON_PREVENTABLE` ballots"

        Design: Corner/rbac/the_deciding_manager_may_not_grant_the_appeal
        """
        context = _case_balloted_by_the_deciding_manager(api)

        decided = validate_success(
            api.decide_review_case(
                context["review_case"]["id"], headers=APPEALS_MANAGER
            )
        )

        assert decided["status"] == REVIEW_STATE_DECIDED
        assert decided["determination"] == DETERMINATION_PREVENTABLE
        assert decided["decision_basis"] == DECISION_BASIS_UNWEIGHTED_MAJORITY
        assert decided["decided_by_user_id"] == OPERATOR_IDS["safety_manager_appeals"]

    def test_the_appeal_bar_keys_on_the_decider_rather_than_on_the_ballots(
        self, api: ApiClient
    ):
        """The manager who voted may grant; the manager who decided may not.

        PRD: "The acting operator must not be the case's `decided_by_user_id`, or the
        response is `ERR_SEGREGATION_OF_DUTIES` — the manager who ruled may not be the
        manager who reopens."

        Design: Corner/rbac/the_deciding_manager_may_not_grant_the_appeal
        """
        context = _case_balloted_by_the_deciding_manager(api)
        case_id = context["review_case"]["id"]
        validate_success(api.decide_review_case(case_id, headers=APPEALS_MANAGER))

        validate_error(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds=PROCEDURAL_GROUNDS,
                    appeal_grounds_code=APPEAL_CODE_PROCEDURAL,
                ),
                APPEALS_MANAGER,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )

        granted = validate_success(
            api.appeal_review_case(
                case_id,
                factories.appeal_payload(
                    appeal_grounds=PROCEDURAL_GROUNDS,
                    appeal_grounds_code=APPEAL_CODE_PROCEDURAL,
                ),
                SAFETY_MANAGER,
            )
        )
        assert granted["status"] == REVIEW_STATE_DELIBERATION
        assert granted["determination"] == DETERMINATION_PENDING
        assert granted["appeal_round"] == 1

        crash = validate_success(api.get_crash(context["crash"]["id"], AUDITOR))
        assert crash["preventability_status"] == PREVENTABILITY_UNDER_REVIEW
