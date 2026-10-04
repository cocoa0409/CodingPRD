"""Genre disputes, provider/report guards, RBAC, and entity/envelope corners.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    accept_report,
    create_dispute_under_review,
    create_label,
    create_provider,
    create_recurrent_rule,
    create_sale_batch,
    create_title,
    get_dispute,
    get_success_data,
    get_title,
    make_chart_ops_headers,
    make_data_provider_headers,
    make_label_rep_headers,
    setup_open_week_scenario,
    submit_report,
    submit_report_ok,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["chart_manager_headers"]
OPS = TEST_USERS["chart_ops_headers"]


class TestGenreReclassificationCascade:
    def test_reclassify_rewrites_genre_and_marks_reentries_processed(self, api):
        """PRD §3.7:"Resolution with `resolution` `RECLASSIFY` requires the
        supplied `new_genre_tag` to equal the disputed chart's `genre_tag` —
        a mismatch is `ERR_RECLASSIFICATION_TARGET_MISMATCH` (HTTP 422) — and
        closes the dispute as `RESOLVED_RECLASSIFIED` while rewriting the
        title's `genre_tag` to `new_genre_tag` and incrementing the title's
        `version`"

    Design: Difficulty/transitive_cascade/genre_reclassification_reentry_cascade"""
        scenario = setup_open_week_scenario(
            chart_scope="GENRE", genre_tag="country", title_genre="pop")
        title = scenario["title"]
        dispute = create_dispute_under_review(title, scenario["chart"],
                                              scenario["label"],
                                              claimed_genre="country")
        resolved = validate_success(
            api.resolve_dispute(dispute["id"],
                                {"resolution": "RECLASSIFY",
                                 "new_genre_tag": "country"}, MANAGER))
        assert resolved["status"] == "RESOLVED_RECLASSIFIED"
        assert resolved["reentries_processed"] is True, (
            "re-entry evaluation cascade ran on the dispute's chart")
        title_after = get_title(title["id"])
        assert title_after["genre_tag"] == "country"
        assert title_after["version"] == title["version"] + 1

    def test_uphold_resolution_closes_without_side_effects(self, api):
        """PRD §3.7:"Resolution with `resolution` `UPHOLD` closes the
        dispute as `RESOLVED_UPHELD` with no further effect"

    Design: Difficulty/transitive_cascade/genre_reclassification_reentry_cascade"""
        scenario = setup_open_week_scenario(
            chart_scope="GENRE", genre_tag="country", title_genre="pop")
        title = scenario["title"]
        dispute = create_dispute_under_review(title, scenario["chart"],
                                              scenario["label"],
                                              claimed_genre="country")
        resolved = validate_success(
            api.resolve_dispute(dispute["id"], {"resolution": "UPHOLD"},
                                MANAGER))
        assert resolved["status"] == "RESOLVED_UPHELD"
        assert get_title(title["id"])["genre_tag"] == "pop", (
            "UPHOLD leaves the title's genre unchanged")


class TestGenreDisputeTerminalLockdown:
    def test_review_on_resolved_dispute_rejected(self, api):
        """PRD §3.7:"A dispute is born `FILED`; a `ChartOps` analyst moves
        it `FILED → UNDER_REVIEW`; a `ChartManager` then resolves it"

    Design: Corner/state_machines/terminal_states_lockdown_dispute_and_report"""
        scenario = setup_open_week_scenario(
            chart_scope="GENRE", genre_tag="country", title_genre="pop")
        dispute = create_dispute_under_review(
            scenario["title"], scenario["chart"], scenario["label"],
            claimed_genre="country")
        get_success_data(api.resolve_dispute(dispute["id"],
                                             {"resolution": "UPHOLD"}, MANAGER))
        resp = api.review_dispute(dispute["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_accept_on_rejected_report_rejected(self, api):
        """PRD §3.3:"Report acceptance is a `ChartOps` decision and is
        heavily guarded: the report must still be `RECEIVED` (anything else
        is `ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/terminal_states_lockdown_dispute_and_report"""
        scenario = setup_open_week_scenario()
        provider = create_provider(feed_kind="STREAM_ON_DEMAND",
                                   territory="DOMESTIC")
        report = submit_report_ok(provider, scenario["title"]["id"],
                                  scenario["week"]["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=2500, file_fingerprint="s4-a")
        get_success_data(api.reject_report(report["id"], {"reason": "bad data"},
                                           OPS))
        resp = api.accept_report(report["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestLabelRepDisputeOwnership:
    def test_non_owning_label_dispute_filing_rejected(self, api):
        """PRD §3.7:"Filing is valid only against a `GENRE`-scoped chart —
        never a `MAIN` chart — the `claimed_genre` must differ from the
        title's current `genre_tag`, and the filing label must be the title's
        owning label; violations surface as `ERR_DISPUTE_INVALID` (HTTP 422)
        or, for the ownership leg, `ERR_UNAUTHORIZED`"

    Design: Corner/rbac/labelrep_dispute_ownership_enforced"""
        label1 = create_label()
        label2 = create_label()
        title = create_title(label1, genre_tag="pop")
        scenario_chart_rr = create_recurrent_rule()
        from test_helpers import create_chart
        chart = create_chart(scenario_chart_rr["id"], chart_scope="GENRE",
                             genre_tag="country", chart_code="GEN-R3",
                             title="Country R3")
        resp = api.create_dispute(
            {"title_product_id": title["id"], "chart_id": chart["id"],
             "filed_by_label_id": label2["id"], "claimed_genre": "country"},
            make_label_rep_headers(label2["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        resp = api.create_dispute(
            {"title_product_id": title["id"], "chart_id": chart["id"],
             "filed_by_label_id": label1["id"], "claimed_genre": "country"},
            make_label_rep_headers(label1["id"]))
        dispute = validate_success(resp, expected_status=201)
        assert dispute["status"] == "FILED"

    def test_owning_label_rep_must_be_caller(self, api):
        """PRD §2.1:"When `X-User-Role` is `LabelRep`, `X-User-ID` is the
        `id` of the acting `LabelAccount`; ownership checks on any resource
        that references a label — notably genre-dispute filing, where the
        dispute's `filed_by_label_id` must equal the title's owning
        `label_account_id` and both must equal the caller — compare the
        resource's foreign-key field to `X-User-ID`"

    Design: Corner/rbac/labelrep_dispute_ownership_enforced"""
        label1 = create_label()
        label2 = create_label()
        title = create_title(label1, genre_tag="pop")
        rr = create_recurrent_rule()
        from test_helpers import create_chart
        chart = create_chart(rr["id"], chart_scope="GENRE", genre_tag="country")
        # filed_by_label_id names the owning label, but the CALLER is label2.
        resp = api.create_dispute(
            {"title_product_id": title["id"], "chart_id": chart["id"],
             "filed_by_label_id": label1["id"], "claimed_genre": "country"},
            make_label_rep_headers(label2["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestProviderReportGuards:
    def test_component_kind_must_match_provider_feed(self, api):
        """PRD §3.3:"a `SALES` provider may submit only `SALES`; a
        `STREAM_ON_DEMAND` provider may submit `STREAM_ON_DEMAND_PAID` or
        `STREAM_ON_DEMAND_AD`; a `STREAM_PROGRAMMED` provider may submit only
        `STREAM_PROGRAMMED`; an `AIRPLAY` provider may submit only
        `AIRPLAY`. A mismatch is rejected with `ERR_COMPONENT_KIND_MISMATCH`
        (HTTP 422)"

    Design: Corner/validations/component_kind_must_match_provider_feed"""
        scenario = setup_open_week_scenario()
        provider = create_provider(feed_kind="SALES", territory="DOMESTIC")
        bad = submit_report(provider, scenario["title"]["id"],
                            scenario["week"]["id"],
                            component_kind="STREAM_ON_DEMAND_PAID",
                            quantity=100, file_fingerprint="v1-bad")
        validate_error(bad, ApiErrorId.ERR_COMPONENT_KIND_MISMATCH)
        good = submit_report(provider, scenario["title"]["id"],
                             scenario["week"]["id"],
                             component_kind="SALES", quantity=100,
                             file_fingerprint="v1-good")
        report = validate_success(good, expected_status=201)
        assert report["status"] == "RECEIVED"

    def test_duplicate_file_fingerprint_same_provider_rejected(self, api):
        """PRD §3.3:"A re-delivered batch — the same provider submitting an
        identical `file_fingerprint` — is rejected with
        `ERR_DUPLICATE_REPORT_BATCH` (HTTP 409)"

    Design: Corner/validations/duplicate_file_fingerprint_rejected"""
        scenario = setup_open_week_scenario()
        pv1 = create_provider(feed_kind="SALES", territory="DOMESTIC")
        pv2 = create_provider(feed_kind="SALES", territory="DOMESTIC")
        first = submit_report(pv1, scenario["title"]["id"],
                              scenario["week"]["id"], component_kind="SALES",
                              quantity=10, file_fingerprint="v2-dup")
        validate_success(first, expected_status=201)
        dup = submit_report(pv1, scenario["title"]["id"],
                            scenario["week"]["id"], component_kind="SALES",
                            quantity=10, file_fingerprint="v2-dup")
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_REPORT_BATCH)
        other = submit_report(pv2, scenario["title"]["id"],
                              scenario["week"]["id"], component_kind="SALES",
                              quantity=10, file_fingerprint="v2-dup")
        validate_success(other, expected_status=201)

    def test_report_accept_blocked_when_provider_suspended(self, api):
        """PRD §3.3:"the provider must be `ACTIVE` (a suspended provider
        yields `ERR_ACCOUNT_SUSPENDED`, HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/report_accept_gated_by_provider_status"""
        scenario = setup_open_week_scenario()
        provider = create_provider(feed_kind="STREAM_ON_DEMAND",
                                   territory="DOMESTIC")
        report = submit_report_ok(provider, scenario["title"]["id"],
                                  scenario["week"]["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=5000, file_fingerprint="xp-1")
        get_success_data(api.suspend_provider(provider["id"], ADMIN))
        resp = api.accept_report(report["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED)
        report_after = get_success_data(api.get_report(report["id"], OPS))
        assert report_after["status"] == "RECEIVED", "report unchanged"

    def test_double_accept_rejected_invalid_state(self, api):
        """PRD §3.3:"the report must still be `RECEIVED` (anything else is
        `ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/report_double_accept_invalid_state"""
        scenario = setup_open_week_scenario()
        provider = create_provider(feed_kind="STREAM_ON_DEMAND",
                                   territory="DOMESTIC")
        report = submit_report_ok(provider, scenario["title"]["id"],
                                  scenario["week"]["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=2500, file_fingerprint="s1-a")
        accept_report(report["id"])
        resp = api.accept_report(report["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        report_after = get_success_data(api.get_report(report["id"], OPS))
        assert report_after["status"] == "ACCEPTED"


class TestSaleBatchRules:
    def test_bundle_batch_against_track_rejected(self, api):
        """PRD §3.4:"The title must have `product_kind` `ALBUM`; a batch
        against a track is rejected with `ERR_BUNDLE_CHANNEL_INVALID`
        (HTTP 422)"

    Design: Corner/errors/bundle_channel_invalid_error_triggerable"""
        scenario = setup_open_week_scenario(product_kind="TRACK")
        resp = create_sale_batch(scenario["title"]["id"], channel="D2C",
                                 quantity=1, buyer_key="b1",
                                 chart_week_id=scenario["week"]["id"])
        validate_error(resp, ApiErrorId.ERR_BUNDLE_CHANNEL_INVALID)

    def test_ticket_bundle_never_countable(self, api):
        """PRD §3.4:"`TICKET_BUNDLE` and `MERCH_BUNDLE` batches — albums
        attached to a non-music primary item — are recorded but are never
        countable, contributing zero units regardless of quantity"

    Design: Corner/entities/sale_batch_default_countable_units_computed_ignores_input"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        from test_helpers import create_sale_batch_ok
        batch = create_sale_batch_ok(scenario["title"]["id"],
                                     channel="TICKET_BUNDLE", quantity=50,
                                     buyer_key="buyer-t",
                                     chart_week_id=scenario["week"]["id"])
        assert batch["countable_units"] == 0, (
            "TICKET_BUNDLE is never countable despite quantity 50")


class TestRbac:
    def test_chart_ops_cannot_create_chart(self, api):
        """PRD §2.1:"A request whose authenticated role is not permitted on
        the endpoint, or which fails a declared ownership check, is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)"

    Design: Corner/errors/unauthorized_error_triggerable"""
        rr = create_recurrent_rule()
        resp = api.create_chart(
            {"chart_code": "SNG-ER1", "title": "Singles ER1",
             "chart_kind": "SINGLES", "chart_scope": "MAIN",
             "recurrent_rule_id": rr["id"]},
            OPS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_dataprovider_cannot_review_reports(self, api):
        """PRD §2.1:"A request whose authenticated role is not permitted on
        the endpoint, or which fails a declared ownership check, is rejected
        with `ERR_UNAUTHORIZED` (HTTP 403)"
    PRD §4: report accept is listed under the `ChartOps` role only. Design: Corner/rbac/dataprovider_cannot_review_reports"""
        scenario = setup_open_week_scenario()
        provider = create_provider(feed_kind="STREAM_ON_DEMAND",
                                   territory="DOMESTIC")
        report = submit_report_ok(provider, scenario["title"]["id"],
                                  scenario["week"]["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=2500, file_fingerprint="r1-a")
        resp = api.accept_report(
            report["id"], make_data_provider_headers(provider["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        report_after = get_success_data(api.get_report(report["id"], OPS))
        assert report_after["status"] == "RECEIVED"


class TestEntityCorners:
    def test_create_chart_with_unknown_recurrent_rule_rejected(self, api):
        """PRD §2.9:"Identifiers in nested paths are validated left to
        right ... an unresolvable identifier at any step yields
        `ERR_NOT_FOUND` (HTTP 404)"
    PRD §3.1:"every chart references
        exactly one recurrent rule at creation"

    Design: Corner/entities/create_chart_requires_recurrent_rule_fk"""
        create_recurrent_rule(rule_code="RR-C1")
        resp = api.create_chart(
            {"chart_code": "SNG-C1", "title": "Singles C1",
             "chart_kind": "SINGLES", "chart_scope": "MAIN",
             "recurrent_rule_id": NON_EXISTENT_UUID},
            MANAGER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_genre_chart_requires_genre_tag_main_forbids_it(self, api):
        """PRD §3.1:"A `GENRE`-scoped chart requires a `genre_tag`; a
        `MAIN`-scoped chart must carry no `genre_tag` at all"

    Design: Corner/entities/genre_chart_requires_genre_tag_main_forbids_it"""
        rr = create_recurrent_rule()
        resp_genre = api.create_chart(
            {"chart_code": "GEN-C2", "title": "Genre C2",
             "chart_kind": "SINGLES", "chart_scope": "GENRE",
             "recurrent_rule_id": rr["id"]},
            MANAGER)
        assert resp_genre.status_code >= 400, (
            "GENRE chart without genre_tag must be rejected")
        resp_main = api.create_chart(
            {"chart_code": "MAIN-C2", "title": "Main C2",
             "chart_kind": "SINGLES", "chart_scope": "MAIN",
             "genre_tag": "pop", "recurrent_rule_id": rr["id"]},
            MANAGER)
        assert resp_main.status_code >= 400, (
            "MAIN chart with genre_tag must be rejected")

    def test_get_missing_title_returns_not_found(self, api):
        """PRD §2.9:"an unresolvable identifier at any step yields
        `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/get_missing_title_returns_not_found"""
        resp = api.get_title(NON_EXISTENT_UUID, MANAGER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_titles_paginates_with_envelope_fields(self, api):
        """PRD §2.3:"List responses carry four pagination fields in `meta`:
        `limit`, `offset`, `total_count` (the full count of matching records
        ignoring pagination), and `has_more` (true when records exist beyond
        the returned page)"

    Design: Corner/entities/list_endpoints_paginate_with_envelope_fields"""
        label = create_label()
        create_title(label, upc="UPC-E5-1", title="T1")
        create_title(label, upc="UPC-E5-2", title="T2")
        data, meta = validate_paginated(
            api.list_titles(MANAGER, params={"limit": 1, "offset": 0}))
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert len(data) == 1


class TestInvestigationListing:
    def test_investigations_filtered_by_signal(self, api):
        """PRD §4: `GET /investigations` —"List investigations"with a `signal_id` filter (list endpoints paginate per §2. 3). PRD §3.6:"On escalation an `Investigation` is created in `OPEN` status, bound
        to the signal through its `signal_id`"

    Design: Corner/endpoints/investigations_filtered_by_signal"""
        scenario = setup_open_week_scenario()
        label = scenario["label"]
        t2 = create_title(label, upc="UPC-EP2-2", title="EP2 T2")
        week = scenario["week"]
        from test_helpers import create_signal, escalate_signal_ok
        sg1 = create_signal(scenario["title"]["id"], week["id"],
                            signal_kind="BULK_PURCHASE", evidence="e1")
        sg2 = create_signal(t2["id"], week["id"],
                            signal_kind="BULK_PURCHASE", evidence="e2")
        inv1 = escalate_signal_ok(sg1["id"], "inv-71")
        list1, meta1 = validate_paginated(
            api.list_investigations(OPS, params={"signal_id": sg1["id"]}))
        assert meta1["total_count"] == 1
        assert [i["id"] for i in list1] == [inv1["id"]]
        list2, meta2 = validate_paginated(
            api.list_investigations(OPS, params={"signal_id": sg2["id"]}))
        assert list2 == []
        assert meta2["total_count"] == 0
