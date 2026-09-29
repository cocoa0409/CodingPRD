"""
Error corners: the per-entity 404 vocabulary, the empty-candidate-set arm of SKU
selection, the subscription state gate across four endpoints, the two transfer
guards, the per-method evidence quorum, and the identity-header gate that
outranks the existence lookup.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CASE_NOT_FOUND,
    ERR_CLAIM_NOT_FOUND,
    ERR_ENTITLEMENT_NOT_FOUND,
    ERR_NO_ELIGIBLE_SKU,
    ERR_NO_EVIDENCE_FOR_METHOD,
    ERR_RESIDENT_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_SKU_NOT_FOUND,
    ERR_SUBSCRIPTION_STATE_INVALID,
    ERR_TRANSFER_DATE_INVALID,
    ERR_TRANSFER_NOT_FOUND,
    ERR_TRANSFER_STATE_INVALID,
    ERR_UNAUTHENTICATED,
)
from test_helpers.test_users import (
    OPERATOR,
    headers_with_empty_role,
    headers_with_empty_user_id,
    headers_without_role,
    headers_without_user_id,
)


class TestNotFoundVocabulary:
    """One unknown id, seven different error identifiers."""

    def test_each_entity_type_answers_an_unknown_id_with_its_own_code(self, api):
        """
        The same syntactically valid but unknown UUID produces a different
        error_id on each of seven reads, all of them HTTP 404, so a single generic
        not-found collapse is detectable.

        PRD §2.5: "Each missing referent has its own error: `ERR_PROPERTY_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_SKU_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND` and `ERR_ENTITLEMENT_NOT_FOUND`, all HTTP 404."

        Design: Corner/errors/each_unknown_path_id_returns_its_own_not_found_code
        """
        probes = [
            (api.get_filter_sku(NON_EXISTENT_UUID, OPERATOR), ERR_SKU_NOT_FOUND),
            (api.get_resident(NON_EXISTENT_UUID, OPERATOR), ERR_RESIDENT_NOT_FOUND),
            (api.get_shipment(NON_EXISTENT_UUID, OPERATOR), ERR_SHIPMENT_NOT_FOUND),
            (api.get_non_install_case(NON_EXISTENT_UUID, OPERATOR), ERR_CASE_NOT_FOUND),
            (api.get_claim(NON_EXISTENT_UUID, OPERATOR), ERR_CLAIM_NOT_FOUND),
            (
                api.get_subscription_transfer(NON_EXISTENT_UUID, OPERATOR),
                ERR_TRANSFER_NOT_FOUND,
            ),
            (
                api.get_benefit_entitlement(NON_EXISTENT_UUID, OPERATOR),
                ERR_ENTITLEMENT_NOT_FOUND,
            ),
        ]

        seen = []
        for response, expected_error in probes:
            error = validate_error(response, expected_error, 404)
            seen.append(error["error_id"])

        assert len(set(seen)) == 7, f"the seven codes must be pairwise distinct: {seen}"


class TestSkuSelectionHasNoCandidate:
    """A non-empty catalog that serves no rack of this size."""

    def test_a_catalog_that_cannot_serve_the_unit_size_blocks_enrolment(self, api):
        """
        A catalog holding only 16x25x1 filters cannot enrol a 20x25x1 rack — the
        empty-candidate-set arm is reached by a size mismatch, nothing is created,
        the unit stays AVAILABLE — and the identical payload succeeds the moment a
        matching SKU is registered.

        PRD §3.3: "When the candidate set comes out empty the request is rejected with `ERR_NO_ELIGIBLE_SKU` and nothing is created."

        Design: Corner/errors/no_eligible_sku_when_the_catalog_cannot_serve_the_unit_size
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.create_sku(api)
        prop = fx.create_property(api)
        unit = fx.create_unit(api, prop["id"], unit_label="A-101", nominal_size_code="20x25x1")
        fx.activate_property(api, prop["id"])
        resident = fx.create_resident(api)
        fx.set_clock(api, "2026-08-05T00:00:00Z")

        payload = f.subscription_payload(resident["id"], unit["id"])
        validate_error(
            api.create_subscription(payload, OPERATOR), ERR_NO_ELIGIBLE_SKU, 422
        )
        _rows, meta = validate_paginated(api.list_subscriptions(OPERATOR))
        assert meta["total_count"] == 0
        assert validate_success(api.get_unit(unit["id"], OPERATOR))["status"] == "AVAILABLE"

        matching_sku = fx.create_sku(
            api,
            sku_code="SKU-20251-M8",
            size_code="20x25x1",
            thickness_inches=1,
            merv_rating=8,
            unit_cost_cents=810,
            ship_weight_oz=17,
            pack_quantity=1,
        )
        created = validate_success(api.create_subscription(payload, OPERATOR), 201)
        assert created["assigned_sku_id"] == matching_sku["id"]


