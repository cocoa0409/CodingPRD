"""Access control, observed-version guards, rate-threshold surveillance and the
immediate-consistency contract of the Brokered Deposit Funding Compliance API.

Every world here is built from scratch through the API's own endpoints, because
the database is empty before each test and the logical clock reads
2026-08-01T00:00:00Z until a caller moves it (PRD §2.10).
"""
import pytest

from test_helpers import (
    DEFAULT_CLOCK_INSTANT,
    ApiErrorId,
    api_client,
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
    make_broker_representative_headers,
    make_compliance_headers,
    make_system_admin_headers,
)


# ─── World builders (composed inline from api_client + factories) ────────────

def _bank(**overrides) -> dict:
    """Clock pinned at the PRD default instant plus one registered bank."""
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    baselines = {
        "core_deposits_cents": 30_000_000_000,
        "total_liabilities_cents": 45_000_000_000,
        "tier1_capital_cents": 4_000_000_000,
        "liquidity_buffer_cents": 900_000_000,
    }
    baselines.update(overrides)
    return fx.register_institution(**baselines)


def _brokered_program(institution, **program_overrides) -> dict:
    """Counterparty with an APPROVED agreement plus a BROKERED programme sitting
    in PENDING_CLASSIFICATION."""
    env = fx.setup_approved_agreement()
    overrides = {
        "broker_id": env["broker"]["id"],
        "agreement_id": env["agreement"]["id"],
        "program_name": "Brokered CD",
        "funding_channel_claim": "BROKERED",
        "offered_rate_bps": 470,
    }
    overrides.update(program_overrides)
    env["institution"] = institution
    env["program"] = fx.open_program(institution["id"], DESK, **overrides)
    return env


def _denied_world() -> dict:
    """One bank, one APPROVED agreement and one PENDING_CLASSIFICATION programme,
    each created by a role that the endpoint actually lists. No benchmark is
    published, so the collection stays empty for the side-effect check."""
    institution = _bank(legal_name="Deny Bank NA")
    return _brokered_program(institution, program_name="Deny Brokered CD",
                             offered_rate_bps=400)


def _two_broker_world() -> dict:
    """Two counterparties, each with one agreement, so a broker representative
    holding counterparty A's id can address both its own and a foreign row."""
    fx.set_clock(DEFAULT_CLOCK_INSTANT)
    broker_a = fx.register_broker(legal_name="Scope Broker A LLC")
    broker_b = fx.register_broker(
        legal_name="Scope Broker B LLC",
        broker_type="LISTING_SERVICE",
        has_placement_discretion=False,
        fee_flat_cents=5000,
    )
    agreement_a = fx.draft_agreement(broker_a["id"], DESK, agreement_ref="AGR-9082-A")
    agreement_b = fx.draft_agreement(
        broker_b["id"], DESK, agreement_ref="AGR-9082-B", fee_flat_cents=5000,
        aml_program_score=70, financial_condition_score=70,
        insurance_coverage_score=70, recordkeeping_score=70,
    )
    return {
        "broker_a": broker_a,
        "broker_b": broker_b,
        "agreement_a": agreement_a,
        "agreement_b": agreement_b,
    }


def _capped_threshold_world() -> dict:
    """A CAPPED bank with a 400 bps DAYS_31_90 benchmark, an OPEN_FOR_PLACEMENT
    programme offering 470 bps and one PENDING tranche of 1,000,000,000 cents."""
    institution = _bank(legal_name="Threshold Bank NA",
                        capital_category="ADEQUATELY_CAPITALIZED")
    fx.publish_rate_cap(tenor_bucket="DAYS_31_90", published_national_rate_bps=400,
                        effective_date="2026-07-01")
    env = _brokered_program(institution, program_name="Threshold Brokered CD",
                            offered_rate_bps=470)
    fx.classify_program(env["program"]["id"], env["program"]["version"], COMPLIANCE)
    env["program"] = fx.attest_program(env["program"]["id"], DESK)
    env["placement"] = fx.book_placement(
        env["program"]["id"], DESK, principal_cents=1_000_000_000, rate_bps=470,
        issue_date="2026-08-01", tenor_days=60,
    )
    return env


def _immediate_world() -> dict:
    """A WELL_CAPITALIZED bank, a FLAT_FEE agreement of 25000 cents, an open
    brokered programme, a board limit at warning 2000 / breach 4000 and one
    PENDING tranche of 1,000,000,000 cents."""
    institution = _bank(legal_name="Immediate Bank NA")
    env = _brokered_program(institution, program_name="Immediate Brokered CD",
                            offered_rate_bps=470)
    fx.classify_program(env["program"]["id"], env["program"]["version"], COMPLIANCE)
    env["program"] = fx.attest_program(env["program"]["id"], DESK)
    env["limit"] = fx.create_concentration_limit(
        institution["id"], TREASURY, metric="BROKERED_TO_TOTAL_DEPOSITS",
        warning_threshold_bps=2000, breach_threshold_bps=4000,
    )
    env["placement"] = fx.book_placement(
        env["program"]["id"], DESK, principal_cents=1_000_000_000, rate_bps=470,
        issue_date="2026-08-01", tenor_days=60,
    )
    return env


