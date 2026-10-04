"""Safety findings, escalation cascades, membership grace windows, members,
RBAC exclusivity, envelope validation, and filtered-list reachability.

Covers difficulty instances: safety_tier3_depth3_cascade,
cycle_run_depth2_member_lapse, grace_interval_closed_end — and corner instances:
finding_close_open_tier1_invalid, grace_boundary_one_second_past,
member_create_duplicate_email, error_invalid_request_missing_field,
error_unauthenticated_and_unauthorized, peer_role_exclusive_denials,
fk_reverse_reachability_lists.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_product_category_payload, create_safety_finding_payload,
    create_purchase_order_payload, create_po_line_payload,
    create_member_payload, create_survey_wave_payload,
    create_category, create_program, create_sample,
    create_member_with_subscription, setup_published_publication, set_clock,
    TEST_USERS, make_member_headers,
)

LM = TEST_USERS["lab_manager_headers"]
SD = TEST_USERS["survey_director_headers"]
SO = TEST_USERS["safety_officer_headers"]
CE = TEST_USERS["content_editor_headers"]
PA = TEST_USERS["purchasing_agent_headers"]
LT = TEST_USERS["lab_technician_headers"]


class TestSafetyCascade:
    def test_tier3_escalate_withdraws_publication_and_flips_designation(self, api):
        """PRD §3.7: "a `CRITICAL` finding with `hazard_flag` set lifts it to tier 3 (regulator communication)".
        PRD §3.7: "At tier 2 or higher, every rated-model entry in the program's non-`WITHDRAWN` publications whose sample's `model_label` matches the finding's sample's `model_label` flips its `designation` to `NOT_RECOMMENDED`."
        PRD §3.7: "At tier 3 exactly, the cascade goes one level deeper: every `PUBLISHED` rating publication of the program is withdrawn".

        Design: Difficulty/transitive_cascade/safety_tier3_depth3_cascade
        """
        ctx = setup_published_publication(category_name="Washers", protocol_code="WSH-01",
                                          model_label="WashA", measurement_value=90)
        pub_id = ctx["publication"]["id"]
        pub = get_success_data(api.get_rating_publication(pub_id, SO))
        assert pub["status"] == "PUBLISHED"
        assert pub["rated_models"][0]["designation"] == "RECOMMENDED"
        resp = api.create_safety_finding(
            create_safety_finding_payload(
                ctx["program"]["id"], ctx["sample"]["id"],
                severity="CRITICAL", description_text="shock hazard", hazard_flag=True,
            ),
            SO,
        )
        finding = get_success_data(resp)
        assert finding["escalation_tier"] == 3
        data = validate_success(api.transition_safety_finding(
            finding["id"], {"action": "escalate"}, SO))
        assert data["status"] == "ESCALATED"
        pub = get_success_data(api.get_rating_publication(pub_id, SO))
        assert pub["status"] == "WITHDRAWN"
        assert pub["rated_models"][0]["designation"] == "NOT_RECOMMENDED"

    def test_tier3_escalate_reverts_program_and_recomputes_category(self, api):
        """PRD §3.7: "every `PUBLISHED` rating publication of the program is withdrawn, which in turn reverts the program from `PUBLISHED` to `READY_FOR_PUBLICATION` and recomputes the category's `last_published_at` and `selection_score` — a depth-3 cascade from escalate, through designation flip, to withdrawal."
        PRD §3.6: "Withdrawing a `PUBLISHED` publication reverts the program `PUBLISHED → READY_FOR_PUBLICATION` and recomputes the category's `last_published_at` from the remaining `PUBLISHED` non-`WITHDRAWN` publications (null when none remain) together with its `selection_score`."

        Design: Difficulty/transitive_cascade/safety_tier3_depth3_cascade
        """
        ctx = setup_published_publication(category_name="Washers", protocol_code="WSH-05",
                                          model_label="WashE", measurement_value=90)
        category_id = ctx["category"]["id"]
        cat = get_success_data(api.get_product_category(category_id, LM))
        assert cat["last_published_at"] is not None
        resp = api.create_safety_finding(
            create_safety_finding_payload(
                ctx["program"]["id"], ctx["sample"]["id"],
                severity="CRITICAL", description_text="shock hazard", hazard_flag=True,
            ),
            SO,
        )
        finding = get_success_data(resp)
        validate_success(api.transition_safety_finding(finding["id"], {"action": "escalate"}, SO))
        program = get_success_data(api.get_test_program(ctx["program"]["id"], LM))
        assert program["status"] == "READY_FOR_PUBLICATION"
        cat = get_success_data(api.get_product_category(category_id, LM))
        assert cat["last_published_at"] is None

    def test_close_from_open_tier1_rejected(self, api):
        """PRD §3.7: "Closure is the terminal move to `CLOSED`, available from `RESOLVED` always, or directly from `OPEN` when the `escalation_tier` is 0."
        PRD §3.7: "a `MAJOR` or `CRITICAL` severity lifts the finding to tier 1 (manufacturer notice)".
        PRD §2.5: "State — the target resource is in a valid from-state for the requested action and the action name itself is known; failure yields `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/finding_close_open_tier1_invalid
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        program = create_program(category["id"])
        sample = create_sample(program["id"], model_label="Dry1", required_units=1)
        resp = api.create_safety_finding(
            create_safety_finding_payload(
                program["id"], sample["id"],
                severity="MAJOR", description_text="door latch", hazard_flag=False,
            ),
            SO,
        )
        finding = get_success_data(resp)
        assert finding["escalation_tier"] == 1
        resp = api.transition_safety_finding(finding["id"], {"action": "close"}, SO)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestMembershipAndCycle:
    def test_cycle_run_lapses_member_after_grace_expiry(self, api):
        """PRD §3.9: "Every subscription in `ACTIVE` or `GRACE` is re-epoch'd against the clock with closed interval boundaries: at or before `term_end` the subscription stays `ACTIVE`; strictly after `term_end` but at or before `grace_until` it is `GRACE`".
        PRD §3.9: "Every member whose latest subscription has become `EXPIRED` cascades from `ACTIVE` to `LAPSED` — a depth-2 cascade from the cycle run through the subscription transition to the member — counted in `members_lapsed`."

        Design: Difficulty/transitive_cascade/cycle_run_depth2_member_lapse
        """
        member = create_member_with_subscription(
            email="m1@x.com", full_name="M One",
            term_start="2026-09-01T00:00:00Z", term_end="2026-09-02T00:00:00Z")
        # grace_until = 2026-09-16T00:00:00Z; advance past it
        set_clock("2026-09-17T00:00:00Z")
        data = validate_success(api.run_cycle(LM))
        assert data["members_lapsed"] == 1
        member_now = get_success_data(api.get_member(member["id"], LM))
        assert member_now["status"] == "LAPSED"

    def test_grace_until_closed_end_holds_and_renew_succeeds(self, api):
        """PRD §3.9: "strictly after `term_end` but at or before `grace_until` it is `GRACE` — note the boundary instant `grace_until` itself is still `GRACE`, and only the first instant after it is `EXPIRED`".
        PRD §3.9: "Renewal supplies `subscription_id` and a new `term_end`, recomputes `grace_until` from the new term end, and increments `renewal_count` by one; a successful renewal on a `GRACE` subscription cascades the member from `LAPSED` back to `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/grace_interval_closed_end
        """
        member = create_member_with_subscription(
            email="g1@x.com", full_name="G One",
            term_start="2026-09-01T00:00:00Z", term_end="2026-09-02T00:00:00Z")
        # grace_until = term_end + 14 days = 2026-09-16T00:00:00Z
        set_clock("2026-09-10T00:00:00Z")
        validate_success(api.run_cycle(LM))
        # member LAPSED during GRACE? No: lapse only happens on EXPIRED. Move to grace_until.
        set_clock("2026-09-16T00:00:00Z")
        data = validate_success(api.run_cycle(LM))
        # closed end: grace_until itself is still GRACE -> nothing transitions to EXPIRED
        assert data["subscriptions_transitioned"] == 0
        data = validate_success(api.transition_member(
            member["id"],
            {"action": "renew", "subscription_id": "1", "term_end": "2027-09-16T00:00:00Z"},
            make_member_headers(member["id"]),
        ))
        subs = [s for s in data["subscriptions"] if s["subscription_id"] == "1"]
        assert len(subs) == 1
        assert subs[0]["renewal_count"] == 1

    def test_one_second_past_grace_until_expires_and_lapses(self, api):
        """PRD §3.9: "strictly after `term_end` but at or before `grace_until` it is `GRACE` — note the boundary instant `grace_until` itself is still `GRACE`, and only the first instant after it is `EXPIRED` (a half-open reading of the window would lapse the member one instant early and is a rejected alternative)".
        PRD §3.9: "Every member whose latest subscription has become `EXPIRED` cascades from `ACTIVE` to `LAPSED` — a depth-2 cascade from the cycle run through the subscription transition to the member — counted in `members_lapsed`."

        Design: Corner/calculations/grace_boundary_one_second_past
        """
        member = create_member_with_subscription(
            email="g2@x.com", full_name="G Two",
            term_start="2026-09-01T00:00:00Z", term_end="2026-09-02T00:00:00Z")
        set_clock("2026-09-16T00:00:01Z")
        data = validate_success(api.run_cycle(LM))
        assert data["subscriptions_transitioned"] == 1
        assert data["members_lapsed"] == 1
        member_now = get_success_data(api.get_member(member["id"], LM))
        assert member_now["status"] == "LAPSED"

    def test_member_duplicate_email_rejected(self, api):
        """PRD §3.9: "A member self-registers under the `Member` role by supplying a unique `email` — lowercased before comparison, with duplicates rejected as `ERR_DUPLICATE`".

        Design: Corner/entities/member_create_duplicate_email
        """
        validate_success(api.create_member(
            create_member_payload(email="dup@x.com", full_name="Dup"),
            make_member_headers("member-registrar")), expected_status=201)
        resp = api.create_member(
            create_member_payload(email="dup@x.com", full_name="Dup Two"),
            make_member_headers("member-registrar"))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestAuthAndRbac:
    def test_missing_role_header_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or declaring a role the system does not know, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_and_unauthorized
        """
        resp = api.list_test_programs({"X-User-ID": "someone"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_member_role_on_lab_manager_endpoint_unauthorized(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | /product-categories | Create a category; selection_score computed with null last_published_at | LabManager |".

        Design: Corner/errors/error_unauthenticated_and_unauthorized
        """
        member = create_member_with_subscription(email="a1@x.com", full_name="A One")
        resp = api.create_product_category(
            create_product_category_payload(name="X", refresh_cycle_months=12,
                                            market_share_pct=1, member_interest_pct=1),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_peer_role_exclusive_denials(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | /test-programs/{id}/transitions | Program actions: approve, start_sourcing, start_testing, start_scoring, ready, cancel | LabManager, EditorialDirector |".
        PRD §4: "| POST | /purchase-orders | Create a DRAFT purchase order with embedded lines; tax computed | PurchasingAgent |".
        PRD §4: "| POST | /survey-waves/{id}/transitions | Wave actions: submit_response, exclude_response, close, qualify (OCC), disqualify | SurveyDirector, Member |".

        Design: Corner/rbac/peer_role_exclusive_denials
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        program = create_program(category["id"])
        resp = api.create_survey_wave(
            create_survey_wave_payload(category["id"]), SD)
        wave = get_success_data(resp)
        # PurchasingAgent cannot run program transitions
        resp = api.transition_test_program(program["id"], {"action": "approve"}, PA)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        # SurveyDirector cannot create purchase orders
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                program["id"],
                [create_po_line_payload("00000000-0000-4000-8000-000000000000",
                                        unit_price_cents=1)],
                buyer_alias="alias-x", retailer_name="ToolMart", receipt_doc_ref="RX",
            ),
            SD,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        # LabTechnician cannot run wave transitions
        resp = api.transition_survey_wave(wave["id"], {"action": "close"}, LT)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestStructureAndReachability:
    def test_missing_required_field_invalid_request(self, api):
        """PRD §2.5: "Structural request validity — required fields present, well-typed, enum values valid, numeric ranges respected; failure yields `ERR_INVALID_REQUEST` (400)."

        Design: Corner/errors/error_invalid_request_missing_field
        """
        resp = api.create_product_category(
            {"name": "Broken", "market_share_pct": 10, "member_interest_pct": 10}, LM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_filtered_lists_reverse_reachability(self, api):
        """PRD §4: "| GET | /test-programs | List programs; optional `category_id`, `status` filters | LabManager, EditorialDirector, MethodologyOfficer, SurveyDirector, SafetyOfficer, ContentEditor, ComplianceOfficer, PurchasingAgent, LabTechnician |".
        PRD §4: "| GET | /test-samples | List samples; optional `program_id`, `status` filters | LabManager, LabTechnician, PurchasingAgent, ComplianceOfficer, ContentEditor, SafetyOfficer |".
        PRD §2.3: "The `meta` block of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        category = create_category(name="Dryers", market_share_pct=20, member_interest_pct=20)
        program = create_program(category["id"])
        sample = create_sample(program["id"], model_label="Dry1", required_units=1)
        resp = api.list_test_programs(LM, params={"category_id": category["id"]})
        progs, meta = validate_paginated(resp)
        assert [p["id"] for p in progs] == [program["id"]]
        assert meta["total_count"] == 1
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta
        resp = api.list_test_samples(LM, params={"program_id": program["id"]})
        samples, meta = validate_paginated(resp)
        assert [s["id"] for s in samples] == [sample["id"]]
        assert meta["total_count"] == 1


class TestGraceWindowSecond:
    def test_renew_recomputes_grace_until(self, api):
        """PRD §3.9: "Renewal supplies `subscription_id` and a new `term_end`, recomputes `grace_until` from the new term end, and increments `renewal_count` by one".

        Design: Difficulty/resource_temporal_overlap/grace_interval_closed_end
        """
        member = create_member_with_subscription(
            email="g3@x.com", full_name="G Three",
            term_start="2026-09-01T00:00:00Z", term_end="2026-09-02T00:00:00Z")
        data = validate_success(api.transition_member(
            member["id"],
            {"action": "renew", "subscription_id": "1", "term_end": "2027-09-16T00:00:00Z"},
            make_member_headers(member["id"]),
        ))
        subs = [s for s in data["subscriptions"] if s["subscription_id"] == "1"]
        assert len(subs) == 1
        # grace_until recomputed: new term_end + 14 days
        assert subs[0]["grace_until"].startswith("2027-09-30")
        assert subs[0]["renewal_count"] == 1


class TestCycleRunSecond:
    def test_cycle_counts_subscription_transition_before_lapse(self, api):
        """PRD §3.9: "Every subscription in `ACTIVE` or `GRACE` is re-epoch'd against the clock with closed interval boundaries: at or before `term_end` the subscription stays `ACTIVE`; strictly after `term_end` but at or before `grace_until` it is `GRACE` — note the boundary instant `grace_until` itself is still `GRACE`, and only the first instant after it is `EXPIRED` (a half-open reading of the window would lapse the member one instant early and is a rejected alternative). Transitions are counted in `subscriptions_transitioned`."

        Design: Difficulty/transitive_cascade/cycle_run_depth2_member_lapse
        """
        member = create_member_with_subscription(
            email="m2@x.com", full_name="M Two",
            term_start="2026-09-01T00:00:00Z", term_end="2026-09-02T00:00:00Z")
        # grace_until = 2026-09-16T00:00:00Z; one second past it
        set_clock("2026-09-16T00:00:01Z")
        data = validate_success(api.run_cycle(LM))
        assert data["subscriptions_transitioned"] == 1
        assert data["members_lapsed"] == 1
        member_now = get_success_data(api.get_member(member["id"], LM))
        assert member_now["status"] == "LAPSED"
        sub = [s for s in member_now["subscriptions"] if s["subscription_id"] == "1"][0]
        assert sub["status"] == "EXPIRED"


class TestSegregationOfDutiesChain:
    def test_placer_cannot_verify_and_distinct_officer_succeeds(self, api):
        """PRD §1: "the agent who places a purchase order may not verify its sourcing documentation".
        PRD §3.3: "the verifier's `X-User-ID` must differ from `placed_by_user_id` (`ERR_SOD_VIOLATION` otherwise)".
        PRD §3.3: "The verifier is stamped into `verified_by_user_id`."

        Design: Corner/rbac/segregation_of_duties_full_chain
        """
        from test_helpers import setup_program_sourcing, create_purchase_order_payload, create_po_line_payload
        ctx = setup_program_sourcing(category_name="Dryers", protocol_code="DRY-01",
                                     model_label="Dry1", market_share_pct=20,
                                     member_interest_pct=20)
        from test_helpers import make_purchasing_agent_headers, make_compliance_officer_headers
        pa_headers = make_purchasing_agent_headers("pa-7")
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"],
                [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1000)],
                buyer_alias="alias-7", retailer_name="ToolMart", receipt_doc_ref="R7",
            ),
            TEST_USERS["purchasing_agent_headers"],
        )
        po = get_success_data(resp)
        validate_success(api.transition_purchase_order(po["id"], {"action": "place"}, pa_headers))
        validate_success(api.transition_purchase_order(po["id"], {"action": "receive"}, pa_headers))
        # same id on the verify side -> SoD violation
        resp = api.transition_purchase_order(
            po["id"], {"action": "verify"}, make_compliance_officer_headers("pa-7"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        # distinct officer succeeds and is stamped
        data = validate_success(api.transition_purchase_order(
            po["id"], {"action": "verify"}, make_compliance_officer_headers("co-7")))
        assert data["status"] == "VERIFIED"
        assert data["verified_by_user_id"] == "co-7"