class TestSubscriptionStateGate:
    """One error identifier guarding four different writes."""

    def test_four_writes_are_refused_on_the_wrong_side_of_the_status_gate(self, api):
        """
        From PENDING_SETUP a manual shipment, a renewal survey and a
        non-installation evaluation are all refused with the same 409 — the
        evaluation before its own evidence check is ever reached — the version
        never moves, and after activation the replayed activate is refused by the
        very same rule without minting a second shipment.

        PRD §2.10: "The subscription's `status` permits the requested transition — otherwise `ERR_SUBSCRIPTION_STATE_INVALID` (409). Applies to seven operations: activating a subscription, cancelling a subscription, scheduling a shipment, recording a renewal survey, running a non-installation evaluation, opening a transfer, and filing a claim."

        Design: Corner/errors/subscription_state_gate_rejects_writes_on_a_pending_setup_subscription
        """
        env = fx.build_base_env(api, activate=False)

        validate_error(
            api.create_shipment(
                env.subscription_id, f.shipment_payload("2026-08-06"), OPERATOR
            ),
            ERR_SUBSCRIPTION_STATE_INVALID,
            409,
        )
        _shipments, shipment_meta = validate_paginated(
            api.list_shipments(OPERATOR, {"subscription_id": env.subscription_id})
        )
        assert shipment_meta["total_count"] == 0

        validate_error(
            api.create_renewal_survey(
                env.subscription_id, f.renewal_survey_payload(False, 0), OPERATOR
            ),
            ERR_SUBSCRIPTION_STATE_INVALID,
            409,
        )
        validate_error(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RENEWAL_SURVEY", "2026-08-05"),
                OPERATOR,
            ),
            ERR_SUBSCRIPTION_STATE_INVALID,
            409,
        )
        assert fx.read_subscription(api, env.subscription_id)["version"] == 1

        activated = validate_success(api.activate_subscription(env.subscription_id, OPERATOR))
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2

        validate_error(
            api.activate_subscription(env.subscription_id, OPERATOR),
            ERR_SUBSCRIPTION_STATE_INVALID,
            409,
        )
        assert fx.read_subscription(api, env.subscription_id)["version"] == 2
        _again, replay_meta = validate_paginated(
            api.list_shipments(OPERATOR, {"subscription_id": env.subscription_id})
        )
        assert replay_meta["total_count"] == 1


class TestTransferGuards:
    """The pipeline cannot be short-circuited, and the pivot date is bounded."""

    def _transfer_env(self, api, effective_date: str):
        env = fx.build_base_env(api)
        destination = fx.create_unit(api, env.property_id, unit_label="A-201")
        transfer = validate_success(
            api.create_subscription_transfer(
                f.transfer_payload(env.subscription_id, destination["id"], effective_date, 2),
                OPERATOR,
            ),
            201,
        )
        return env, destination, transfer

    def test_completion_before_the_remap_step_is_refused_and_mints_nothing(self, api):
        """
        Completion is only a transition out of SKU_REMAPPED, so calling it from
        REQUESTED must 409 while leaving the proration figures at their creation
        zeros, minting no successor subscription, posting no adjustment row and
        moving no money — and the same call succeeds once the remap has run.

        PRD §3.8: "Any transfer action attempted from a state the transfer machine does not permit — including all three terminal states `COMPLETED`, `REJECTED` and `SUPERSEDED` — is rejected with `ERR_TRANSFER_STATE_INVALID`."

        Design: Corner/errors/transfer_completed_before_the_sku_remap_step_rejected
        """
        env, _destination, transfer = self._transfer_env(api, "2026-08-25")
        assert transfer["status"] == "REQUESTED"

        validate_error(
            api.complete_transfer(transfer["id"], OPERATOR), ERR_TRANSFER_STATE_INVALID, 409
        )

        refused = validate_success(api.get_subscription_transfer(transfer["id"], OPERATOR))
        assert refused["status"] == "REQUESTED"
        a.assert_cents(refused["net_adjustment_cents"], 0, "net_adjustment_cents")
        assert refused["successor_subscription_id"] is None
        _subscriptions, subscription_meta = validate_paginated(api.list_subscriptions(OPERATOR))
        assert subscription_meta["total_count"] == 1
        assert a.property_balance(api, env.property_id, OPERATOR) == 5588
        assert (
            a.find_ledger_rows(fx.read_ledger(api, env.subscription_id), "TRANSFER_ADJUSTMENT")
            == []
        )

        remapped = validate_success(api.remap_transfer_sku(transfer["id"], OPERATOR))
        assert remapped["status"] == "SKU_REMAPPED"
        completed = validate_success(api.complete_transfer(transfer["id"], OPERATOR))
        assert completed["status"] == "COMPLETED"

    def test_the_pivot_date_is_bounded_below_by_the_clock_and_above_by_the_lease(self, api):
        """
        A pivot one day behind the clock and a pivot one day past the outgoing
        lease end are refused with the same error identifier, no transfer record
        survives either attempt, the subscription is untouched — and a pivot equal
        to the clock date is accepted, so the lower bound is inclusive.

        PRD §3.8: "The pivot date must be usable: an `effective_date` earlier than the logical-clock date, or falling outside the closed interval from the subscription's `lease_start_date` to its `lease_end_date`, is rejected with `ERR_TRANSFER_DATE_INVALID`."

        Design: Corner/errors/transfer_effective_date_before_the_clock_rejected
        """
        env = fx.build_base_env(api)
        destination = fx.create_unit(api, env.property_id, unit_label="A-201")
        fx.set_clock(api, "2026-09-11T00:00:00Z")

        for pivot in ("2026-09-10", "2027-08-01"):
            validate_error(
                api.create_subscription_transfer(
                    f.transfer_payload(env.subscription_id, destination["id"], pivot, 2),
                    OPERATOR,
                ),
                ERR_TRANSFER_DATE_INVALID,
                422,
            )

        _rows, meta = validate_paginated(api.list_subscription_transfers(OPERATOR))
        assert meta["total_count"] == 0
        untouched = fx.read_subscription(api, env.subscription_id)
        assert untouched["status"] == "ACTIVE"
        assert untouched["version"] == 2

        accepted = validate_success(
            api.create_subscription_transfer(
                f.transfer_payload(env.subscription_id, destination["id"], "2026-09-11", 2),
                OPERATOR,
            ),
            201,
        )
        assert accepted["status"] == "REQUESTED"
        assert accepted["effective_date"] == "2026-09-11"