class TestRoleBasedAccessControl:
    """Role authorisation, entity-backed scoping and duty segregation (PRD §2.1,
    §2.9 and the endpoint role lists of PRD §4)."""

    def test_each_role_drives_the_step_its_own_endpoint_list_grants(self):
        """One funding lifecycle where every step is taken by the role that owns it.

        PRD §2.1: "When the headers are well formed but the acting role does not
        appear on the authorised-role list of the addressed endpoint (§4), the
        request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §4 grants each of these steps to exactly the role used below:
        "| POST | `/national-rate-caps` | Publishes one national rate cap for a tenor bucket effective from a date. | `SystemAdmin` |"
        "| POST | `/deposit-classifications` | Records a brokered-versus-non-brokered determination for a program, guarded by `expected_program_version`, and becomes the program's governing classification. | `SystemAdmin`, `ComplianceReviewer` |"
        "| POST | `/deposit-placements` | Books a deposit tranche under a program with its principal, rate, issue date and tenor. | `SystemAdmin`, `FundingDeskOfficer` |"
        "| POST | `/institutions/{id}/concentration-limits` | Sets a board limit for one concentration metric, superseding any active limit on that metric and re-evaluating posture immediately. | `SystemAdmin`, `TreasuryController` |"
        "| PATCH | `/institutions/{id}/capital-category` | Supervisory re-categorisation, guarded by `expected_institution_version`; a downgrade out of `WELL_CAPITALIZED` caps the bank and cascades a rate-cap re-evaluation over its active placements. | `SystemAdmin`, `Examiner` |"

        PRD §3.2: "The composite `diligence_score` is a weighted blend of the four
        sub-scores: thirty-five parts of `aml_program_score`, thirty parts of
        `financial_condition_score`, twenty parts of `insurance_coverage_score` and
        fifteen parts of `recordkeeping_score`, summed as an exact rational and
        divided by one hundred, with that single final quotient rounded half up to a
        whole point in the 0 to 100 range."

        PRD §3.6: "The `outcome` follows: `EXEMPT_NO_CAP` when there is no ceiling
        because the bank is `WELL_CAPITALIZED` and therefore `EXEMPT`, `BREACH` when
        `breach_bps` is greater than zero, and `PASS` otherwise."

        PRD §3.1: "From the capital category the system immediately derives
        `rate_cap_regime`, which is `EXEMPT` when the category is `WELL_CAPITALIZED`
        and `CAPPED` for every other category."

        Design: Corner/rbac/corner_every_role_can_perform_its_own_exclusive_operations
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        validate_success(
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
        institution = validate_success(
            api_client.create_institution(
                f.institution_payload(
                    legal_name="Permit Bank NA",
                    core_deposits_cents=30_000_000_000,
                    total_liabilities_cents=45_000_000_000,
                    tier1_capital_cents=4_000_000_000,
                    liquidity_buffer_cents=900_000_000,
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        # The desk originates the counterparty file.
        broker = validate_success(
            api_client.create_broker(
                f.broker_payload(legal_name="Permit Brokers LLC", fee_flat_cents=10000),
                DESK,
            ),
            expected_status=201,
        )
        agreement = validate_success(
            api_client.create_agreement(
                broker["id"], f.agreement_payload(fee_flat_cents=10000), DESK
            ),
            expected_status=201,
        )
        validate_success(
            api_client.diligence_action(
                agreement["id"], f.diligence_action_payload("START_DILIGENCE"), DESK
            )
        )
        # Compliance blesses it: the second line approves what the desk prepared.
        approved = validate_success(
            api_client.diligence_action(
                agreement["id"], f.diligence_action_payload("APPROVE"), COMPLIANCE
            )
        )
        assert approved["status"] == "APPROVED", (
            f"a composite of 74 must land the agreement in APPROVED, got {approved['status']}"
        )
        assert approved["diligence_score"] == 74, (
            "the weighted blend of 80/75/70/65 rounds half up to 74, got "
            f"{approved['diligence_score']}"
        )
        # The desk opens the programme.
        program = validate_success(
            api_client.create_program(
                f.brokered_program_payload(
                    institution["id"], broker["id"], agreement["id"],
                    program_name="Permit Brokered CD", offered_rate_bps=400,
                ),
                DESK,
            ),
            expected_status=201,
        )
        # Compliance determines the class.
        classification = validate_success(
            api_client.create_classification(
                f.classification_payload(program["id"], program["version"]), COMPLIANCE
            ),
            expected_status=201,
        )
        assert classification["determined_by_user_id"] == USER_IDS["compliance"], (
            "determined_by_user_id must be the acting compliance identifier, got "
            f"{classification['determined_by_user_id']}"
        )
        # The desk attests it.
        attested = validate_success(
            api_client.program_state_action(
                program["id"], {"action": "ATTEST_CLASSIFICATION"}, DESK
            )
        )
        assert attested["state"] == "OPEN_FOR_PLACEMENT", (
            f"attestation must open the programme, got state {attested['state']}"
        )
        assert attested["attested_by_user_id"] == USER_IDS["desk"], (
            "attested_by_user_id must be the acting desk identifier, got "
            f"{attested['attested_by_user_id']}"
        )
        # The desk books and funds the tranche.
        placement = validate_success(
            api_client.create_placement(
                f.placement_payload(program["id"], principal_cents=1_000_000_000,
                                    rate_bps=400),
                DESK,
            ),
            expected_status=201,
        )
        activated = validate_success(
            api_client.funding_action(
                placement["id"], f.funding_action_payload("ACTIVATE"), DESK
            )
        )
        assert activated["funding_status"] == "ACTIVE", (
            f"the funding action must activate the tranche, got {activated['funding_status']}"
        )
        # Compliance runs surveillance.
        check = validate_success(
            api_client.create_rate_cap_check(
                placement["id"], f.rate_cap_check_payload("2026-08-01"), COMPLIANCE
            ),
            expected_status=201,
        )
        asserts.assert_rate_cap_check(check)
        assert check["effective_cap_bps"] is None, (
            "a WELL_CAPITALIZED bank is EXEMPT, so no ceiling is snapshotted, got "
            f"{check['effective_cap_bps']}"
        )
        assert check["outcome"] == "EXEMPT_NO_CAP", (
            f"an EXEMPT bank yields EXEMPT_NO_CAP, got {check['outcome']}"
        )
        assert check["breach_bps"] == 0, (
            f"breach_bps is 0 whenever there is no ceiling, got {check['breach_bps']}"
        )
        # Treasury expresses the board's appetite and drafts the plan.
        limit = validate_success(
            api_client.create_concentration_limit(
                institution["id"],
                f.concentration_limit_payload(warning_threshold_bps=2000,
                                             breach_threshold_bps=4000),
                TREASURY,
            ),
            expected_status=201,
        )
        assert limit["current_value_bps"] == 322, (
            "the brokered metric is floor(1000000000 * 10000 / 31000000000) == 322, got "
            f"{limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "WITHIN", (
            f"322 bps sits below the 2000 bps warning level, got {limit['breach_state']}"
        )
        plan = validate_success(
            api_client.create_contingency_plan(
                institution["id"],
                f.contingency_plan_payload(
                    plan_version_label="CFP-PERMIT", effective_from="2026-08-01",
                    effective_to="2026-12-31", stage_1_trigger_bps=500,
                    stage_2_trigger_bps=2000, stage_3_trigger_bps=4000,
                ),
                TREASURY,
            ),
            expected_status=201,
        )
        asserts.assert_contingency_plan(plan)
        assert plan["status"] == "DRAFT", (
            f"a new plan lands in DRAFT, got {plan['status']}"
        )
        # The examiner re-categorises capital.
        observed = validate_success(api_client.get_institution(institution["id"], TREASURY))
        recategorised = validate_success(
            api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "ADEQUATELY_CAPITALIZED",
                    "expected_institution_version": observed["version"],
                },
                EXAMINER,
            )
        )
        assert recategorised["capital_category"] == "ADEQUATELY_CAPITALIZED", (
            "the examiner's re-categorisation must land, got "
            f"{recategorised['capital_category']}"
        )
        assert recategorised["rate_cap_regime"] == "CAPPED", (
            "any category other than WELL_CAPITALIZED derives CAPPED, got "
            f"{recategorised['rate_cap_regime']}"
        )
        # The shared computed read answers treasury too.
        summary = validate_success(
            api_client.get_wholesale_funding_summary(institution["id"], TREASURY)
        )
        assert isinstance(summary, dict) and summary, (
            "the wholesale funding summary must return a computed object for treasury"
        )

    @pytest.mark.parametrize(
        "probe",
        [
            "benchmark_publication_by_the_desk",
            "classification_by_the_desk",
            "placement_by_compliance",
            "program_by_treasury",
            "board_limit_by_the_examiner",
            "capital_recategorisation_by_compliance",
        ],
    )
    def test_a_role_missing_from_the_endpoint_list_is_refused(self, probe):
        """Each body below is otherwise perfectly valid, so the only reason it fails
        is the role gate, which runs ahead of every state, existence and arithmetic rule.

        PRD §2.1: "When the headers are well formed but the acting role does not
        appear on the authorised-role list of the addressed endpoint (§4), the
        request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §2.8: "2. Authorisation: the acting role appears on the target endpoint's
        list, and a `BrokerRepresentative`'s `X-User-ID` equals the `Broker` id
        reachable from the addressed resource — `ERR_UNAUTHORIZED`. All endpoints."

        The role lists these six probes fall outside of are, from PRD §4:
        "| POST | `/national-rate-caps` | Publishes one national rate cap for a tenor bucket effective from a date. | `SystemAdmin` |"
        "| POST | `/deposit-classifications` | Records a brokered-versus-non-brokered determination for a program, guarded by `expected_program_version`, and becomes the program's governing classification. | `SystemAdmin`, `ComplianceReviewer` |"
        "| POST | `/deposit-placements` | Books a deposit tranche under a program with its principal, rate, issue date and tenor. | `SystemAdmin`, `FundingDeskOfficer` |"
        "| POST | `/deposit-programs` | Opens a funding program for a bank with its channel claim, product terms and rate. | `SystemAdmin`, `FundingDeskOfficer` |"
        "| POST | `/institutions/{id}/concentration-limits` | Sets a board limit for one concentration metric, superseding any active limit on that metric and re-evaluating posture immediately. | `SystemAdmin`, `TreasuryController` |"
        "| PATCH | `/institutions/{id}/capital-category` | Supervisory re-categorisation, guarded by `expected_institution_version`; a downgrade out of `WELL_CAPITALIZED` caps the bank and cascades a rate-cap re-evaluation over its active placements. | `SystemAdmin`, `Examiner` |"

        Design: Corner/rbac/corner_each_role_is_refused_other_roles_exclusive_operations
        """
        env = _denied_world()
        institution, program = env["institution"], env["program"]
        if probe == "benchmark_publication_by_the_desk":
            response = api_client.publish_national_rate_cap(
                f.national_rate_cap_payload(
                    tenor_bucket="DAYS_31_90", published_national_rate_bps=400,
                    effective_date="2026-07-01",
                ),
                DESK,
            )
        elif probe == "classification_by_the_desk":
            # The observed version is current, so nothing but the role gate can fire.
            response = api_client.create_classification(
                f.classification_payload(program["id"], program["version"]), DESK
            )
        elif probe == "placement_by_compliance":
            response = api_client.create_placement(
                f.placement_payload(program["id"], principal_cents=1_000_000_000,
                                    rate_bps=400),
                COMPLIANCE,
            )
        elif probe == "program_by_treasury":
            response = api_client.create_program(
                f.program_payload(institution["id"], program_name="Treasury Program",
                                  offered_rate_bps=300),
                TREASURY,
            )
        elif probe == "board_limit_by_the_examiner":
            response = api_client.create_concentration_limit(
                institution["id"],
                f.concentration_limit_payload(warning_threshold_bps=2000,
                                             breach_threshold_bps=4000),
                EXAMINER,
            )
        else:
            response = api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "ADEQUATELY_CAPITALIZED",
                    "expected_institution_version": institution["version"],
                },
                COMPLIANCE,
            )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_the_refused_cross_role_calls_write_nothing(self):
        """A request refused on the role gate is refused before it can write.

        PRD §2.1: "When the headers are well formed but the acting role does not
        appear on the authorised-role list of the addressed endpoint (§4), the
        request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        PRD §2.8: "A request never accumulates errors. Every request is evaluated
        against the rules below in ascending priority order and, on the first rule it
        violates, is rejected with that rule's error and nothing else is evaluated."

        Design: Corner/rbac/corner_each_role_is_refused_other_roles_exclusive_operations
        """
        env = _denied_world()
        institution, program = env["institution"], env["program"]
        baseline = fx.read_institution(institution["id"])
        validate_error(
            api_client.publish_national_rate_cap(
                f.national_rate_cap_payload(tenor_bucket="DAYS_31_90",
                                            published_national_rate_bps=400,
                                            effective_date="2026-07-01"),
                DESK,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        validate_error(
            api_client.create_classification(
                f.classification_payload(program["id"], program["version"]), DESK
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        validate_error(
            api_client.create_placement(
                f.placement_payload(program["id"], principal_cents=1_000_000_000,
                                    rate_bps=400),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        validate_error(
            api_client.create_program(
                f.program_payload(institution["id"], program_name="Treasury Program",
                                  offered_rate_bps=300),
                TREASURY,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        validate_error(
            api_client.create_concentration_limit(
                institution["id"],
                f.concentration_limit_payload(warning_threshold_bps=2000,
                                             breach_threshold_bps=4000),
                EXAMINER,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        validate_error(
            api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "ADEQUATELY_CAPITALIZED",
                    "expected_institution_version": baseline["version"],
                },
                COMPLIANCE,
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        _, benchmark_meta = validate_paginated(api_client.list_national_rate_caps(ADMIN))
        assert benchmark_meta["total_count"] == 0, (
            "the refused publication must leave no benchmark behind, got "
            f"{benchmark_meta['total_count']}"
        )
        _, classification_meta = validate_paginated(api_client.list_classifications(ADMIN))
        assert classification_meta["total_count"] == 0, (
            "the refused determination must leave no classification behind, got "
            f"{classification_meta['total_count']}"
        )
        _, placement_meta = validate_paginated(api_client.list_placements(ADMIN))
        assert placement_meta["total_count"] == 0, (
            "the refused booking must leave no tranche behind, got "
            f"{placement_meta['total_count']}"
        )
        _, program_meta = validate_paginated(api_client.list_programs(ADMIN))
        assert program_meta["total_count"] == 1, (
            "only the programme opened by the desk in setup may exist, got "
            f"{program_meta['total_count']}"
        )
        _, limit_meta = validate_paginated(
            api_client.list_concentration_limits(institution["id"], ADMIN)
        )
        assert limit_meta["total_count"] == 0, (
            f"the refused board limit must not be created, got {limit_meta['total_count']}"
        )
        held = fx.read_institution(institution["id"])
        assert held["capital_category"] == "WELL_CAPITALIZED", (
            "the refused re-categorisation must not move the capital category, got "
            f"{held['capital_category']}"
        )
        assert held["version"] == baseline["version"], (
            "a rejected write does not advance the bank's version: expected "
            f"{baseline['version']}, got {held['version']}"
        )

    def test_a_two_role_route_admits_both_listed_roles_and_refuses_a_third(self):
        """Counterparty registration names two roles, and both of them really work
        on the same body; a role outside the pair is refused.

        PRD §4: "| POST | `/brokers` | Registers a deposit broker or listing service counterparty. | `SystemAdmin`, `FundingDeskOfficer` |"

        PRD §2.1: "When the headers are well formed but the acting role does not
        appear on the authorised-role list of the addressed endpoint (§4), the
        request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_shared_operations_accept_more_than_one_role
        """
        fx.set_clock(DEFAULT_CLOCK_INSTANT)
        by_admin = validate_success(
            api_client.create_broker(
                f.broker_payload(legal_name="Shared Route Brokers A LLC"), ADMIN
            ),
            expected_status=201,
        )
        assert by_admin["legal_name"] == "Shared Route Brokers A LLC", (
            f"the administrator's registration must persist, got {by_admin['legal_name']}"
        )
        by_desk = validate_success(
            api_client.create_broker(
                f.broker_payload(legal_name="Shared Route Brokers B LLC"), DESK
            ),
            expected_status=201,
        )
        assert by_desk["legal_name"] == "Shared Route Brokers B LLC", (
            f"the desk's registration must persist, got {by_desk['legal_name']}"
        )
        assert by_desk["id"] != by_admin["id"], (
            "the two accepted registrations must be separate counterparties"
        )
        validate_error(
            api_client.create_broker(
                f.broker_payload(legal_name="Shared Route Brokers C LLC"), TREASURY
            ),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        _, meta = validate_paginated(api_client.list_brokers(ADMIN))
        assert meta["total_count"] == 2, (
            "exactly the two registrations by listed roles may exist, got "
            f"{meta['total_count']}"
        )

    def test_a_shared_determination_and_attestation_accept_the_second_listed_role(self):
        """The determination route lists the administrator beside compliance, and the
        state-action route lists compliance beside the desk; each second role is
        exercised on a body the first role would also have been allowed to send.

        PRD §4: "| POST | `/deposit-classifications` | Records a brokered-versus-non-brokered determination for a program, guarded by `expected_program_version`, and becomes the program's governing classification. | `SystemAdmin`, `ComplianceReviewer` |"

        PRD §4: "| POST | `/deposit-programs/{id}/state-actions` | Drives the program state machine with `action` of `ATTEST_CLASSIFICATION`, `SUSPEND`, `RESUME`, `START_RECLASSIFICATION` or `CLOSE`, plus an optional `note`. | `SystemAdmin`, `FundingDeskOfficer`, `ComplianceReviewer` |"

        Design: Corner/rbac/corner_shared_operations_accept_more_than_one_role
        """
        institution = _bank(legal_name="Shared Route Bank NA")
        env = _brokered_program(institution, program_name="Shared Brokered CD")
        determination = validate_success(
            api_client.create_classification(
                f.classification_payload(env["program"]["id"], env["program"]["version"]),
                ADMIN,
            ),
            expected_status=201,
        )
        assert determination["determined_by_user_id"] == USER_IDS["admin"], (
            "the administrator's identifier must be recorded on the determination, got "
            f"{determination['determined_by_user_id']}"
        )
        assert determination["determined_class"] == "BROKERED", (
            "a discretionary deposit broker programme is brokered, got "
            f"{determination['determined_class']}"
        )
        attested = validate_success(
            api_client.program_state_action(
                env["program"]["id"], {"action": "ATTEST_CLASSIFICATION"}, COMPLIANCE
            )
        )
        assert attested["state"] == "OPEN_FOR_PLACEMENT", (
            f"the attestation must open the programme, got {attested['state']}"
        )
        assert attested["attested_by_user_id"] == USER_IDS["compliance"], (
            "the attesting identifier must be the reviewer that acted, got "
            f"{attested['attested_by_user_id']}"
        )

    def test_the_drafting_identifier_may_not_approve_its_own_contingency_plan(self):
        """The same opaque identifier drafts and then tries to bless the plan while it
        sits in the reviewable status, so nothing but the duty comparison can refuse
        it; a second identifier then approves the very same plan.

        PRD §2.9: "Approving a liquidity contingency plan requires an acting
        identifier different from the plan's `prepared_by_user_id`."

        PRD §2.9: "Because the comparison ignores `X-User-Role`, a `SystemAdmin` that
        prepared an artefact cannot bless it either."

        PRD §3.7: "From `UNDER_REVIEW` the second line either approves, moving the
        plan to `APPROVED` and stamping `approved_by_user_id`, or rejects, moving it
        to the terminal `REJECTED` with no derived-field change; both decisions
        require an acting identifier different from the plan's `prepared_by_user_id`."

        Design: Corner/rbac/corner_same_user_id_cannot_prepare_and_approve
        """
        institution = _bank(legal_name="Duty Plan Bank NA")
        drafter = make_system_admin_headers("op_dual")
        plan = validate_success(
            api_client.create_contingency_plan(
                institution["id"],
                f.contingency_plan_payload(effective_from="2026-08-01",
                                           effective_to="2026-12-31"),
                drafter,
            ),
            expected_status=201,
        )
        assert plan["prepared_by_user_id"] == "op_dual", (
            f"the drafting identifier must be stamped, got {plan['prepared_by_user_id']}"
        )
        assert plan["approved_by_user_id"] is None, (
            f"a new plan carries no approver, got {plan['approved_by_user_id']}"
        )
        under_review = validate_success(
            api_client.plan_lifecycle_action(
                plan["id"], {"action": "SUBMIT_FOR_REVIEW"}, drafter
            )
        )
        assert under_review["status"] == "UNDER_REVIEW", (
            "the plan must be in the reviewable status before the approval probe, got "
            f"{under_review['status']}"
        )
        validate_error(
            api_client.plan_lifecycle_action(plan["id"], {"action": "APPROVE"}, drafter),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )
        held = fx.read_plan(plan["id"])
        assert held["status"] == "UNDER_REVIEW", (
            f"the refused approval must leave the status alone, got {held['status']}"
        )
        assert held["approved_by_user_id"] is None, (
            "the refused approval must not stamp an approver, got "
            f"{held['approved_by_user_id']}"
        )
        approved = validate_success(
            api_client.plan_lifecycle_action(plan["id"], {"action": "APPROVE"}, COMPLIANCE)
        )
        assert approved["status"] == "APPROVED", (
            f"a second identifier may approve the same plan, got {approved['status']}"
        )
        assert approved["approved_by_user_id"] == USER_IDS["compliance"], (
            "the approving identifier must be stamped, got "
            f"{approved['approved_by_user_id']}"
        )

    def test_the_determining_identifier_may_not_attest_its_own_determination(self):
        """The attestation comparison reaches into another record — the governing
        determination — so the identifier that determined cannot attest, whichever
        listed role it wears.

        PRD §2.9: "Attesting a program's classification requires an acting identifier
        different from the `determined_by_user_id` of the governing determination —
        the only one of the five that compares against a different record's field
        rather than the addressed record's own preparer."

        Design: Corner/rbac/corner_same_user_id_cannot_prepare_and_approve
        """
        institution = _bank(legal_name="Duty Attest Bank NA")
        env = _brokered_program(institution, program_name="Duty Brokered CD")
        determiner = make_compliance_headers("op_dual")
        determination = validate_success(
            api_client.create_classification(
                f.classification_payload(env["program"]["id"], env["program"]["version"]),
                determiner,
            ),
            expected_status=201,
        )
        assert determination["determined_by_user_id"] == "op_dual", (
            "the determining identifier must be stamped, got "
            f"{determination['determined_by_user_id']}"
        )
        classified = fx.read_program(env["program"]["id"])
        assert classified["state"] == "CLASSIFIED", (
            "the programme must be classified before the attestation probe, got "
            f"{classified['state']}"
        )
        validate_error(
            api_client.program_state_action(
                env["program"]["id"], {"action": "ATTEST_CLASSIFICATION"}, determiner
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )
        held = fx.read_program(env["program"]["id"])
        assert held["state"] == "CLASSIFIED", (
            f"the refused attestation must not open the programme, got {held['state']}"
        )
        assert held["attested_by_user_id"] is None, (
            f"no attester may be stamped, got {held['attested_by_user_id']}"
        )
        attested = validate_success(
            api_client.program_state_action(
                env["program"]["id"], {"action": "ATTEST_CLASSIFICATION"}, DESK
            )
        )
        assert attested["state"] == "OPEN_FOR_PLACEMENT", (
            "a different identifier may attest the same determination, got "
            f"{attested['state']}"
        )
        assert attested["attested_by_user_id"] == USER_IDS["desk"], (
            f"the attesting identifier must be stamped, got {attested['attested_by_user_id']}"
        )

    def test_a_broker_representative_reads_exactly_its_own_rows(self):
        """The representative's identifier is the counterparty row's own id, and the
        three reads it is scoped to all resolve to that counterparty.

        PRD §2.1: "When `X-User-Role` is `BrokerRepresentative`, `X-User-ID` is the
        `id` of the acting `Broker` row, and ownership checks on any resource that
        references a `Broker` compare the resource's broker foreign-key field to
        `X-User-ID`."

        PRD §2.1: "A broker representative is read-only and narrowly scoped — it may
        read its own broker record, its own agreements and its own fee summary, and
        nothing else."

        PRD §3.2: "A broker representative may read that summary, its own counterparty
        record and its own agreements, and the agreement list may be narrowed by
        `status`."

        Design: Corner/rbac/corner_broker_representative_is_scoped_to_its_own_rows
        """
        env = _two_broker_world()
        broker_a, agreement_a = env["broker_a"], env["agreement_a"]
        rep_a = make_broker_representative_headers(broker_a["id"])
        own_record = validate_success(api_client.get_broker(broker_a["id"], rep_a))
        assert own_record["id"] == broker_a["id"], (
            f"the representative must read its own row, got {own_record['id']}"
        )
        own_agreements, meta = validate_paginated(
            api_client.list_broker_agreements(broker_a["id"], rep_a)
        )
        assert meta["total_count"] == 1, (
            f"only its own single agreement may be listed, got {meta['total_count']}"
        )
        assert own_agreements[0]["id"] == agreement_a["id"], (
            f"the listed agreement must be its own, got {own_agreements[0]['id']}"
        )
        own_agreement = validate_success(
            api_client.get_agreement(agreement_a["id"], rep_a)
        )
        assert own_agreement["id"] == agreement_a["id"], (
            f"the representative must read its own agreement, got {own_agreement['id']}"
        )
        summary = validate_success(api_client.get_fee_summary(agreement_a["id"], rep_a))
        assert summary["agreement_id"] == agreement_a["id"], (
            f"the summary must name its own agreement, got {summary['agreement_id']}"
        )
        assert summary["fee_structure"] == "FLAT_FEE", (
            f"the summary echoes the contracted construct, got {summary['fee_structure']}"
        )
        assert summary["line_count"] == 0, (
            f"no tranche is active yet, so no line contributes, got {summary['line_count']}"
        )
        assert summary["accrued_fee_cents"] == 0, (
            f"an unplaced agreement has accrued nothing, got {summary['accrued_fee_cents']}"
        )

    @pytest.mark.parametrize(
        "target",
        ["broker_record", "agreement_collection", "agreement_record", "fee_summary"],
    )
    def test_a_broker_representative_is_refused_a_sibling_counterpartys_row(self, target):
        """Every one of these routes lists `BrokerRepresentative`, so the role gate
        alone would admit the call; what refuses it is the ownership comparison
        against the addressed row's counterparty.

        PRD §2.1: "Any request whose addressed resource resolves to a different broker
        is refused with `ERR_UNAUTHORIZED`."

        PRD §2.8: "2. Authorisation: the acting role appears on the target endpoint's
        list, and a `BrokerRepresentative`'s `X-User-ID` equals the `Broker` id
        reachable from the addressed resource — `ERR_UNAUTHORIZED`. All endpoints."

        Design: Corner/rbac/corner_broker_representative_is_scoped_to_its_own_rows
        """
        env = _two_broker_world()
        rep_a = make_broker_representative_headers(env["broker_a"]["id"])
        if target == "broker_record":
            response = api_client.get_broker(env["broker_b"]["id"], rep_a)
        elif target == "agreement_collection":
            response = api_client.list_broker_agreements(env["broker_b"]["id"], rep_a)
        elif target == "agreement_record":
            response = api_client.get_agreement(env["agreement_b"]["id"], rep_a)
        else:
            response = api_client.get_fee_summary(env["agreement_b"]["id"], rep_a)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    @pytest.mark.parametrize("collection", ["brokers", "deposit_programs"])
    def test_a_broker_representative_is_absent_from_unscoped_collections(self, collection):
        """Unscoped collections cannot be narrowed to one counterparty, so the role
        does not appear on their lists at all.

        PRD §4: "| GET | `/brokers` | Lists counterparties, filterable by `broker_type` and `registration_status`. | `SystemAdmin`, `FundingDeskOfficer`, `ComplianceReviewer`, `TreasuryController`, `Examiner` |"

        PRD §4: "| GET | `/deposit-programs` | Lists programs, filterable by bank, counterparty, `state` and `funding_channel_claim`. | `SystemAdmin`, `FundingDeskOfficer`, `ComplianceReviewer`, `TreasuryController`, `Examiner` |"

        PRD §2.1: "When the headers are well formed but the acting role does not
        appear on the authorised-role list of the addressed endpoint (§4), the
        request is refused with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_broker_representative_is_scoped_to_its_own_rows
        """
        env = _two_broker_world()
        rep_a = make_broker_representative_headers(env["broker_a"]["id"])
        if collection == "brokers":
            response = api_client.list_brokers(rep_a)
        else:
            response = api_client.list_programs(rep_a)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)


def _version_cascade_world() -> dict:
    """A bank downgraded out of the exempt regime after a brokered programme was
    opened, so the programme's version has been advanced by somebody else's write."""
    institution = _bank(legal_name="Version Bank NA")
    fx.publish_rate_cap(tenor_bucket="DAYS_31_90", published_national_rate_bps=400,
                        effective_date="2026-07-01")
    env = _brokered_program(institution, program_name="Version Brokered CD",
                            offered_rate_bps=400)
    assert env["program"]["version"] == 1, (
        f"a freshly opened programme is at version 1, got {env['program']['version']}"
    )
    env["observed_program_version"] = env["program"]["version"]
    env["institution"] = fx.change_capital_category(
        institution["id"], "ADEQUATELY_CAPITALIZED", None, EXAMINER
    )
    return env


class TestCrossCuttingComplexityLayers:
    """Observed-version guards and rate-threshold surveillance across the
    determination, re-categorisation and booking paths (PRD §2.6, §3.1 and §3.6)."""

    def test_a_determination_holding_a_superseded_program_version_is_rejected(self):
        """The reviewer never touched the programme: a supervisory re-categorisation
        advanced its version, and the version guard alone catches that.

        PRD §2.6: "If that value does not equal the program's current `version`, the
        determination is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412)."

        PRD §3.1: "Every one of the bank's programs whose `state` is not `CLOSED` has
        its `effective_cap_bps` recomputed and its `version` incremented by exactly 1,
        processed in `created_at` ascending order"

        Design: Corner/cross_cutting_complexity_layers/corner_stale_program_version_rejected_on_classification_create
        """
        env = _version_cascade_world()
        cascaded = fx.read_program(env["program"]["id"])
        assert cascaded["version"] == 2, (
            f"the cascade must advance the programme's version to 2, got {cascaded['version']}"
        )
        assert cascaded["effective_cap_bps"] == 475, (
            "the recomputed ceiling is the published 400 bps plus 75, got "
            f"{cascaded['effective_cap_bps']}"
        )
        assert cascaded["state"] == "PENDING_CLASSIFICATION", (
            f"the programme is still awaiting its determination, got {cascaded['state']}"
        )
        validate_error(
            api_client.create_classification(
                f.classification_payload(env["program"]["id"],
                                         env["observed_program_version"]),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_STALE_PROGRAM_VERSION.value,
        )
        held = fx.read_program(env["program"]["id"])
        assert held["governing_classification_id"] is None, (
            "the refused determination must not become the governing one, got "
            f"{held['governing_classification_id']}"
        )
        assert held["version"] == 2, (
            f"a rejected write does not advance the programme's version, got {held['version']}"
        )
        assert held["state"] == "PENDING_CLASSIFICATION", (
            f"the refused determination must not classify the programme, got {held['state']}"
        )
        _, meta = validate_paginated(api_client.list_classifications(COMPLIANCE))
        assert meta["total_count"] == 0, (
            f"no determination row may be created, got {meta['total_count']}"
        )

    def test_re_reading_the_program_version_lets_the_same_determination_through(self):
        """Exactly the same body, retried against the version the client has now
        observed, is accepted; the witness it stamps is that observed version plus its
        own increment.

        PRD §2.6: "Without the guard, a client holding an older view of the program
        could supersede a governing determination it never saw; with it, the outcome
        is a deterministic rejection that tells the client to re-read the program
        first."

        PRD §3.4: "The determination also captures `program_version_at_determination`,
        which is the program's `version` immediately after this determination has been
        applied, that is the observed `expected_program_version` plus the
        determination's own increment of 1."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_program_version_rejected_on_classification_create
        """
        env = _version_cascade_world()
        validate_error(
            api_client.create_classification(
                f.classification_payload(env["program"]["id"],
                                         env["observed_program_version"]),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_STALE_PROGRAM_VERSION.value,
        )
        re_read = fx.read_program(env["program"]["id"])
        assert re_read["version"] == 2, (
            f"the client must now observe version 2, got {re_read['version']}"
        )
        determination = validate_success(
            api_client.create_classification(
                f.classification_payload(env["program"]["id"], re_read["version"]),
                COMPLIANCE,
            ),
            expected_status=201,
        )
        assert determination["program_version_at_determination"] == 3, (
            "the stamped witness is the observed 2 plus this determination's own "
            f"increment of 1, got {determination['program_version_at_determination']}"
        )
        classified = fx.read_program(env["program"]["id"])
        assert classified["state"] == "CLASSIFIED", (
            f"the accepted determination must classify the programme, got {classified['state']}"
        )
        assert classified["version"] == 3, (
            f"the determination increments the version by exactly one, got {classified['version']}"
        )
        assert classified["governing_classification_id"] == determination["id"], (
            "the new determination must govern the programme, got "
            f"{classified['governing_classification_id']}"
        )

    def test_a_replayed_institution_version_cannot_revert_a_downgrade(self):
        """Any category legitimately succeeds any other, so a second writer replaying
        its own stale view would otherwise silently undo the downgrade; only the
        version guard stops it.

        PRD §2.6: "If that value does not equal the institution's current `version`,
        the re-categorisation is rejected with `ERR_STALE_INSTITUTION_VERSION` (HTTP
        412)."

        PRD §2.6: "Any capital category is a legitimate successor to any other, so
        nothing else would stop a writer holding a stale view from silently reverting
        a supervisory downgrade."

        PRD §3.1: "From the capital category the system immediately derives
        `rate_cap_regime`, which is `EXEMPT` when the category is `WELL_CAPITALIZED`
        and `CAPPED` for every other category."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_institution_version_rejected_on_capital_recategorisation
        """
        institution = _bank(legal_name="Replay Bank NA")
        observed_version = institution["version"]
        assert observed_version == 1, (
            f"a freshly registered bank is at version 1, got {observed_version}"
        )
        downgraded = validate_success(
            api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "ADEQUATELY_CAPITALIZED",
                    "expected_institution_version": observed_version,
                },
                EXAMINER,
            )
        )
        assert downgraded["capital_category"] == "ADEQUATELY_CAPITALIZED", (
            f"the downgrade must be applied, got {downgraded['capital_category']}"
        )
        assert downgraded["rate_cap_regime"] == "CAPPED", (
            "any category other than well capitalised is capped, got "
            f"{downgraded['rate_cap_regime']}"
        )
        assert downgraded["version"] == 2, (
            f"the accepted re-categorisation lifts the version to 2, got {downgraded['version']}"
        )
        validate_error(
            api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "WELL_CAPITALIZED",
                    "expected_institution_version": observed_version,
                },
                EXAMINER,
            ),
            ApiErrorId.ERR_STALE_INSTITUTION_VERSION.value,
        )
        held = fx.read_institution(institution["id"])
        assert held["capital_category"] == "ADEQUATELY_CAPITALIZED", (
            "the refused revert must not undo the downgrade, got "
            f"{held['capital_category']}"
        )
        assert held["rate_cap_regime"] == "CAPPED", (
            f"the regime must stay capped, got {held['rate_cap_regime']}"
        )
        assert held["version"] == 2, (
            f"a rejected write does not increment the version, got {held['version']}"
        )

    def test_the_re_read_version_admits_the_next_re_categorisation(self):
        """Once the client re-reads the bank, the next supervisory move is accepted and
        the counter advances by exactly one again.

        PRD §2.6: "A supervisory capital re-categorisation must carry
        `expected_institution_version`, a required input field holding the `version` of
        the target `Institution` as the client last read it."

        PRD §3.1: "From the capital category the system immediately derives
        `rate_cap_regime`, which is `EXEMPT` when the category is `WELL_CAPITALIZED`
        and `CAPPED` for every other category."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_institution_version_rejected_on_capital_recategorisation
        """
        institution = _bank(legal_name="Re-read Bank NA")
        observed_version = institution["version"]
        fx.change_capital_category(
            institution["id"], "ADEQUATELY_CAPITALIZED", observed_version, EXAMINER
        )
        validate_error(
            api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "WELL_CAPITALIZED",
                    "expected_institution_version": observed_version,
                },
                EXAMINER,
            ),
            ApiErrorId.ERR_STALE_INSTITUTION_VERSION.value,
        )
        re_read = fx.read_institution(institution["id"])
        assert re_read["version"] == 2, (
            f"the client must now observe version 2, got {re_read['version']}"
        )
        further = validate_success(
            api_client.change_capital_category(
                institution["id"],
                {
                    "capital_category": "UNDERCAPITALIZED",
                    "expected_institution_version": re_read["version"],
                },
                EXAMINER,
            )
        )
        assert further["capital_category"] == "UNDERCAPITALIZED", (
            f"the re-read view admits the next move, got {further['capital_category']}"
        )
        assert further["rate_cap_regime"] == "CAPPED", (
            f"the regime stays capped below well capitalised, got {further['rate_cap_regime']}"
        )
        assert further["version"] == 3, (
            f"the second accepted write lifts the version to 3, got {further['version']}"
        )

    def test_the_surveillance_dimension_walks_as_the_published_ceiling_moves(self):
        """The tranche's own rate never changes; three successive publications move the
        ceiling under it and the surveillance dimension walks with the outcomes.

        PRD §3.6: "An `UNREVIEWED` tranche whose review comes back `PASS` or
        `EXEMPT_NO_CAP` moves `UNREVIEWED → RATE_CHECKED`; an `UNREVIEWED` tranche
        whose review comes back `BREACH` moves `UNREVIEWED → FLAGGED` and the appended
        review carries a `breach_bps` above zero."

        PRD §3.6: "A `FLAGGED` tranche whose review comes back `PASS` or
        `EXEMPT_NO_CAP` moves `FLAGGED → REMEDIATED`, with the appended review carrying
        a `breach_bps` of zero"

        PRD §3.6: "The outcome drives the surveillance dimension and nothing else —
        `funding_status` never moves on a review."

        PRD §3.6: "`breach_bps` is the amount by which `offered_rate_bps` exceeds
        `effective_cap_bps`, floored at zero so it is never negative, and it is 0
        whenever `effective_cap_bps` is null."

        Design: Corner/cross_cutting_complexity_layers/corner_rate_threshold_boundary_breach_and_reset
        """
        env = _capped_threshold_world()
        placement = env["placement"]
        first = validate_success(
            api_client.create_rate_cap_check(
                placement["id"], f.rate_cap_check_payload("2026-08-01"), COMPLIANCE
            ),
            expected_status=201,
        )
        asserts.assert_rate_cap_check(first)
        assert first["national_rate_bps_snapshot"] == 400, (
            f"the only publication yet is 400 bps, got {first['national_rate_bps_snapshot']}"
        )
        assert first["effective_cap_bps"] == 475, (
            f"the ceiling is 400 plus 75 with no local leg, got {first['effective_cap_bps']}"
        )
        assert first["breach_bps"] == 0, (
            f"470 sits below 475, so nothing is exceeded, got {first['breach_bps']}"
        )
        assert first["outcome"] == "PASS", (
            f"a capped bank inside its ceiling passes, got {first['outcome']}"
        )
        after_first = fx.read_placement(placement["id"])
        assert after_first["compliance_status"] == "RATE_CHECKED", (
            f"an unreviewed tranche that passes is rate checked, got {after_first['compliance_status']}"
        )
        fx.publish_rate_cap(tenor_bucket="DAYS_31_90", published_national_rate_bps=300,
                            effective_date="2026-08-15")
        second = validate_success(
            api_client.create_rate_cap_check(
                placement["id"], f.rate_cap_check_payload("2026-08-15"), COMPLIANCE
            ),
            expected_status=201,
        )
        asserts.assert_rate_cap_check(second)
        assert second["national_rate_bps_snapshot"] == 300, (
            "on its own effective date the 300 bps publication governs, got "
            f"{second['national_rate_bps_snapshot']}"
        )
        assert second["effective_cap_bps"] == 375, (
            f"the ceiling falls to 300 plus 75, got {second['effective_cap_bps']}"
        )
        assert second["breach_bps"] == 95, (
            f"470 exceeds 375 by 95 basis points, got {second['breach_bps']}"
        )
        assert second["outcome"] == "BREACH", (
            f"a positive excess is a breach, got {second['outcome']}"
        )
        after_second = fx.read_placement(placement["id"])
        assert after_second["compliance_status"] == "FLAGGED", (
            f"a breaching review flags the tranche, got {after_second['compliance_status']}"
        )
        fx.publish_rate_cap(tenor_bucket="DAYS_31_90", published_national_rate_bps=450,
                            effective_date="2026-09-01")
        third = validate_success(
            api_client.create_rate_cap_check(
                placement["id"], f.rate_cap_check_payload("2026-09-01"), COMPLIANCE
            ),
            expected_status=201,
        )
        asserts.assert_rate_cap_check(third)
        assert third["national_rate_bps_snapshot"] == 450, (
            f"the latest effective publication is 450 bps, got {third['national_rate_bps_snapshot']}"
        )
        assert third["effective_cap_bps"] == 525, (
            f"the ceiling recovers to 450 plus 75, got {third['effective_cap_bps']}"
        )
        assert third["breach_bps"] == 0, (
            f"470 is back inside the ceiling, got {third['breach_bps']}"
        )
        assert third["outcome"] == "PASS", (
            f"the recovered ceiling passes, got {third['outcome']}"
        )
        final = fx.read_placement(placement["id"])
        assert final["compliance_status"] == "REMEDIATED", (
            f"a flagged tranche that passes is remediated, got {final['compliance_status']}"
        )
        assert final["rate_bps"] == 470, (
            f"only the published threshold moved, not the tranche's rate, got {final['rate_bps']}"
        )
        assert final["funding_status"] == "PENDING", (
            f"no review may move the funding dimension, got {final['funding_status']}"
        )
        checks, meta = validate_paginated(
            api_client.list_rate_cap_checks(placement["id"], COMPLIANCE)
        )
        assert meta["total_count"] == 3, (
            f"the surveillance record is append-only, got {meta['total_count']}"
        )
        assert [check["check_date"] for check in checks] == [
            "2026-08-01", "2026-08-15", "2026-09-01"
        ], f"reviews are listed by check date ascending, got {[c['check_date'] for c in checks]}"

    def test_the_publication_effective_date_edge_decides_a_booking(self):
        """A publication governs from its own effective date, so the day before it the
        old ceiling still admits the same rate and on the date itself the new one
        refuses it.

        PRD §3.1: "A publication governs the half-open interval that begins on its own
        `effective_date` and ends the day the next publication for the same bucket
        becomes effective"

        PRD §3.5: "Where the bank's `rate_cap_regime` is `CAPPED`, the tranche's
        `rate_bps` must not exceed the ceiling computed as of its own `issue_date`;
        equality passes and one basis point above is refused with
        `ERR_RATE_CAP_EXCEEDED`"

        Design: Corner/cross_cutting_complexity_layers/corner_rate_threshold_boundary_breach_and_reset
        """
        env = _capped_threshold_world()
        fx.publish_rate_cap(tenor_bucket="DAYS_31_90", published_national_rate_bps=300,
                            effective_date="2026-08-15")
        accepted = validate_success(
            api_client.create_placement(
                f.placement_payload(env["program"]["id"], principal_cents=100_000_000,
                                    rate_bps=470, issue_date="2026-08-14", tenor_days=60),
                DESK,
            ),
            expected_status=201,
        )
        assert accepted["issue_date"] == "2026-08-14", (
            f"the accepted tranche keeps its own issue date, got {accepted['issue_date']}"
        )
        assert accepted["funding_status"] == "PENDING", (
            f"a booked tranche starts pending, got {accepted['funding_status']}"
        )
        validate_error(
            api_client.create_placement(
                f.placement_payload(env["program"]["id"], principal_cents=100_000_000,
                                    rate_bps=470, issue_date="2026-08-15", tenor_days=60),
                DESK,
            ),
            ApiErrorId.ERR_RATE_CAP_EXCEEDED.value,
        )
        _, meta = validate_paginated(api_client.list_placements(DESK))
        assert meta["total_count"] == 2, (
            "only the setup tranche and the accepted edge tranche may exist, got "
            f"{meta['total_count']}"
        )


class TestConsistencyModel:
    """Every derived figure is settled inside the request that moved the money
    (PRD §2.11, §3.5 and §3.7)."""

    def test_the_activation_response_and_the_bank_read_agree_in_the_same_instant(self):
        """One activation is the only write; the response itself and the very next
        reads already carry every derived figure, with no second read needed to settle.

        PRD §2.11: "Wholesale metrics are refreshed as part of the same request that
        moved the money, never lazily. Each recomputation of the balance buckets is
        immediately followed by a recomputation of the point-in-time wholesale funding
        ratio and of the concentration posture, in that order, so a caller reading the
        bank straight after a funding action sees the posture that already reflects
        it."

        PRD §3.5: "On success the tranche's `classified_as` is set from the
        `determined_class` of the program's governing determination, its
        `principal_cents` is added to the matching wholesale bucket on the bank and the
        concentration posture is re-run, the same amount is added to the program's
        `outstanding_principal_cents`, and the agreement's `accrued_fee_cents` together
        with this tranche's own `fee_accrual_cents` are recomputed by the fee rule of
        §3.2."

        Design: Corner/consistency_model/corner_every_derived_field_is_visible_in_the_same_response
        """
        env = _immediate_world()
        activated = validate_success(
            api_client.funding_action(
                env["placement"]["id"], {"action": "ACTIVATE"}, DESK
            )
        )
        assert activated["funding_status"] == "ACTIVE", (
            f"the activation response already shows the tranche funded, got {activated['funding_status']}"
        )
        assert activated["classified_as"] == "BROKERED", (
            "the inherited class is on the same response, got "
            f"{activated['classified_as']}"
        )
        assert activated["fee_accrual_cents"] == 25000, (
            "the flat contracted fee is already accrued on this line, got "
            f"{activated['fee_accrual_cents']}"
        )
        bank = fx.read_institution(env["institution"]["id"])
        assert bank["brokered_deposits_cents"] == 1_000_000_000, (
            f"the brokered bucket already holds the tranche, got {bank['brokered_deposits_cents']}"
        )
        assert bank["total_deposits_cents"] == 31_000_000_000, (
            "total deposits are the core baseline plus the brokered bucket, got "
            f"{bank['total_deposits_cents']}"
        )
        assert bank["wholesale_funding_ratio_bps"] == 322, (
            "1,000,000,000 of 31,000,000,000 is 322 basis points with the remainder "
            f"discarded, got {bank['wholesale_funding_ratio_bps']}"
        )
        assert bank["single_broker_max_ratio_bps"] == 322, (
            "the single counterparty's whole exposure is that same tranche, got "
            f"{bank['single_broker_max_ratio_bps']}"
        )
        assert bank["breached_metric_count"] == 0, (
            f"322 basis points breaches nothing, got {bank['breached_metric_count']}"
        )
        assert bank["concentration_posture"] == "OPEN", (
            f"the posture already reflects the activation, got {bank['concentration_posture']}"
        )
        program = fx.read_program(env["program"]["id"])
        assert program["outstanding_principal_cents"] == 1_000_000_000, (
            "the programme's outstanding principal is settled in the same instant, got "
            f"{program['outstanding_principal_cents']}"
        )

    def test_the_agreement_mirror_and_the_board_limit_reflect_the_activation_at_once(self):
        """The fee mirror on the agreement and the board limit's evaluated value are
        both current on the first read after the activation.

        PRD §3.2: "The rounding order is pinned: every line is rounded to whole cents
        first and the rounded lines are then added together to give the agreement's
        `accrued_fee_cents`."

        PRD §3.7: "Each `ACTIVE` limit then takes that value into its own
        `current_value_bps` and sets `breach_state` to `BREACH` when the value is at or
        above its `breach_threshold_bps`, to `WARNING` when the value is at or above
        its `warning_threshold_bps` but below the breach level, and to `WITHIN`
        otherwise."

        PRD §3.7: "The average-daily variant is read-only and period-scoped, requested
        by supplying a `basis` of `AVERAGE_DAILY` together with `period_start` and
        `period_end`; `basis` defaults to `POINT_IN_TIME`, under which the average-daily
        figures are all reported as 0."

        Design: Corner/consistency_model/corner_every_derived_field_is_visible_in_the_same_response
        """
        env = _immediate_world()
        validate_success(
            api_client.funding_action(
                env["placement"]["id"], {"action": "ACTIVATE"}, DESK
            )
        )
        agreement = fx.read_agreement(env["agreement"]["id"])
        assert agreement["accrued_fee_cents"] == 25000, (
            "the flat fee of the single active line is already mirrored on the "
            f"agreement, got {agreement['accrued_fee_cents']}"
        )
        limits, meta = validate_paginated(
            api_client.list_concentration_limits(env["institution"]["id"], TREASURY)
        )
        assert meta["total_count"] == 1, (
            f"exactly the one board limit exists, got {meta['total_count']}"
        )
        limit = limits[0]
        assert limit["status"] == "ACTIVE", (
            f"the board limit is the governing one, got {limit['status']}"
        )
        assert limit["current_value_bps"] == 322, (
            "the limit already carries the post-activation brokered ratio, got "
            f"{limit['current_value_bps']}"
        )
        assert limit["breach_state"] == "WITHIN", (
            "322 basis points is below the 2000 warning level, got "
            f"{limit['breach_state']}"
        )
        summary = fx.read_wholesale_summary(env["institution"]["id"], None, TREASURY)
        assert summary["avg_wholesale_cents"] == 0, (
            "with no basis supplied the average-daily figures are reported as 0, got "
            f"{summary['avg_wholesale_cents']}"
        )
        assert summary["average_daily_ratio_bps"] == 0, (
            "with no basis supplied the average-daily figures are reported as 0, got "
            f"{summary['average_daily_ratio_bps']}"
        )
