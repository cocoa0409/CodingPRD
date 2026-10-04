"""Access control, not-found, pull gating, terminal lockdown, and
reverse-reachability listings."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_agreement_payload,
    create_approved_market,
    create_confirmed_slot,
    create_draft_statement,
    create_market_payload,
    create_validated_report,
    get_success_data,
    make_exhibitor_finance_headers,
    propose_slot,
    set_clock,
    setup_bookable_scenario,
    setup_confirmed_slot_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
PCM = TEST_USERS["contract_manager_headers"]
RS = TEST_USERS["release_scheduler_headers"]
BOA = TEST_USERS["box_office_analyst_headers"]


class TestRbac:
    def test_network_planner_cannot_sign_agreement(self, api):
        """PRD §2.1: "When the role is recognized but not permitted to perform
        the requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: `POST /v1/agreements/{agreementId}/sign` is authorized for
        PlatformContractManager only.

        Design: Corner/roles/network_planner_cannot_sign_agreement
        """
        set_clock()
        market = create_approved_market()
        agreement = get_success_data(
            api.create_agreement(
                create_agreement_payload(market_id=market["id"]), PCM)
        )
        resp = api.sign_agreement(agreement["id"], NP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        fetched = validate_success(api.get_agreement(agreement["id"], PCM))
        assert fetched["status"] == "NEGOTIATING"

    def test_exhibitor_finance_cannot_issue_statement(self, api):
        """PRD §2.1: "When the role is recognized but not permitted to perform
        the requested operation, the request is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: `POST /v1/revenue-share-statements/{statementId}/issue` is
        authorized for BoxOfficeAnalyst only.

        Design: Corner/roles/exhibitor_finance_cannot_issue_statement
        """
        ctx = setup_confirmed_slot_scenario()
        statement = create_draft_statement(ctx["agreement"]["id"],
                                           ctx["window"]["id"])
        efu = make_exhibitor_finance_headers(ctx["agreement"]["id"])
        resp = api.issue_statement(statement["id"], efu)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)

    def test_missing_user_context_header_rejected_400(self, api):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any
        other processing."

        Design: Corner/roles/network_planner_cannot_sign_agreement
        """
        set_clock()
        resp = api.create_market(create_market_payload(),
                                 headers={"Content-Type": "application/json"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400)


class TestReverseReachability:
    def test_list_auditoriums_by_agreement(self, api):
        """PRD §4: `GET /v1/agreements/{agreementId}/auditoriums` is "List
        auditoriums for an agreement"; PRD §3.1: "An Auditorium is registered
        under an agreement by a `PlatformContractManager` with an
        `agreement_id`"."

        Design: Corner/endpoints/fk_reverse_list_auditoriums_by_agreement
        """
        set_clock()
        market = create_approved_market()
        agreement = get_success_data(
            api.create_agreement(
                create_agreement_payload(market_id=market["id"],
                                         committed_screen_count=2), PCM)
        )
        aud_ids = set()
        for label in ("S1", "S2"):
            aud = get_success_data(api.create_auditorium(
                {"agreement_id": agreement["id"], "auditorium_label": label,
                 "screen_geometry": {"width_m": 20, "height_m": 11,
                                     "curvature_deg": 60},
                 "seating_capacity": 200, "supported_formats": ["PREMIUM_2D"],
                 "sound_calibration_profile": {"spl_target_db": 85,
                                               "eq_curve_id": "STD",
                                               "channel_count": 12}}, PCM))
            aud_ids.add(aud["id"])
        rows, meta = validate_paginated(
            api.list_agreement_auditoriums(agreement["id"], PCM)
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == aud_ids

    def test_list_auditoriums_excludes_other_agreements(self, api):
        """PRD §4: `GET /v1/agreements/{agreementId}/auditoriums` is "List
        auditoriums for an agreement" — the reverse reachability of the
        auditorium's `agreement_id` foreign key (§3.1).

        Design: Corner/endpoints/fk_reverse_list_auditoriums_by_agreement
        """
        set_clock()
        market = create_approved_market()
        agr_a = get_success_data(
            api.create_agreement(
                create_agreement_payload(market_id=market["id"]), PCM)
        )
        agr_b = get_success_data(
            api.create_agreement(
                create_agreement_payload(market_id=market["id"]), PCM)
        )
        get_success_data(api.create_auditorium(
            {"agreement_id": agr_a["id"], "auditorium_label": "A1",
             "screen_geometry": {"width_m": 20, "height_m": 11,
                                 "curvature_deg": 60},
             "seating_capacity": 200, "supported_formats": ["PREMIUM_2D"],
             "sound_calibration_profile": {"spl_target_db": 85,
                                           "eq_curve_id": "STD",
                                           "channel_count": 12}}, PCM))
        get_success_data(api.create_auditorium(
            {"agreement_id": agr_b["id"], "auditorium_label": "B1",
             "screen_geometry": {"width_m": 20, "height_m": 11,
                                 "curvature_deg": 60},
             "seating_capacity": 200, "supported_formats": ["PREMIUM_2D"],
             "sound_calibration_profile": {"spl_target_db": 85,
                                           "eq_curve_id": "STD",
                                           "channel_count": 12}}, PCM))
        rows, meta = validate_paginated(
            api.list_agreement_auditoriums(agr_a["id"], PCM)
        )
        assert meta["total_count"] == 1
        assert rows[0]["auditorium_label"] == "A1"


class TestPullGating:
    def test_pull_after_slot_start_rejected(self, api):
        """PRD §3.5: "From `CONFIRMED`, a pull requires the logical clock to
        be strictly earlier than `slot_start_date`; once the slot has
        started, the pull is rejected with `ERR_SLOT_ALREADY_STARTED`."

        Design: Corner/errors/pull_already_started_slot_returns_slot_already_started
        """
        ctx = setup_confirmed_slot_scenario()
        set_clock("2026-09-08T00:00:00Z")  # after slot start 2026-09-07
        resp = api.pull_slot(ctx["slot"]["id"], RS)
        validate_error(resp, ApiErrorId.ERR_SLOT_ALREADY_STARTED,
                       expected_status=409)
        slot = validate_success(api.get_screen_slot(ctx["slot"]["id"], RS))
        assert slot["status"] == "CONFIRMED"

    def test_pull_before_slot_start_succeeds(self, api):
        """PRD §3.5: "From `CONFIRMED`, a pull requires the logical clock to
        be strictly earlier than `slot_start_date`" and "A successful pull
        releases the slot's committed screen-seconds back to the window."

        Design: Corner/errors/pull_already_started_slot_returns_slot_already_started
        """
        ctx = setup_confirmed_slot_scenario()
        # Clock is at 2026-09-04 (setup approval instant), before the slot's
        # 2026-09-07 start.
        resp = api.pull_slot(ctx["slot"]["id"], RS)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "PULLED"
        window = validate_success(
            api.get_release_window(ctx["window"]["id"], RS))
        assert window["committed_premium_screen_seconds"] == 0


class TestTerminalLockdown:
    def test_terminated_agreement_rejects_further_transitions(self, api):
        """PRD §3.1: "Termination is available from `NEGOTIATING`, `SIGNED`,
        or `ACTIVE` and always lands in `TERMINATED`."
        PRD §2.9: "(5) the target resource's state permits the requested
        transition (`ERR_INVALID_STATE` or the transition's domain-specific
        error)."

        Design: Corner/state_machines/terminate_terminal_agreement_returns_invalid_state
        """
        set_clock()
        market = create_approved_market()
        agreement = get_success_data(
            api.create_agreement(
                create_agreement_payload(market_id=market["id"]), PCM)
        )
        get_success_data(api.terminate_agreement(agreement["id"], PCM))
        resp = api.sign_agreement(agreement["id"], PCM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        fetched = validate_success(api.get_agreement(agreement["id"], PCM))
        assert fetched["status"] == "TERMINATED"

    def test_terminated_agreement_rejects_reactivate(self, api):
        """PRD §3.1: "Termination is available from `NEGOTIATING`, `SIGNED`,
        or `ACTIVE` and always lands in `TERMINATED`." — no transition leaves
        TERMINATED, so activate from it must hit the state gate of §2.9:
        "(5) the target resource's state permits the requested transition
        (`ERR_INVALID_STATE` or the transition's domain-specific error)."

        Design: Corner/state_machines/terminate_terminal_agreement_returns_invalid_state
        """
        set_clock()
        market = create_approved_market()
        agreement = get_success_data(
            api.create_agreement(
                create_agreement_payload(market_id=market["id"]), PCM)
        )
        get_success_data(api.terminate_agreement(agreement["id"], PCM))
        resp = api.activate_agreement(agreement["id"], PCM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
