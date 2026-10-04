"""Model lifecycle, governance gates, model editing, and validation errors."""
from test_helpers import (
    ApiErrorId,
    assert_model_version,
    create_fairness_review_payload,
    create_model_version_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestModelVersionCreation:

    def test_model_version_create_returns_201_with_draft_status_and_version_1(
        self, api, risk_officer_creator_headers
    ):
        """PRD 3.1: "A new model starts in `DRAFT`"
        PRD 2.4: "The `version` field is an integer starting at 1 that increments by exactly one on every mutation of the resource"
        PRD 3.1: "stamps the computed report onto the model's `fairness_report`, which is null until the model reaches `VALIDATED`."
        PRD 4: "Operations that create a new resource return `201 Created`"

        Design: Corner/entities/model_version_create_returns_201_with_draft_status_and_version_1
        """
        payload = create_model_version_payload(model_code="ADU-E-1", calibration_note="entity create")
        resp = api.create_model_version(payload, risk_officer_creator_headers)
        model = validate_success(resp, expected_status=201)
        assert_model_version(model)
        assert model["status"] == "DRAFT"
        assert model["version"] == 1
        assert model["fairness_report"] is None
        assert resp.json()["response_type"] == "object"
        meta = resp.json()["meta"]
        assert meta.get("api_request_id"), "meta.api_request_id must be present"
        assert meta.get("api_request_timestamp"), "meta.api_request_timestamp must be present"


class TestModelStateVersusGovernancePriority:

    def test_activate_draft_model_with_no_reviews_reports_invalid_state(
        self, api, risk_officer_creator_headers
    ):
        """PRD 3.1: "A model whose status is not `VALIDATED` cannot be activated (`ERR_MODEL_INVALID_STATE`)."
        PRD 2.9: "then state-transition legality (the entity-specific invalid-state errors, all HTTP 409), then segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`), then the model governance gates (`ERR_FAIRNESS_GATE_BLOCKING` and `ERR_EXCLUSION_REVIEW_OPEN`)"

        Design: Difficulty/priority_pair_validation_conflict/model_state_error_beats_fairness_gate_error
        """
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-P-1"), risk_officer_creator_headers
        )
        model = validate_success(resp, expected_status=201)

        resp = api.activate_model_version(model["id"], risk_officer_creator_headers)
        err = validate_error(resp, ApiErrorId.ERR_MODEL_INVALID_STATE)
        assert err["error_id"] != ApiErrorId.ERR_FAIRNESS_GATE_BLOCKING.value
        model = get_success_data(api.get_model_version(model["id"], risk_officer_creator_headers))
        assert model["status"] == "DRAFT"

    def test_activate_draft_model_leaves_it_draft_and_blocks_every_retry(
        self, api, risk_officer_creator_headers
    ):
        """PRD 3.1: "A model whose status is not `VALIDATED` cannot be activated (`ERR_MODEL_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/model_state_error_beats_fairness_gate_error
        """
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-P-1B"), risk_officer_creator_headers
        )
        model = validate_success(resp, expected_status=201)

        for _ in range(2):
            resp = api.activate_model_version(model["id"], risk_officer_creator_headers)
            validate_error(resp, ApiErrorId.ERR_MODEL_INVALID_STATE)
        model = get_success_data(api.get_model_version(model["id"], risk_officer_creator_headers))
        assert model["status"] == "DRAFT"


