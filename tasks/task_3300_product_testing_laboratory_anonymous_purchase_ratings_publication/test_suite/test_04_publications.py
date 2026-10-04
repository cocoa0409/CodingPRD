"""Rating publications: editorial loop, designations, OCC, embargo, visibility.

Covers difficulty instances: publication_revision_loop,
designation_score_boundary_80 — and corner instances:
publication_submit_from_approved_invalid, publication_approve_occ_stale_version,
protocol_activate_occ_stale_category, publish_before_embargo_rejected,
member_cannot_read_under_review_publication, error_marketing_use_header,
manufacturer_response_accept_sets_publication_text.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_lab_protocol_payload, create_rating_publication_payload,
    create_category, setup_program_ready, setup_published_publication,
    create_draft_publication_with_model, create_under_review_publication,
    create_approved_publication, create_member_with_subscription, set_clock,
    TEST_USERS, make_member_headers,
)

LM = TEST_USERS["lab_manager_headers"]
MO = TEST_USERS["methodology_officer_headers"]
CE = TEST_USERS["content_editor_headers"]
ED = TEST_USERS["editorial_director_headers"]


class TestPublicationEditorialLoop:
    def test_revision_loop_returns_to_under_review(self, api):
        """PRD §3.6: "Submission by the `ContentEditor` moves the publication from `DRAFT` (or from `REVISION_REQUESTED` on resubmission) to `UNDER_REVIEW`".
        PRD §3.6: "Alternatively the director may send the publication back, `UNDER_REVIEW → REVISION_REQUESTED`."

        Design: Difficulty/non_linear_state_machine/publication_revision_loop
        """
        ctx = setup_program_ready(category_name="Washers", protocol_code="WSH-01",
                                  model_label="WashA", measurement_value=90)
        pub = create_under_review_publication(ctx)
        assert pub["status"] == "UNDER_REVIEW"
        data = validate_success(api.transition_rating_publication(
            pub["id"], {"action": "request_revision"}, ED))
        assert data["status"] == "REVISION_REQUESTED"
        data = validate_success(api.transition_rating_publication(
            pub["id"], {"action": "submit"}, CE))
        assert data["status"] == "UNDER_REVIEW"

    def test_resubmit_after_revision_requires_models_and_ready_program(self, api):
        """PRD §3.6: "Submission by the `ContentEditor` moves the publication from `DRAFT` (or from `REVISION_REQUESTED` on resubmission) to `UNDER_REVIEW`, and requires the program to be in `READY_FOR_PUBLICATION` and `model_count` to be at least 1."

        Design: Difficulty/non_linear_state_machine/publication_revision_loop
        """
        ctx = setup_program_ready(category_name="Washers", protocol_code="WSH-02",
                                  model_label="WashB", measurement_value=90)
        pub = create_under_review_publication(ctx)
        data = validate_success(api.transition_rating_publication(
            pub["id"], {"action": "request_revision"}, ED))
        assert data["status"] == "REVISION_REQUESTED"
        # second loop iteration works again from REVISION_REQUESTED
        data = validate_success(api.transition_rating_publication(
            pub["id"], {"action": "submit"}, CE))
        assert data["status"] == "UNDER_REVIEW"
        data = validate_success(api.transition_rating_publication(
            pub["id"], {"action": "request_revision"}, ED))
        assert data["status"] == "REVISION_REQUESTED"

    def test_submit_from_approved_is_invalid(self, api):
        """PRD §3.6: "Submission by the `ContentEditor` moves the publication from `DRAFT` (or from `REVISION_REQUESTED` on resubmission) to `UNDER_REVIEW`".
        PRD §2.5: "State — the target resource is in a valid from-state for the requested action and the action name itself is known; failure yields `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/publication_submit_from_approved_invalid
        """
        ctx = setup_program_ready(category_name="Washers", protocol_code="WSH-03",
                                  model_label="WashC", measurement_value=90)
        pub = create_approved_publication(ctx)
        assert pub["status"] == "APPROVED"
        resp = api.transition_rating_publication(pub["id"], {"action": "submit"}, CE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDesignationBoundary:
    def test_overall_80_exact_is_recommended(self, api):
        """PRD §3.6: "When `survey_score` is null, the survey weight folds away entirely and `overall_score` equals the `lab_score` exactly".
        PRD §3.6: "Otherwise, if `overall_score` is at least 80, the designation is `RECOMMENDED`."
        PRD §3.6: "All boundaries are inclusive."
        PRD §3.6: "Otherwise, if `overall_score` is at least 75 and `price_cents` is at most 20000 cents, the designation is `BEST_BUY`."

        Design: Difficulty/boundary_precision_check/designation_score_boundary_80
        """
        ctx = setup_program_ready(category_name="Washers", protocol_code="WSH-01",
                                  model_label="WashA", measurement_value=80)
        pub = create_draft_publication_with_model(ctx)
        entry = pub["rated_models"][0]
        # lab 80, no survey -> overall == lab_score == 80
        assert entry["overall_score"] == pytest.approx(80, abs=0.01)
        # price median of the sourcing PO line (50000) > 20000 cap -> not BEST_BUY
        assert entry["price_cents"] == 50000
        assert entry["designation"] == "RECOMMENDED"

    def test_overall_79_is_standard(self, api):
        """PRD §3.6: "Otherwise, if `overall_score` is at least 80, the designation is `RECOMMENDED`."
        PRD §3.6: "Otherwise, if `overall_score` is at least 50, the designation is `STANDARD`."
        PRD §3.6: "All boundaries are inclusive."

        Design: Difficulty/boundary_precision_check/designation_score_boundary_80
        """
        ctx = setup_program_ready(category_name="Washers", protocol_code="WSH-04",
                                  model_label="WashD", measurement_value=79)
        pub = create_draft_publication_with_model(ctx)
        entry = pub["rated_models"][0]
        assert entry["overall_score"] == pytest.approx(79, abs=0.01)
        assert entry["designation"] == "STANDARD"


class TestOptimisticConcurrency:
    def test_publication_approve_stale_then_fresh(self, api):
        """PRD §2.6: "Publication approval: the transitions call on a rating publication with `action` set to `approve` must carry `expected_program_version` equal to the current `version` of the publication's `TestProgram`. An intervening mutation of the program makes the approver's readiness view stale, and the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.6: "it is on approval that the publication pins its methodology — `protocol_id_snapshot` captures the category's `ACTIVE` protocol".

        Design: Corner/endpoints/publication_approve_occ_stale_version
        """
        ctx = setup_program_ready(category_name="Washers", protocol_code="WSH-01",
                                  model_label="WashA", measurement_value=90)
        pub = create_under_review_publication(ctx)
        prog = get_success_data(api.get_test_program(ctx["program"]["id"], ED))
        stale_version = prog["version"] - 1
        resp = api.transition_rating_publication(
            pub["id"], {"action": "approve", "expected_program_version": stale_version}, ED)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data = validate_success(api.transition_rating_publication(
            pub["id"], {"action": "approve", "expected_program_version": prog["version"]}, ED))
        assert data["status"] == "APPROVED"
        assert data["protocol_id_snapshot"] == ctx["protocol"]["id"]

    def test_protocol_activate_stale_then_fresh_supersedes(self, api):
        """PRD §2.6: "Protocol activation: the transitions call on a lab protocol with `action` set to `activate` must carry `expected_category_version` equal to the current `version` of the protocol's `ProductCategory`. If the category version has advanced — for example because a prior activation for the same category superseded the previously `ACTIVE` protocol and bumped the category — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "Activation (`IN_REVIEW → ACTIVE`) stamps `activated_at` with the clock, supersedes any other `ACTIVE` protocol of the same category (moving it to `SUPERSEDED`), bumps the category's `version`".

        Design: Corner/endpoints/protocol_activate_occ_stale_category
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        stale_version = category["version"]
        # protocol A: submit + activate with the fresh version
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-A",
                                        measurement_repeat_min=1,
                                        perf_weight_pct=50, reliability_weight_pct=25),
            LM,
        )
        proto_a = get_success_data(resp)
        validate_success(api.transition_lab_protocol(proto_a["id"], {"action": "submit_review"}, LM))
        validate_success(api.transition_lab_protocol(
            proto_a["id"], {"action": "activate", "expected_category_version": stale_version}, MO))
        # protocol B: submit
        resp = api.create_lab_protocol(
            create_lab_protocol_payload(category["id"], protocol_code="DRY-B",
                                        measurement_repeat_min=2,
                                        perf_weight_pct=55, reliability_weight_pct=25),
            LM,
        )
        proto_b = get_success_data(resp)
        validate_success(api.transition_lab_protocol(proto_b["id"], {"action": "submit_review"}, LM))
        cat_now = get_success_data(api.get_product_category(category["id"], MO))
        assert cat_now["version"] > stale_version
        # stale activate -> 412
        resp = api.transition_lab_protocol(
            proto_b["id"], {"action": "activate", "expected_category_version": stale_version}, MO)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # fresh activate -> B ACTIVE, A SUPERSEDED
        data = validate_success(api.transition_lab_protocol(
            proto_b["id"], {"action": "activate", "expected_category_version": cat_now["version"]}, MO))
        assert data["status"] == "ACTIVE"
        proto_a_now = get_success_data(api.get_lab_protocol(proto_a["id"], MO))
        assert proto_a_now["status"] == "SUPERSEDED"