class TestEvidenceQuorum:
    """The quorum is counted per detection method, not globally."""

    def test_one_telemetry_window_is_not_a_quorum_but_one_survey_is(self, api):
        """
        A single reading inside the runtime window is one short of the analytics
        quorum, so that evaluation is refused and opens no case, while the survey
        method on the very same subscription clears its quorum of one and opens a
        case carrying the survey method's own frozen thresholds.

        PRD §2.10: "The requested detection method has evidence: at least two telemetry readings inside the evaluation window for runtime analytics, at least one survey for the renewal survey method — otherwise `ERR_NO_EVIDENCE_FOR_METHOD` (422). Applies to the non-installation evaluation only."

        Design: Corner/errors/runtime_evaluation_with_a_single_reading_returns_no_evidence
        """
        env = fx.build_base_env(api)
        fx.deliver_first_shipment(api, env.subscription_id, "2026-08-08T00:00:00Z")
        fx.add_runtime_reading(
            api, env.unit_id, "2026-08-09T00:00:00Z", "2026-08-10T00:00:00Z",
            240, 100, "PRESSURE_SENSOR",
        )
        fx.set_clock(api, "2026-08-20T00:00:00Z")
        fx.submit_renewal_survey(
            api, env.subscription_id, installed_last_shipment=False, filters_on_hand_count=0
        )

        validate_error(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RUNTIME_ANALYTICS", "2026-08-20"),
                OPERATOR,
            ),
            ERR_NO_EVIDENCE_FOR_METHOD,
            422,
        )
        _cases, case_meta = validate_paginated(
            api.list_subscription_cases(env.subscription_id, OPERATOR)
        )
        assert case_meta["total_count"] == 0
        assert fx.read_subscription(api, env.subscription_id)["installation_posture"] == (
            "UNVERIFIED"
        )

        survey_case = validate_success(
            api.create_non_install_evaluation(
                env.subscription_id,
                f.non_install_evaluation_payload("RENEWAL_SURVEY", "2026-08-20"),
                OPERATOR,
            ),
            201,
        )
        assert survey_case["detection_method"] == "RENEWAL_SURVEY"
        assert survey_case["suspect_threshold"] == 55
        assert survey_case["confirm_threshold"] == 80

        _after, after_meta = validate_paginated(
            api.list_subscription_cases(env.subscription_id, OPERATOR)
        )
        assert after_meta["total_count"] == 1


class TestIdentityHeaderGate:
    """Priority 1 fires before the existence lookup of priority 3."""

    def test_a_missing_or_empty_identity_header_is_a_401_even_on_an_unknown_path(self, api):
        """
        Omitting either identity header, or sending either of them empty, is a 401
        on a read that would otherwise have succeeded; the same omission on a
        well-formed but unknown property id is still a 401 rather than a 404; and
        nothing about the property changed.

        PRD §2.1: "If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/request_missing_x_user_id_header_rejected
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        prop = fx.create_property(api)

        for headers in (
            headers_without_user_id(),
            headers_without_role(),
            headers_with_empty_user_id(),
            headers_with_empty_role(),
        ):
            validate_error(api.get_property(prop["id"], headers), ERR_UNAUTHENTICATED, 401)

        validate_error(
            api.get_property(NON_EXISTENT_UUID, headers_without_user_id()),
            ERR_UNAUTHENTICATED,
            401,
        )
        validate_error(
            api.get_property(NON_EXISTENT_UUID, headers_without_role()),
            ERR_UNAUTHENTICATED,
            401,
        )

        after = fx.read_property(api, prop["id"])
        assert after["version"] == 1
        assert after["status"] == "ONBOARDING"