class TestModelLocking:

    def test_patch_of_validated_model_is_model_locked_not_invalid_state(
        self, api, risk_officer_creator_headers, risk_officer_validator_headers
    ):
        """PRD 3.1: "an edit attempt against a model no longer in `DRAFT` is rejected with `ERR_MODEL_LOCKED` (HTTP 409)"

        Design: Corner/errors/model_locked_error_on_patch_of_validated_model
        """
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-R-1", calibration_note="lock"),
            risk_officer_creator_headers,
        )
        model = validate_success(resp, expected_status=201)
        resp = api.validate_model_version(model["id"], risk_officer_validator_headers)
        model = validate_success(resp, expected_status=200)
        assert model["status"] == "VALIDATED"

        resp = api.patch_model_version(
            model["id"],
            {
                "variables": [{"name": "bureau_score", "weight": 2, "min": 300, "max": 850}],
                "score_floor": 0,
                "score_ceiling": 1000,
                "expected_model_version": model["version"],
            },
            risk_officer_creator_headers,
        )
        err = validate_error(resp, ApiErrorId.ERR_MODEL_LOCKED)
        assert err["error_id"] != ApiErrorId.ERR_MODEL_INVALID_STATE.value

        model = get_success_data(api.get_model_version(model["id"], risk_officer_creator_headers))
        assert model["variables"][0]["weight"] == 6, "the locked edit must not change variables"

    def test_model_versions_list_filters_by_status(self, api, risk_officer_creator_headers,
                                                   risk_officer_validator_headers, auditor_headers):
        """PRD 2.3: "List endpoints also accept resource-specific equality filters - such as `status`"

        Design: Corner/endpoints/model_versions_list_filters_by_status
        """
        # Model A: full governance chain to ACTIVE.
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-N-3A"), risk_officer_creator_headers
        )
        model_a = validate_success(resp, expected_status=201)
        validate_success(api.validate_model_version(model_a["id"], risk_officer_validator_headers))
        resp = api.create_fairness_review(
            create_fairness_review_payload(model_a["id"]), risk_officer_creator_headers
        )
        review = validate_success(resp, expected_status=201)
        validate_success(
            api.decide_fairness_review(review["id"], {"outcome": "PASSED"}, risk_officer_creator_headers)
        )
        validate_success(api.activate_model_version(model_a["id"], risk_officer_creator_headers))

        # Model B: left DRAFT.
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-N-3B"), risk_officer_creator_headers
        )
        model_b = validate_success(resp, expected_status=201)

        data, meta = validate_paginated(
            api.list_model_versions(auditor_headers, params={"status": "DRAFT"})
        )
        assert [m["id"] for m in data] == [model_b["id"]]
        assert meta["total_count"] == 1

        data, meta = validate_paginated(
            api.list_model_versions(auditor_headers, params={"status": "ACTIVE"})
        )
        assert [m["id"] for m in data] == [model_a["id"]]
        assert meta["total_count"] == 1

        data, meta = validate_paginated(api.list_model_versions(auditor_headers))
        assert meta["total_count"] == 2


class TestModelOcc:

    def test_stale_model_version_on_patch_returns_412(self, api, risk_officer_creator_headers):
        """PRD 2.8: "Editing a draft model requires `expected_model_version` matching the model's current `version`."
        PRD 2.8: "In all three cases a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD 3.1: "Each successful edit increments the model's `version` by one."

        Design: Corner/cross_cutting_layers/stale_model_version_on_patch_returns_412
        """
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-X-1", calibration_note="occ"),
            risk_officer_creator_headers,
        )
        model = validate_success(resp, expected_status=201)
        stale_version = model["version"]

        # First edit succeeds and bumps the version.
        resp = api.patch_model_version(
            model["id"],
            {
                "variables": [{"name": "bureau_score", "weight": 2, "min": 300, "max": 850}],
                "score_floor": 0,
                "score_ceiling": 1000,
                "expected_model_version": stale_version,
            },
            risk_officer_creator_headers,
        )
        model = validate_success(resp, expected_status=200)
        assert model["version"] == stale_version + 1
        assert model["variables"][0]["weight"] == 2

        # Second edit carrying the pre-edit version is stale.
        resp = api.patch_model_version(
            model["id"],
            {
                "variables": [{"name": "bureau_score", "weight": 3, "min": 300, "max": 850}],
                "score_floor": 0,
                "score_ceiling": 1000,
                "expected_model_version": stale_version,
            },
            risk_officer_creator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        model = get_success_data(api.get_model_version(model["id"], risk_officer_creator_headers))
        assert model["variables"][0]["weight"] == 2, "the stale write must be rejected wholesale"


class TestGovernanceGates:

    def test_activation_blocked_by_open_variable_exclusion_review(
        self, api, risk_officer_creator_headers, risk_officer_validator_headers
    ):
        """PRD 3.1: "Additionally, no `VARIABLE_EXCLUSION` review on this model may still be `PENDING`, or activation fails with `ERR_EXCLUSION_REVIEW_OPEN`."

        Design: Corner/errors/model_activate_blocked_by_open_exclusion_review
        """
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-R-2", calibration_note="excl"),
            risk_officer_creator_headers,
        )
        model = validate_success(resp, expected_status=201)
        validate_success(api.validate_model_version(model["id"], risk_officer_validator_headers))

        # PASSED disparate-impact review satisfies the fairness gate.
        resp = api.create_fairness_review(
            create_fairness_review_payload(model["id"], details="di"), risk_officer_creator_headers
        )
        review_di = validate_success(resp, expected_status=201)
        validate_success(
            api.decide_fairness_review(review_di["id"], {"outcome": "PASSED"}, risk_officer_creator_headers)
        )

        # A VARIABLE_EXCLUSION review is opened and left PENDING.
        resp = api.create_fairness_review(
            create_fairness_review_payload(
                model["id"], review_type="VARIABLE_EXCLUSION", details="vex pending"
            ),
            risk_officer_creator_headers,
        )
        validate_success(resp, expected_status=201)

        resp = api.activate_model_version(model["id"], risk_officer_creator_headers)
        err = validate_error(resp, ApiErrorId.ERR_EXCLUSION_REVIEW_OPEN)
        assert err["error_id"] != ApiErrorId.ERR_FAIRNESS_GATE_BLOCKING.value
        model = get_success_data(api.get_model_version(model["id"], risk_officer_creator_headers))
        assert model["status"] == "VALIDATED"

    def test_activation_blocked_by_failed_disparate_impact_review(
        self, api, risk_officer_creator_headers, risk_officer_validator_headers
    ):
        """PRD 3.1: "No fairness review on this model may have outcome `FAILED`, and at least one `DISPARATE_IMPACT` review must exist with outcome `PASSED`; otherwise activation fails with `ERR_FAIRNESS_GATE_BLOCKING`."

        Design: Corner/errors/fairness_gate_blocking_when_review_failed
        """
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-R-4", calibration_note="gate"),
            risk_officer_creator_headers,
        )
        model = validate_success(resp, expected_status=201)
        validate_success(api.validate_model_version(model["id"], risk_officer_validator_headers))

        resp = api.create_fairness_review(
            create_fairness_review_payload(model["id"], details="failed di"), risk_officer_creator_headers
        )
        review = validate_success(resp, expected_status=201)
        validate_success(
            api.decide_fairness_review(review["id"], {"outcome": "FAILED"}, risk_officer_creator_headers)
        )

        resp = api.activate_model_version(model["id"], risk_officer_creator_headers)
        validate_error(resp, ApiErrorId.ERR_FAIRNESS_GATE_BLOCKING)
        model = get_success_data(api.get_model_version(model["id"], risk_officer_creator_headers))
        assert model["status"] == "VALIDATED"


