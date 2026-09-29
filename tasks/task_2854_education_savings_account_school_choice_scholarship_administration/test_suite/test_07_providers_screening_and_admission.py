"""Provider onboarding: registration, the integrity score, admission banding, sanctions."""

from test_helpers import (
    CO,
    ELEVATED_SCREENING_SCORE,
    MISSING_ID,
    PA,
    Q1_NET_CENTS,
    SCREENING_SCORE_CEILING,
    VS,
    ApiErrorId,
    assert_bare_uuid,
    assert_fraud_screening,
    assert_iso_millis,
    assert_provider,
    account_version,
    create_approve_provider_payload,
    create_materials_category,
    create_out_of_state_provider_payload,
    create_provider,
    create_provider_payload,
    create_purchase_request_payload,
    create_risky_provider_payload,
    create_sanction_payload,
    create_screening_payload,
    create_tutoring_category,
    file_provider_delisting_appeal,
    decide_appeal,
    read_account,
    read_appeal,
    read_provider,
    read_purchase_request,
    sanction_provider,
    setup_approved_provider,
    setup_funded_account,
    validate_error,
    validate_paginated,
    validate_success,
)

RISK_CEILING_FLAGS = ["OFAC_HIT", "PRIOR_DELISTING", "NO_STATE_REGISTRATION"]
PROBATION_BAND_FLAGS = ["ADDRESS_MISMATCH", "SHARED_BANK_ACCOUNT"]


class TestProviderRegistration:
    """A registration is entirely server-stamped and starts from zero risk."""

    def test_system_fields_are_minted_by_the_server(self, api):
        """PRD §2.4: "`version` is an integer that starts at 1 when the resource is created
        and increases by exactly 1 on each subsequent mutation of that resource, including
        mutations the server performs on its own initiative as part of a cascade."

        PRD §3.6: "A fresh registration sits in `DRAFT` with `screening_score` 0,
        `surveillance_score` 0, `substantiated_case_count` 0, an empty
        `authorized_category_codes`, an empty `screening_flags`, a null `screened_at`, and
        a null `sanction_reason`."

        Design: Corner/entities/provider_system_fields_are_server_generated
        """
        payload = create_provider_payload()
        for stamped in ("id", "created_at", "updated_at", "version"):
            assert stamped not in payload, (
                f"the registration input declares no {stamped}, got {payload!r}"
            )

        response = api.create_provider(payload, PA)
        assert response.status_code == 201, (
            f"a registration is created with HTTP 201, got {response.status_code}"
        )
        provider = validate_success(response, 201)
        assert_provider(provider)
        assert_bare_uuid(provider["id"], "provider.id")
        assert provider["version"] == 1, (
            f"the version starts at 1, got {provider['version']}"
        )
        assert_iso_millis(provider["created_at"], "provider.created_at")
        assert_iso_millis(provider["updated_at"], "provider.updated_at")

        assert provider["status"] == "DRAFT", (
            f"a fresh registration sits in DRAFT, got {provider['status']!r}"
        )
        assert provider["screening_score"] == 0, (
            f"with screening_score 0, got {provider['screening_score']!r}"
        )
        assert provider["surveillance_score"] == 0, (
            f"surveillance_score 0, got {provider['surveillance_score']!r}"
        )
        assert provider["substantiated_case_count"] == 0, (
            f"substantiated_case_count 0, got {provider['substantiated_case_count']!r}"
        )
        assert provider["authorized_category_codes"] == [], (
            "an empty authorized_category_codes before admission, got "
            f"{provider['authorized_category_codes']!r}"
        )
        assert provider["screening_flags"] == [], (
            f"an empty screening_flags, got {provider['screening_flags']!r}"
        )
        assert provider["screened_at"] is None, (
            f"a null screened_at, got {provider['screened_at']!r}"
        )
        assert provider["sanction_reason"] is None, (
            f"and a null sanction_reason, got {provider['sanction_reason']!r}"
        )

        assert provider["legal_name"] == payload["legal_name"], (
            f"the supplied legal_name is echoed, got {provider['legal_name']!r}"
        )
        assert provider["ein"] == payload["ein"], (
            f"as is the ein, got {provider['ein']!r}"
        )
        assert provider["address_state"] == payload["address_state"], (
            f"as is the address_state, got {provider['address_state']!r}"
        )
        assert provider["provider_type"] == payload["provider_type"], (
            f"as is the provider_type, got {provider['provider_type']!r}"
        )

        stored = read_provider(provider["id"])
        assert stored["id"] == provider["id"] and stored["version"] == 1, (
            f"the stored record matches what creation returned, got {stored!r}"
        )