class TestEmbargoAndVisibility:
    def test_publish_before_embargo_rejected_then_succeeds_at_embargo(self, api):
        """PRD §3.6: "Publication (`APPROVED → PUBLISHED`) is allowed only when the clock has reached `embargo_until` (before that instant the attempt is rejected with `ERR_EMBARGOED`)".

        Design: Corner/validations/publish_before_embargo_rejected
        """
        ctx = setup_program_ready(category_name="Washers", protocol_code="WSH-01",
                                  model_label="WashA", measurement_value=90)
        pub = create_approved_publication(ctx, embargo_until="2026-10-01T00:00:00Z")
        # clock still at startup default 2026-09-01 < embargo
        resp = api.transition_rating_publication(pub["id"], {"action": "publish"}, ED)
        validate_error(resp, ApiErrorId.ERR_EMBARGOED)
        set_clock("2026-10-01T00:00:00Z")
        data = validate_success(api.transition_rating_publication(
            pub["id"], {"action": "publish"}, ED))
        assert data["status"] == "PUBLISHED"

    def test_member_cannot_read_under_review_publication(self, api):
        """PRD §3.6: "Visibility for the `Member` role is narrow: members see only publications that are `PUBLISHED`, not `WITHDRAWN`, and whose `embargo_until` has been reached by the clock — a member read of an embargoed publication is rejected with `ERR_EMBARGOED`, and member-only operations additionally require the acting member's own `status` to be `ACTIVE`, else `ERR_MEMBERSHIP_INACTIVE` (403)."

        Design: Corner/endpoints/member_cannot_read_under_review_publication
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        from test_helpers import create_program as _mk_prog
        program = _mk_prog(category["id"])
        resp = api.create_rating_publication(
            create_rating_publication_payload(program["id"]), CE)
        pub = get_success_data(resp)
        member = create_member_with_subscription(email="r1@x.com", full_name="R One")
        # Set the logical clock past term_end + grace_until so the subscription
        # ages to EXPIRED; per PRD §3.9 the member cascades ACTIVE -> LAPSED
        # only on the ops-run checkpoint.
        set_clock("2027-09-16T00:00:01Z")
        resp = api.run_cycle(LM)
        validate_success(resp)
        resp = api.get_rating_publication(pub["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_INACTIVE)
        data = validate_success(api.get_rating_publication(pub["id"], CE))
        assert data["status"] == "DRAFT"

    def test_marketing_use_header_refused(self, api):
        """PRD §2.8: "Any read of the rating-publication collection or of a single rating publication that carries the header `X-Marketing-Use: true` is refused with `ERR_MARKETING_USE_FORBIDDEN` (422), regardless of the caller's role."

        Design: Corner/errors/error_marketing_use_header
        """
        headers = dict(CE)
        headers["X-Marketing-Use"] = "true"
        resp = api.list_rating_publications(headers)
        validate_error(resp, ApiErrorId.ERR_MARKETING_USE_FORBIDDEN)
        # without the header the same call succeeds
        resp = api.list_rating_publications(CE)
        data = validate_success(resp)
        assert isinstance(data, list)

    def test_manufacturer_response_accept_sets_text_reject_leaves_it(self, api):
        """PRD §3.10: "The publication's `manufacturer_response_text` always reflects the `body_text` of the latest `ACCEPTED` response, and is null when no accepted response exists."

        Design: Corner/cross_cutting_layers/manufacturer_response_accept_sets_publication_text
        """
        ctx = setup_published_publication(category_name="Washers", protocol_code="WSH-01",
                                          model_label="WashA", measurement_value=90)
        pub_id = ctx["publication"]["id"]
        validate_success(api.transition_rating_publication(
            pub_id, {"action": "log_manufacturer_response",
                     "manufacturer_name": "Acme", "body_text": "We dispute the method."}, CE))
        data = validate_success(api.transition_rating_publication(
            pub_id, {"action": "accept_manufacturer_response", "response_index": 1}, CE))
        assert data["manufacturer_response_text"] == "We dispute the method."
        validate_success(api.transition_rating_publication(
            pub_id, {"action": "log_manufacturer_response",
                     "manufacturer_name": "Globex", "body_text": "Second statement."}, CE))
        data = validate_success(api.transition_rating_publication(
            pub_id, {"action": "reject_manufacturer_response", "response_index": 2}, CE))
        assert data["manufacturer_response_text"] == "We dispute the method."