class TestModelRetirement:

    def test_retire_blocked_while_applications_open_then_succeeds_after_withdrawal(
        self, api, risk_officer_creator_headers, risk_officer_validator_headers,
        platform_admin_headers,
    ):
        """PRD 3.1: "An `ACTIVE` model may be retired only when every application that snapshotted it has reached a terminal state - `APPROVED`, `DECLINED`, or `WITHDRAWN` - and the attempt fails with `ERR_MODEL_HAS_OPEN_APPLICATIONS` while any such application remains open"

        Design: Corner/errors/model_retire_blocked_with_open_applications
        """
        from test_helpers import (
            create_active_model,
            create_applicant,
            submit_application,
        )

        model = create_active_model(model_code="ADU-R-3")
        applicant = create_applicant(full_name="Retire Ruth")
        app = submit_application(applicant["id"])
        assert app["status"] == "VERIFICATION_PENDING"

        resp = api.retire_model_version(model["id"], risk_officer_creator_headers)
        validate_error(resp, ApiErrorId.ERR_MODEL_HAS_OPEN_APPLICATIONS)

        resp = api.withdraw_application(app["id"], platform_admin_headers)
        validate_success(resp, expected_status=200)

        resp = api.retire_model_version(model["id"], risk_officer_creator_headers)
        model = validate_success(resp, expected_status=200)
        assert model["status"] == "RETIRED"


class TestFairnessReviewEndpoints:

    def test_fairness_review_create_and_decide_round_trip(
        self, api, risk_officer_creator_headers, auditor_headers
    ):
        """PRD 3.2: "A new review starts with outcome `PENDING`."
        PRD 3.2: "Deciding the review sets its `outcome` to `PASSED` or `FAILED`"
        PRD 4: "Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`."

        Design: Corner/endpoints/fairness_review_create_and_decide_round_trip
        """
        resp = api.create_model_version(
            create_model_version_payload(model_code="ADU-N-1", calibration_note="fr"),
            risk_officer_creator_headers,
        )
        model = validate_success(resp, expected_status=201)

        resp = api.create_fairness_review(
            create_fairness_review_payload(
                model["id"], review_type="VARIABLE_EXCLUSION", details="exclude zip-derived variable"
            ),
            risk_officer_creator_headers,
        )
        review = validate_success(resp, expected_status=201)
        assert review["outcome"] == "PENDING"

        resp = api.decide_fairness_review(
            review["id"], {"outcome": "FAILED"}, risk_officer_creator_headers
        )
        review = validate_success(resp, expected_status=200)
        assert review["outcome"] == "FAILED"
        assert review["details"] == "exclude zip-derived variable"

        data, meta = validate_paginated(
            api.list_fairness_reviews(
                auditor_headers,
                params={"model_version_id": model["id"], "review_type": "VARIABLE_EXCLUSION"},
            )
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == review["id"]