class TestFraudScreeningLinkage:
    """A screening lives under the provider it references and nowhere else."""

    def test_screening_is_created_and_listed_under_its_provider(self, api):
        """PRD §3.6: "Recording a screening advances the provider `DRAFT → SCREENED` and
        copies `screening_score`, `screening_flags`, and `screened_at` onto the provider.
        It also sets `surveillance_score` equal to `screening_score`, which is correct at
        that moment because there has been no decay and no substantiated case history."

        PRD §3.6: "The weights are 60 for `OFAC_HIT`, 40 for `PRIOR_DELISTING`, 35 for
        `NO_STATE_REGISTRATION`, 25 for `SHARED_BANK_ACCOUNT`, 20 for `ADDRESS_MISMATCH`,
        and 15 for `NEW_ENTITY_UNDER_12_MONTHS`."

        Design: Corner/endpoints/fraud_screening_is_listed_under_the_provider_it_references
        """
        provider = create_provider()

        screening = validate_success(
            api.create_fraud_screening(
                provider["id"], create_screening_payload(["ADDRESS_MISMATCH"]), VS
            ),
            201,
        )
        assert_fraud_screening(screening)
        assert screening["screening_score"] == 20, (
            f"ADDRESS_MISMATCH alone weighs 20, got {screening['screening_score']}"
        )
        assert screening["provider_id"] == provider["id"], (
            f"the row records the provider it screened, got {screening['provider_id']!r}"
        )
        assert screening["screened_by_user_id"] == VS["X-User-ID"], (
            "the screener's identifier is recorded, got "
            f"{screening['screened_by_user_id']!r}"
        )
        assert_iso_millis(screening["screened_at"], "screening.screened_at")

        rows, meta = validate_paginated(api.list_fraud_screenings(provider["id"], VS))
        assert meta["total_count"] == 1, (
            f"the provider's cross-reference list holds one row, got "
            f"{meta['total_count']}"
        )
        assert rows[0]["id"] == screening["id"], (
            f"and it is the row just created, got {rows[0]!r}"
        )

        screened = read_provider(provider["id"])
        assert screened["status"] == "SCREENED", (
            f"recording the screening advanced DRAFT to SCREENED, got "
            f"{screened['status']!r}"
        )
        assert screened["screening_score"] == 20, (
            f"the score was copied onto the provider, got {screened['screening_score']}"
        )
        assert screened["surveillance_score"] == 20, (
            "the surveillance score equals the screening score at that moment, got "
            f"{screened['surveillance_score']}"
        )
        assert screened["screening_flags"] == ["ADDRESS_MISMATCH"], (
            f"and so were the flags, got {screened['screening_flags']!r}"
        )
        assert screened["screened_at"] == screening["screened_at"], (
            f"as was screened_at, got {screened['screened_at']!r}"
        )

        orphan = api.create_fraud_screening(
            MISSING_ID, create_screening_payload(["ADDRESS_MISMATCH"]), VS
        )
        validate_error(orphan, ApiErrorId.PROVIDER_NOT_FOUND.value, 404)
        _, unchanged = validate_paginated(api.list_fraud_screenings(provider["id"], VS))
        assert unchanged["total_count"] == 1, (
            "the refused screening created no orphan row anywhere, got "
            f"{unchanged['total_count']} under the real provider"
        )


