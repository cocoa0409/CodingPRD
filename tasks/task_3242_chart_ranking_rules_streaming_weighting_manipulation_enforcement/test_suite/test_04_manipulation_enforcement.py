"""Manipulation enforcement tests: signal escalation cascades, investigation
resolution findings, duty segregation, three-strikes suspension, and the
disqualify cascade.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_report,
    create_label,
    create_provider,
    create_sale_batch_ok,
    create_signal,
    create_title,
    create_week,
    disqualify_title_via_investigation,
    escalate_signal,
    escalate_signal_ok,
    get_label,
    get_success_data,
    get_title,
    get_week,
    resolve_investigation,
    resolve_investigation_ok,
    set_clock,
    setup_locked_week_with_sales,
    setup_open_week_scenario,
    setup_signal_escalated,
    submit_report_ok,
    validate_error,
    validate_paginated,
    validate_success,
    compute_week,
    publish_week,
)

OPS = TEST_USERS["chart_ops_headers"]


class TestEscalationCascades:
    def test_artificial_streaming_quarantines_streaming_reports_only(self, api):
        """PRD §3.6:"for `ARTIFICIAL_STREAMING`, every `ACCEPTED` report of
        the same title and week with a streaming component kind
        (`STREAM_ON_DEMAND_PAID`, `STREAM_ON_DEMAND_AD`, or
        `STREAM_PROGRAMMED`) moves to `QUARANTINED`"

    Design: Corner/state_machines/escalate_artificial_streaming_quarantines_streaming_reports"""
        scenario = setup_open_week_scenario()
        title = scenario["title"]
        week = scenario["week"]
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        pv_sales = create_provider(feed_kind="SALES", territory="DOMESTIC")
        r_str = submit_report_ok(pv_od, title["id"], week["id"],
                                 component_kind="STREAM_ON_DEMAND_PAID",
                                 quantity=2500, file_fingerprint="s9-str")
        r_sal = submit_report_ok(pv_sales, title["id"], week["id"],
                                 component_kind="SALES", quantity=9,
                                 file_fingerprint="s9-sal")
        accept_report(r_str["id"])
        accept_report(r_sal["id"])
        signal = create_signal(title["id"], week["id"], ops_user_id="ops-31",
                               signal_kind="ARTIFICIAL_STREAMING",
                               evidence="bot pattern")
        investigation = escalate_signal_ok(signal["id"], "inv-31",
                                           ops_user_id="ops-31")
        assert investigation["status"] == "OPEN"
        assert investigation["assigned_to"] == "inv-31"
        sig_after = get_success_data(api.get_signal(signal["id"], OPS))
        assert sig_after["status"] == "ESCALATED"
        str_after = get_success_data(api.get_report(r_str["id"], OPS))
        sal_after = get_success_data(api.get_report(r_sal["id"], OPS))
        assert str_after["status"] == "QUARANTINED"
        assert sal_after["status"] == "ACCEPTED", (
            "SALES reports are untouched by the ARTIFICIAL_STREAMING cascade")

    def test_bulk_purchase_escalation_zeroes_countable_units(self, api):
        """PRD §3.6:"for `BULK_PURCHASE`, every `CLEARED` sale batch of the
        same title and week moves to `UNDER_REVIEW` with its `countable_units`
        zeroed"

    Design: Difficulty/compensating_invariant/escalate_dismiss_restore_invariant"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        title = scenario["title"]
        week = scenario["week"]
        batch = create_sale_batch_ok(title["id"], channel="D2C", quantity=3,
                                     buyer_key="buyer-Z",
                                     chart_week_id=week["id"])
        assert batch["countable_units"] == 3
        signal = create_signal(title["id"], week["id"], ops_user_id="ops-88",
                               signal_kind="BULK_PURCHASE",
                               evidence="bulk pattern")
        escalate_signal_ok(signal["id"], "inv-99", ops_user_id="ops-88")
        batches, _ = validate_paginated(
            api.list_sale_batches(title["id"], OPS,
                                  params={"chart_week_id": week["id"]}))
        assert batches[0]["review_status"] == "UNDER_REVIEW"
        assert batches[0]["countable_units"] == 0, (
            "escalation zeroes countable_units")

    def test_dismissed_finding_restores_batches_and_reports(self, api):
        """PRD §3.6:"A `DISMISSED` finding restores what escalation froze:
        quarantined reports of the signal's title and week return
        `QUARANTINED → ACCEPTED`, and under-review sale batches return
        `UNDER_REVIEW → CLEARED` with `countable_units` recomputed under the
        per-buyer cap allocation"

    Design: Difficulty/compensating_invariant/escalate_dismiss_restore_invariant"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        title = scenario["title"]
        week = scenario["week"]
        batch = create_sale_batch_ok(title["id"], channel="D2C", quantity=3,
                                     buyer_key="buyer-Z",
                                     chart_week_id=week["id"])
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        report = submit_report_ok(pv_od, title["id"], week["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=2500, file_fingerprint="ci-1")
        accept_report(report["id"])
        signal = create_signal(title["id"], week["id"], ops_user_id="ops-88",
                               signal_kind="BULK_PURCHASE",
                               evidence="bulk pattern")
        investigation = escalate_signal_ok(signal["id"], "inv-99",
                                           ops_user_id="ops-88")
        resolve_investigation_ok(investigation["id"], "DISMISSED", "inv-99")
        batches, _ = validate_paginated(
            api.list_sale_batches(title["id"], OPS,
                                  params={"chart_week_id": week["id"]}))
        assert batches[0]["review_status"] == "CLEARED", "batch restored"
        assert batches[0]["countable_units"] == 3, (
            "countable_units recomputed to the pre-escalation value")
        report_after = get_success_data(api.get_report(report["id"], OPS))
        assert report_after["status"] == "ACCEPTED", (
            "streaming report untouched by the BULK_PURCHASE round trip")
        assert get_title(title["id"])["eligibility_posture"] == "ELIGIBLE"
        assert get_label(scenario["label"]["id"])["strike_count"] == 0


class TestDutySegregation:
    def test_self_assignment_rejected(self, api):
        """PRD §3.6:"segregation of duties forbids self-dealing: the
        payload's `assigned_to` — the opaque operator id of the investigator
        who will own the case — must differ from the escalating analyst's
        `X-User-ID`, with a violation rejected as
        `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403)"

    Design: Difficulty/priority_pair_validation_conflict/duty_segregation_beats_aggregate_cap"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM",
            title_overrides={"base_price_cents": 100})
        signal = create_signal(scenario["title"]["id"], scenario["week"]["id"],
                               ops_user_id="ops-77",
                               signal_kind="BULK_PURCHASE",
                               evidence="suspicious bulk")
        resp = escalate_signal(signal["id"], "ops-77", ops_user_id="ops-77")
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)
        investigations, meta = validate_paginated(
            api.list_investigations(OPS,
                                    params={"signal_id": signal["id"]}))
        assert investigations == [], "no investigation created on self-dealing"

    def test_self_assignment_rejected_streaming_signal(self, api):
        """PRD §3.6:"segregation of duties forbids self-dealing: the
        payload's `assigned_to` — the opaque operator id of the investigator
        who will own the case — must differ from the escalating analyst's
        `X-User-ID`, with a violation rejected as
        `ERR_DUTY_SEGREGATION_VIOLATION` (HTTP 403)"

    Design: Difficulty/priority_pair_validation_conflict/duty_segregation_beats_aggregate_cap"""
        scenario = setup_open_week_scenario()
        signal = create_signal(scenario["title"]["id"], scenario["week"]["id"],
                               ops_user_id="ops-self",
                               signal_kind="ARTIFICIAL_STREAMING",
                               evidence="e")
        resp = escalate_signal(signal["id"], "ops-self",
                               ops_user_id="ops-self")
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)

    def test_resolve_by_unassigned_investigator_rejected(self, api):
        """PRD §3.6:"Resolution belongs to the assigned `Investigator`
        alone: the resolver's `X-User-ID` must equal the investigation's
        `assigned_to` (again `ERR_DUTY_SEGREGATION_VIOLATION`)"

    Design: Corner/rbac/investigator_cannot_resolve_unassigned_case"""
        scenario = setup_signal_escalated(signal_kind="BULK_PURCHASE",
                                          ops_user_id="ops-r2",
                                          investigator_id="inv-81")
        investigation = scenario["investigation"]
        resp = resolve_investigation(investigation["id"], "DISMISSED", "inv-82",
                                     notes="wrong person")
        validate_error(resp, ApiErrorId.ERR_DUTY_SEGREGATION_VIOLATION)
        closed = resolve_investigation_ok(investigation["id"], "DISMISSED",
                                          "inv-81", notes="right person")
        assert closed["status"] == "CLOSED"


class TestSecondEscalation:
    def test_second_escalation_rejected(self, api):
        """PRD §3.6:"A signal supports at most one investigation; a second
        escalation attempt is rejected with `ERR_SIGNAL_ALREADY_ESCALATED`
        (HTTP 409)"

    Design: Corner/validations/second_escalation_rejected_signal_already_escalated"""
        scenario = setup_signal_escalated(signal_kind="BULK_PURCHASE",
                                          ops_user_id="ops-41",
                                          investigator_id="inv-41")
        signal = scenario["signal"]
        resp = escalate_signal(signal["id"], "inv-42")
        from test_helpers import validate_error_is_one_of
        # The signal is now ESCALATED: either the state-legality check or the
        # single-investigation uniqueness guard may surface first.
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_SIGNAL_ALREADY_ESCALATED,
                   ApiErrorId.ERR_INVALID_STATE])
        assert resp.status_code == 409
        investigations, meta = validate_paginated(
            api.list_investigations(OPS, params={"signal_id": signal["id"]}))
        assert len(investigations) == 1
        assert investigations[0]["id"] == scenario["investigation"]["id"]


class TestSignalDismissTerminal:
    def test_dismissed_signal_cannot_be_escalated(self, api):
        """PRD §3.6:"A signal is born `OPEN`; the analyst may dismiss it
        (`OPEN → DISMISSED`) or escalate it (`OPEN → ESCALATED`)"

    Design: Corner/state_machines/signal_dismiss_terminal_no_escalation_after"""
        scenario = setup_open_week_scenario()
        signal = create_signal(scenario["title"]["id"], scenario["week"]["id"],
                               signal_kind="BULK_PURCHASE", evidence="weak")
        get_success_data(api.dismiss_signal(signal["id"], OPS))
        resp = escalate_signal(signal["id"], "inv-32")
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestSuspendedLabelEscalationGate:
    def test_escalate_signal_on_suspended_label_rejected(self, api):
        """PRD §3.6:"The title's owning label account must be `ACTIVE` —
        escalating against a suspended label is rejected with
        `ERR_ACCOUNT_SUSPENDED`"

    Design: Corner/validations/escalate_signal_on_suspended_label_rejected"""
        scenario = setup_open_week_scenario()
        label = scenario["label"]
        week = scenario["week"]
        titles = [scenario["title"]]
        for i in range(2, 5):
            titles.append(create_title(label, upc=f"UPC-V6-{i}",
                                       title=f"V6 T{i}"))
        for i, title in enumerate(titles[:3], start=1):
            disqualify_title_via_investigation(title["id"], week["id"],
                                               f"inv-5{i}")
        assert get_label(label["id"])["account_status"] == "SUSPENDED"
        signal = create_signal(titles[3]["id"], week["id"],
                               signal_kind="ARTIFICIAL_STREAMING",
                               evidence="s4")
        resp = escalate_signal(signal["id"], "inv-51")
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)


class TestDisqualifyCascade:
    def test_disqualify_cascade_depth(self, api):
        """PRD §3.6:"A `DISQUALIFY` finding is the maximum sanction: the
        title's `eligibility_posture` becomes `DISQUALIFIED`; every chart
        entry of the title on the signal's week transitions to
        `RECURRENT_REMOVED`; all of the title's reports for that week in
        `ACCEPTED` or `QUARANTINED` become `EXCLUDED`; affected `COMPUTED`
        weeks are invalidated to `LOCKED`; and the owning label's
        `strike_count` increments by 1. A label whose `strike_count` reaches
        3 transitions `ACTIVE → SUSPENDED`"

    Design: Difficulty/transitive_cascade/disqualify_cascade_depth3"""
        label = create_label()
        t1 = create_title(label, upc="UPC-TC-1", title="Song TC1")
        t2 = create_title(label, upc="UPC-TC-2", title="Song TC2")
        t3 = create_title(label, upc="UPC-TC-3", title="Song TC3")
        from test_helpers import setup_chart_with_active_methodology
        chart, mv, rr = setup_chart_with_active_methodology()
        week = create_week(chart)
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        report = submit_report_ok(pv_od, t3["id"], week["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=10000, file_fingerprint="tc-p3")
        accept_report(report["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], TEST_USERS["chart_manager_headers"]))
        compute_week(week["id"])
        publish_week(week["id"])
        disqualify_title_via_investigation(t1["id"], week["id"], "inv-op-1")
        disqualify_title_via_investigation(t2["id"], week["id"], "inv-op-1")
        from test_helpers import create_signal as _cs
        signal = _cs(t3["id"], week["id"],
                     signal_kind="ARTIFICIAL_STREAMING",
                     evidence="strike 3 target")
        investigation = escalate_signal_ok(signal["id"], "inv-op-1")
        resolve_investigation_ok(investigation["id"], "DISQUALIFY", "inv-op-1")
        assert get_title(t3["id"])["eligibility_posture"] == "DISQUALIFIED"
        entries, _ = validate_paginated(
            api.list_week_entries(week["id"], TEST_USERS["chart_manager_headers"]))
        from test_helpers import find_entry
        entry = find_entry(entries, t3["id"])
        assert entry is not None
        assert entry["entry_status"] == "RECURRENT_REMOVED"
        report_after = get_success_data(api.get_report(report["id"], OPS))
        assert report_after["status"] == "EXCLUDED"
        label_after = get_label(label["id"])
        assert label_after["strike_count"] == 3
        assert label_after["account_status"] == "SUSPENDED", (
            "three-strikes rule: ACTIVE -> SUSPENDED at strike 3")

    def test_disqualify_immediate_consistency(self, api):
        """PRD §3.6: "A `DISQUALIFY` finding is the maximum sanction: the
        title's `eligibility_posture` becomes `DISQUALIFIED`; every chart
        entry of the title on the signal's week transitions to
        `RECURRENT_REMOVED`; all of the title's reports for that week in
        `ACCEPTED` or `QUARANTINED` become `EXCLUDED`; affected `COMPUTED`
        weeks are invalidated to `LOCKED`; and the owning label's
        `strike_count` increments by 1"

        Design: Corner/consistency_model/immediate_consistency_disqualify_visible_in_same_response_chain"""
        scenario = setup_signal_escalated(signal_kind="ARTIFICIAL_STREAMING",
                                          ops_user_id="ops-cm1",
                                          investigator_id="inv-95")
        investigation = scenario["investigation"]
        resolve_investigation_ok(investigation["id"], "DISQUALIFY", "inv-95")
        assert get_title(scenario["title"]["id"])["eligibility_posture"] == "DISQUALIFIED"
        assert get_label(scenario["label"]["id"])["strike_count"] == 1


class TestThreeStrikesThreshold:
    def test_threshold_crossing_and_reinstate_keeps_strikes(self, api):
        """PRD §3.6:"A label whose `strike_count` reaches 3 transitions
        `ACTIVE → SUSPENDED` — the three-strikes rule — which in turn blocks
        further signal escalations against its titles. A `ChartManager` may
        reinstate a suspended label account, moving it `SUSPENDED →
        ACTIVE`"

    Design: Corner/cross_cutting_layers/three_strikes_label_suspension_threshold_trigger"""
        scenario = setup_open_week_scenario()
        label = scenario["label"]
        week = scenario["week"]
        titles = [scenario["title"]]
        for i in range(2, 4):
            titles.append(create_title(label, upc=f"UPC-CC2-{i}",
                                       title=f"CC2 T{i}"))
        disqualify_title_via_investigation(titles[0]["id"], week["id"], "inv-91")
        disqualify_title_via_investigation(titles[1]["id"], week["id"], "inv-91")
        mid = get_label(label["id"])
        assert mid["strike_count"] == 2
        assert mid["account_status"] == "ACTIVE", "below the threshold"
        disqualify_title_via_investigation(titles[2]["id"], week["id"], "inv-91")
        end = get_label(label["id"])
        assert end["strike_count"] == 3
        assert end["account_status"] == "SUSPENDED", "threshold crossing"
        reinstated = validate_success(
            api.reinstate_label(label["id"], TEST_USERS["chart_manager_headers"]))
        assert reinstated["account_status"] == "ACTIVE"
        assert reinstated["strike_count"] == 3, "reinstate does not reset strikes"

    def test_two_strikes_leaves_label_active(self, api):
        """PRD §3.6:"A label whose `strike_count` reaches 3 transitions
        `ACTIVE → SUSPENDED` — the three-strikes rule"

    Design: Corner/cross_cutting_layers/three_strikes_label_suspension_threshold_trigger"""
        scenario = setup_open_week_scenario()
        label = scenario["label"]
        week = scenario["week"]
        t2 = create_title(label, upc="UPC-TS-2", title="TS2")
        disqualify_title_via_investigation(scenario["title"]["id"], week["id"],
                                           "inv-92")
        disqualify_title_via_investigation(t2["id"], week["id"], "inv-92")
        label_after = get_label(label["id"])
        assert label_after["strike_count"] == 2
        assert label_after["account_status"] == "ACTIVE"


class TestPublishBlockedByDisqualifiedTitle:
    def test_publish_rejected_when_entry_title_disqualified(self, api):
        """PRD §3.5:"Publishing requires the week's pinned
        `computed_methodology_version_id` to still equal the chart's
        `current_methodology_version_id`, no active freeze, and no entry
        whose title's `eligibility_posture` is `DISQUALIFIED` — such a
        publish is rejected with `ERR_TITLE_DISQUALIFIED`"

    Design: Corner/validations/publish_blocked_when_week_contains_disqualified_title"""
        scenario = setup_locked_week_with_sales(sales_quantity=5)
        title = scenario["title"]
        w1 = scenario["week"]
        compute_week(w1["id"])
        # Disqualify via a signal attached to a week of a *different* chart:
        # the DISQUALIFY cascade invalidates computed weeks of the signal's
        # chart only, so w1 stays COMPUTED and the publish gate on title
        # posture must fire.
        from test_helpers import setup_chart_with_active_methodology
        other_chart, _other_mv, _other_rr = setup_chart_with_active_methodology()
        other_week = create_week(other_chart, week_index=1,
                                 opens_at="2026-09-04T00:00:00Z",
                                 closes_at="2026-09-11T00:00:00Z")
        disqualify_title_via_investigation(title["id"], other_week["id"], "inv-61")
        resp = api.publish_week(w1["id"], TEST_USERS["chart_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_TITLE_DISQUALIFIED)
        assert get_week(w1["id"])["status"] != "PUBLISHED", (
            "publish did not succeed")