class TestScreeningScoreCeiling:
    """The flag weights clamp, and a clamped score bars admission outright."""

    def test_weights_above_the_ceiling_clamp_and_admission_is_refused(self, api):
        """PRD §3.6: "A list summing above the ceiling clamps to exactly 100 —
        `OFAC_HIT` together with `PRIOR_DELISTING` and `NO_STATE_REGISTRATION` sums to 135
        and is recorded as 100 — and an empty flag list scores 0 and clears cleanly. The
        row also carries a `recommended_status` of `APPROVE` when the score is below 40,
        `PROBATION` when it is at least 40 and below 60, and `REJECT` when it is 60 or
        more"

        PRD §3.6: "Its `screening_score` must be below 60, or the attempt is
        `ERR_FRAUD_RISK_TOO_HIGH` and the provider stays in `SCREENED` — a score of exactly
        60 is already too high."

        Design: Corner/calculations/screening_flag_weights_clamp_at_the_score_ceiling
        """
        create_tutoring_category()
        provider = create_provider(create_risky_provider_payload)

        screening = validate_success(
            api.create_fraud_screening(
                provider["id"], create_screening_payload(RISK_CEILING_FLAGS), VS
            ),
            201,
        )
        assert screening["screening_score"] == SCREENING_SCORE_CEILING, (
            f"the raw 135 is recorded as 100, got {screening['screening_score']}"
        )
        assert screening["screening_score"] != 60 + 40 + 35, (
            f"the uncapped sum is never stored, got {screening['screening_score']}"
        )
        assert screening["recommended_status"] == "REJECT", (
            "a score of 60 or more recommends REJECT, got "
            f"{screening['recommended_status']!r}"
        )

        screened = read_provider(provider["id"])
        assert screened["status"] == "SCREENED", (
            f"the provider is SCREENED, got {screened['status']!r}"
        )
        assert screened["screening_score"] == SCREENING_SCORE_CEILING, (
            f"carrying the clamped 100, got {screened['screening_score']}"
        )
        assert screened["surveillance_score"] == SCREENING_SCORE_CEILING, (
            f"and a surveillance score of 100, got {screened['surveillance_score']}"
        )

        refused = api.approve_provider(
            provider["id"], create_approve_provider_payload(["TUTORING"]), VS
        )
        validate_error(refused, ApiErrorId.FRAUD_RISK_TOO_HIGH.value, 422)

        after = read_provider(provider["id"])
        assert after["status"] == "SCREENED", (
            f"the provider stays in SCREENED, not PROBATION, got {after['status']!r}"
        )
        assert after["authorized_category_codes"] == [], (
            "and no catalogue line was pinned by the refused admission, got "
            f"{after['authorized_category_codes']!r}"
        )
        assert after["sanction_reason"] is None, (
            f"nor was any sanction recorded, got {after['sanction_reason']!r}"
        )


class TestProviderSanctionCycle:
    """PROBATION and REINSTATE form a cycle; PERMANENTLY_BARRED closes the machine."""

    def test_probation_then_reinstatement_returns_to_approved(self, api):
        """PRD §3.6: "`PROBATION` moves the provider `APPROVED → PROBATION`; the provider
        must be in `APPROVED` or the attempt is `ERR_INVALID_STATE_TRANSITION`, and the
        `version` rises by 1. `REINSTATE` closes that cycle by moving the provider
        `PROBATION → APPROVED`; the provider must be in `PROBATION`, or the attempt is
        `ERR_INVALID_STATE_TRANSITION`, and its `surveillance_score` must be below 75, or
        the attempt is `ERR_FRAUD_RISK_TOO_HIGH`. On reinstatement `sanction_reason` is set
        back to null and the `version` rises by 1."

        Design: Corner/state_machines/provider_probation_then_reinstatement_closes_the_cycle
        """
        create_tutoring_category()
        env = setup_approved_provider(flags=[], codes=["TUTORING"])
        assert env.screening["screening_score"] == 0, (
            f"an empty flag list scores 0, got {env.screening['screening_score']}"
        )
        assert env.provider["status"] == "APPROVED", (
            f"a score below 40 admits straight to APPROVED, got {env.provider['status']!r}"
        )
        approved_version = env.provider["version"]

        on_probation = sanction_provider(
            env.provider_id, "PROBATION", "Late invoice documentation."
        )
        assert on_probation["status"] == "PROBATION", (
            f"the sanction moves APPROVED to PROBATION, got {on_probation['status']!r}"
        )
        assert on_probation["sanction_reason"] == "Late invoice documentation.", (
            f"storing the supplied reason, got {on_probation['sanction_reason']!r}"
        )
        assert on_probation["version"] == approved_version + 1, (
            f"and raising the version by 1, got {on_probation['version']}"
        )

        reinstated = sanction_provider(
            env.provider_id, "REINSTATE", "Documentation received and verified."
        )
        assert reinstated["status"] == "APPROVED", (
            "REINSTATE closes the cycle back to a state already occupied, got "
            f"{reinstated['status']!r}"
        )
        assert reinstated["sanction_reason"] is None, (
            f"and sets sanction_reason back to null, got {reinstated['sanction_reason']!r}"
        )
        assert reinstated["version"] == approved_version + 2, (
            f"raising the version once more, got {reinstated['version']}"
        )
        assert reinstated["surveillance_score"] == 0, (
            "no substantiated case ever attached, so the surveillance score is still 0, "
            f"got {reinstated['surveillance_score']}"
        )
        assert reinstated["authorized_category_codes"] == ["TUTORING"], (
            "the pinned catalogue line survives the whole cycle, got "
            f"{reinstated['authorized_category_codes']!r}"
        )

    def test_permanently_barred_provider_refuses_every_later_sanction(self, api):
        """PRD §3.6: "A provider whose appeal is refused moves `DELISTED →
        PERMANENTLY_BARRED`, after which every further sanction or admission attempt
        returns `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/permanently_barred_provider_rejects_every_later_sanction
        """
        create_tutoring_category()
        env = setup_approved_provider(flags=[], codes=["TUTORING"])
        delisted = sanction_provider(
            env.provider_id, "DELIST", "Falsified attendance logs."
        )
        assert delisted["status"] == "DELISTED", (
            f"the provider is delisted first, got {delisted['status']!r}"
        )

        appeal = file_provider_delisting_appeal(env.provider_id)
        decided = decide_appeal(
            appeal["id"],
            "UPHELD",
            "Falsification confirmed by two independent site visits.",
        )
        assert decided["status"] == "UPHELD", (
            f"the appeal is refused, got {decided['status']!r}"
        )
        assert read_appeal(appeal["id"])["status"] == "UPHELD", (
            "and the refusal is what the stored appeal reports"
        )
        barred = read_provider(env.provider_id)
        assert barred["status"] == "PERMANENTLY_BARRED", (
            f"an upheld delisting bars the provider for good, got {barred['status']!r}"
        )

        reinstate = api.sanction_provider(
            env.provider_id,
            create_sanction_payload("REINSTATE", "Requesting readmission."),
            CO,
        )
        validate_error(reinstate, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        delist_again = api.sanction_provider(
            env.provider_id,
            create_sanction_payload("DELIST", "Duplicate delisting attempt."),
            CO,
        )
        validate_error(delist_again, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        readmit = api.approve_provider(
            env.provider_id, create_approve_provider_payload(["TUTORING"]), VS
        )
        validate_error(readmit, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)

        final = read_provider(env.provider_id)
        assert final["status"] == "PERMANENTLY_BARRED", (
            f"the status never changes again, got {final['status']!r}"
        )
        assert final["version"] == barred["version"], (
            "and none of the three rejected calls mutated the record, got version "
            f"{final['version']} against {barred['version']}"
        )


class TestSanctionAuthority:
    """Onboarding and enforcement are held by different roles."""

    def test_vendor_screener_cannot_delist_a_provider(self, api):
        """PRD §2.1: "When both headers are well formed but the declared role is not among
        the roles permitted for the endpoint being called, the rejection is
        `ERR_FORBIDDEN_ROLE`."

        PRD §3.6: "A `ComplianceOfficer` may afterwards apply or lift a sanction by
        supplying an `action` of `PROBATION`, `REINSTATE`, or `DELIST` together with a
        `reason`, which is stored on the provider as `sanction_reason`."

        Design: Corner/rbac/vendor_screener_cannot_sanction_a_provider
        """
        create_tutoring_category()
        env = setup_approved_provider(flags=["NO_STATE_REGISTRATION"], codes=["TUTORING"])
        assert env.screening["screening_score"] == 35, (
            f"NO_STATE_REGISTRATION weighs 35, got {env.screening['screening_score']}"
        )
        assert env.provider["status"] == "APPROVED", (
            f"a score below 40 admits to APPROVED, got {env.provider['status']!r}"
        )

        refused = api.sanction_provider(
            env.provider_id,
            create_sanction_payload("DELIST", "Screener attempts an enforcement action."),
            VS,
        )
        validate_error(refused, ApiErrorId.FORBIDDEN_ROLE.value, 403)

        untouched = read_provider(env.provider_id)
        assert untouched["status"] == "APPROVED", (
            f"the screener's attempt changed nothing, got {untouched['status']!r}"
        )
        assert untouched["sanction_reason"] is None, (
            f"and recorded no reason, got {untouched['sanction_reason']!r}"
        )

        allowed = validate_success(
            api.sanction_provider(
                env.provider_id,
                create_sanction_payload("DELIST", "Falsified attendance logs."),
                CO,
            )
        )
        assert allowed["status"] == "DELISTED", (
            "the same call by a compliance officer succeeds, got "
            f"{allowed['status']!r}"
        )
        assert allowed["sanction_reason"] == "Falsified attendance logs.", (
            f"and stores the reason, got {allowed['sanction_reason']!r}"
        )


class TestProbationGatesTheReimbursementFlow:
    """A third entity's state decides the filing, and it decides it per flow."""

    def _probation_provider_environment(self):
        """A funded account, a reimbursement-friendly category, a probationary vendor."""
        env = setup_funded_account(quarters=1)
        env["materials"] = create_materials_category()
        env.update(
            setup_approved_provider(
                payload_builder=create_out_of_state_provider_payload,
                flags=PROBATION_BAND_FLAGS,
                codes=["MATERIALS"],
            )
        )
        return env

    def test_reimbursement_naming_a_probationary_provider_is_refused(self, api):
        """PRD §3.6: "With a `screening_score` of at least 40 and below 60 the provider
        moves `SCREENED → PROBATION` instead. The supplied `authorized_category_codes` are
        pinned in exactly the same way, `sanction_reason` is set to the literal string
        `ELEVATED_SCREENING_SCORE`, and its `version` rises by 1. A provider on probation
        may only be used with the pre-approval flow; a reimbursement purchase naming it is
        refused with `ERR_PROVIDER_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/reimbursement_flow_requires_provider_not_on_probation
        """
        env = self._probation_provider_environment()
        assert env.screening["screening_score"] == 20 + 25, (
            "ADDRESS_MISMATCH 20 plus SHARED_BANK_ACCOUNT 25 scores 45, got "
            f"{env.screening['screening_score']}"
        )
        assert env.screening["recommended_status"] == "PROBATION", (
            "a score of at least 40 and below 60 recommends PROBATION, got "
            f"{env.screening['recommended_status']!r}"
        )
        assert env.provider["status"] == "PROBATION", (
            f"so admission landed the provider in PROBATION, got {env.provider['status']!r}"
        )
        assert env.provider["sanction_reason"] == ELEVATED_SCREENING_SCORE, (
            "with the literal sanction reason ELEVATED_SCREENING_SCORE, got "
            f"{env.provider['sanction_reason']!r}"
        )
        assert env.provider["authorized_category_codes"] == ["MATERIALS"], (
            "the codes are pinned in exactly the same way as on the approved branch, got "
            f"{env.provider['authorized_category_codes']!r}"
        )

        account_before = read_account(env.account_id)
        assert account_before["status"] == "ACTIVE", (
            f"the account itself is impeccable, got {account_before['status']!r}"
        )
        assert account_before["balance_cents"] == Q1_NET_CENTS, (
            f"with ample balance, got {account_before['balance_cents']}"
        )

        refused = api.create_purchase_request(
            env.account_id,
            create_purchase_request_payload(
                env.provider_id,
                env.materials["id"],
                account_before["version"],
                flow="REIMBURSEMENT",
                amount_cents=60000,
                invoice_reference="MAT-77",
            ),
            env.guardian,
        )
        validate_error(refused, ApiErrorId.PROVIDER_NOT_ELIGIBLE.value, 422)

        account_after = read_account(env.account_id)
        assert account_after["version"] == account_before["version"], (
            "the refused filing never consumed the account's version guard, got "
            f"{account_after['version']} against {account_before['version']}"
        )
        assert account_after["balance_cents"] == Q1_NET_CENTS, (
            f"and moved no money, got {account_after['balance_cents']}"
        )
        _, meta = validate_paginated(
            api.list_purchase_requests(PA, params={"provider_id": env.provider_id})
        )
        assert meta["total_count"] == 0, (
            f"no purchase request exists against the vendor, got {meta['total_count']}"
        )

    def test_the_identical_amount_under_preapproval_is_accepted(self, api):
        """PRD §3.7: "The named provider must be participation-eligible for the requested
        `flow`: `APPROVED` when the flow is `REIMBURSEMENT`, and either `APPROVED` or
        `PROBATION` when the flow is `PREAPPROVAL`; a provider in `DRAFT`, `SCREENED`,
        `DELISTED`, or `PERMANENTLY_BARRED`, or one on probation with a reimbursement flow,
        is refused with `ERR_PROVIDER_NOT_ELIGIBLE`."

        PRD §3.7: "A successful filing lands at `PENDING_REVIEW` and `UNSETTLED`, and —
        because it consumes the account's version guard — the account's own `version` rises
        by 1 even though no money has moved."

        Design: Difficulty/cross_entity_state_dependency/reimbursement_flow_requires_provider_not_on_probation
        """
        env = self._probation_provider_environment()
        assert env.provider["status"] == "PROBATION", (
            f"the very same probationary vendor is named, got {env.provider['status']!r}"
        )
        version_before = account_version(env.account_id)

        request = validate_success(
            api.create_purchase_request(
                env.account_id,
                create_purchase_request_payload(
                    env.provider_id,
                    env.materials["id"],
                    version_before,
                    flow="PREAPPROVAL",
                    amount_cents=60000,
                ),
                env.guardian,
            ),
            201,
        )
        assert request["flow"] == "PREAPPROVAL", (
            f"the accepted request runs the pre-approval flow, got {request['flow']!r}"
        )
        assert request["amount_cents"] == 60000, (
            "for the identical amount the reimbursement attempt was refused, got "
            f"{request['amount_cents']}"
        )
        assert request["approval_status"] == "PENDING_REVIEW", (
            f"landing at PENDING_REVIEW, got {request['approval_status']!r}"
        )
        assert request["settlement_status"] == "UNSETTLED", (
            f"and UNSETTLED, got {request['settlement_status']!r}"
        )
        assert request["invoice_reference"] is None, (
            "an omitted invoice_reference is null until a claim supplies it, got "
            f"{request['invoice_reference']!r}"
        )
        assert request["provider_id"] == env.provider_id, (
            f"the request names the probationary vendor, got {request['provider_id']!r}"
        )

        account = read_account(env.account_id)
        assert account["version"] == version_before + 1, (
            "the successful filing consumed the version guard, got "
            f"{account['version']} against {version_before}"
        )
        assert account["balance_cents"] == Q1_NET_CENTS, (
            f"yet no money has moved, got {account['balance_cents']}"
        )
        assert account["encumbered_cents"] == 0, (
            f"creation alone encumbers nothing, got {account['encumbered_cents']}"
        )

        stored = read_purchase_request(request["id"])
        assert stored["id"] == request["id"], (
            f"the request is readable afterwards, got {stored!r}"
        )
        rows, meta = validate_paginated(
            api.list_purchase_requests(PA, params={"provider_id": env.provider_id})
        )
        assert meta["total_count"] == 1, (
            f"exactly one request stands against the vendor, got {meta['total_count']}"
        )
        assert rows[0]["id"] == request["id"], (
            f"and it is the pre-approval one, got {rows[0]!r}"
        )
