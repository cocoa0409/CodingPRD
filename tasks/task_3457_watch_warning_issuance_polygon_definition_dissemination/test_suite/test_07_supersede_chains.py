"""Supersede chains: cascades, chain-shape rules, handoff coverage.

Issuing a replacement product supersedes its target atomically, withdrawing
the target's queued records and closing its verification window at the
replacement's issued_at (PRD §3.5, §3.7, §3.8).
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    cancel_product,
    create_alert_channel,
    create_and_confirm_event,
    create_storm,
    create_warning_draft,
    create_watch_draft,
    get_product,
    issue_product,
    list_coordination_requests,
    list_records,
    respond_to_request,
    set_clock,
    setup_coordinated_offices,
    setup_issued_warning,
    setup_office_with_storm,
    square_polygon,
    submit_coordination,
    validate_error,
)

LEFT_HALF = square_polygon(lon_max=0.05)


def _instant(value):
    """Parse an ISO 8601 UTC instant regardless of fractional-digit rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _setup_issued_watch_ready_to_upgrade(api):
    """Two coordinated offices, EAS + DATA_FEED channels, an ISSUED SEVERE
    watch over both CWAs (issued at 09:00), and a UPGRADE WARNING draft
    superseding it."""
    bundle = setup_coordinated_offices(api)
    create_alert_channel(api, name="EAS-1")
    create_alert_channel(
        api,
        name="DF-1",
        channel_type="DATA_FEED",
        supports_levels=["WATCH", "ADVISORY", "WARNING"],
        max_message_chars=4000,
    )
    set_clock(api, "2026-09-01T09:00:00Z")
    watch = create_watch_draft(
        api,
        bundle.office_a,
        bundle.headers_a,
        [bundle.zone_a["id"], bundle.zone_b["id"]],
        hazard_type="SEVERE_THUNDERSTORM",
        effective_from="2026-09-01T09:30:00Z",
        expires_at="2026-09-01T12:00:00Z",
    )
    submit_coordination(api, watch["id"], bundle.headers_a)
    for request in list_coordination_requests(api, watch["id"], bundle.headers_a):
        respond_to_request(api, request["id"], bundle.headers_b, "ACKNOWLEDGED")
    bundle.watch = issue_product(api, watch["id"], bundle.headers_a)
    bundle.storm = create_storm(
        api, bundle.office_a["id"], bundle.headers_a, "SEVERE_THUNDERSTORM", max_wind_mph=65
    )
    bundle.upgrade = create_warning_draft(
        api,
        bundle.office_a,
        bundle.headers_a,
        bundle.storm,
        polygon=LEFT_HALF,
        expires_at="2026-09-01T10:30:00Z",
        supersedes_product_id=bundle.watch["id"],
        supersede_reason="UPGRADE",
    )
    return bundle


class TestSupersedeCascade:
    def test_upgrade_issue_supersedes_watch_and_withdraws_its_records(self, api):
        """PRD §3.5: "When the product supersedes another, the prior product
        moves from `ISSUED` to `SUPERSEDED` with `superseded_at` set to the new
        product's `issued_at` and its own `version` incremented."
        PRD §3.7: "when a replacement product issues (§3.5), the superseded
        product's `QUEUED` records are likewise withdrawn"

        Design: Difficulty/transitive_cascade/supersede_cascade_withdraws_prior_records
        """
        bundle = _setup_issued_watch_ready_to_upgrade(api)
        upgrade = issue_product(api, bundle.upgrade["id"], bundle.headers_a)
        assert upgrade["status"] == "ISSUED"
        assert _instant(upgrade["issued_at"]) == _instant("2026-09-01T09:00:00Z")

        watch = get_product(api, bundle.watch["id"], bundle.headers_a)
        assert watch["status"] == "SUPERSEDED"
        assert watch["superseded_at"] == upgrade["issued_at"]

        prior_records = list_records(api, bundle.watch["id"], bundle.headers_a)
        assert len(prior_records) == 2, "EAS-1 and DF-1 both carried the WATCH"
        assert all(r["status"] == "WITHDRAWN" for r in prior_records), (
            "withdrawn by the supersession without any clock dispatch"
        )
        new_records = list_records(api, upgrade["id"], bundle.headers_a)
        assert len(new_records) == 2, "both channels carry WARNING too"
        assert all(r["status"] == "QUEUED" for r in new_records)

    def test_superseded_watch_window_closes_at_upgrade_issued_at(self, api):
        """PRD §3.4: "The derived `window_end` is the earliest non-null value
        among `cancelled_at`, `superseded_at`, and `expires_at`; it recomputes
        whenever one of those fields is set"
        PRD §3.5: "the prior product moves from `ISSUED` to `SUPERSEDED` with
        `superseded_at` set to the new product's `issued_at`"

        Design: Difficulty/transitive_cascade/supersede_cascade_withdraws_prior_records
        """
        bundle = _setup_issued_watch_ready_to_upgrade(api)
        upgrade = issue_product(api, bundle.upgrade["id"], bundle.headers_a)
        watch = get_product(api, bundle.watch["id"], bundle.headers_a)
        assert watch["window_end"] == upgrade["issued_at"], (
            "superseded_at beats the watch's 12:00 expires_at"
        )
        assert _instant(watch["window_end"]) == _instant("2026-09-01T09:00:00Z")
        assert _instant(watch["superseded_at"]) == _instant("2026-09-01T09:00:00Z")


class TestSupersedeChainShape:
    def test_invalid_supersede_chain_shapes_rejected(self, api):
        """PRD §3.5: "An `UPGRADE` chain must run from a `WATCH` to a `WARNING`
        of the same hazard; `CONTINUATION` and `CORRECTION` chains require the
        same level and the same hazard; and a chain whose prior product is
        already past its `expires_at` is invalid — any violation is
        `ERR_INVALID_SUPERSEDE_CHAIN`."

        Design: Corner/errors/invalid_supersede_chain_shapes_rejected
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 60}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        w1 = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm,
            polygon=LEFT_HALF, expires_at="2026-09-01T10:45:00Z",
        )
        w1 = issue_product(api, w1["id"], bundle.headers)

        w2 = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm,
            polygon=square_polygon(lon_min=0.05), expires_at="2026-09-01T10:50:00Z",
            supersedes_product_id=w1["id"], supersede_reason="UPGRADE",
        )
        resp = api.issue_product(
            w2["id"], {"expected_product_version": w2["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSEDE_CHAIN)

        w3 = create_watch_draft(
            api, bundle.office, bundle.headers, [bundle.zone["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            effective_from="2026-09-01T10:45:00Z", expires_at="2026-09-01T14:00:00Z",
            supersedes_product_id=w1["id"], supersede_reason="CONTINUATION",
        )
        resp = api.issue_product(
            w3["id"], {"expected_product_version": w3["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_SUPERSEDE_CHAIN)
        assert get_product(api, w1["id"], bundle.headers)["status"] == "ISSUED", (
            "neither malformed chain superseded the live warning"
        )


class TestContinuationOfCancelledTarget:
    def _setup(self, api):
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 60}
        )
        set_clock(api, "2026-09-01T10:00:00Z")
        w1 = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T10:45:00Z"
        )
        w1 = issue_product(api, w1["id"], bundle.headers)
        cancel_product(api, w1["id"], bundle.headers)
        w2 = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm,
            effective_from="2026-09-01T08:00:00Z",
            expires_at="2026-09-01T09:00:00Z",
            supersedes_product_id=w1["id"], supersede_reason="CONTINUATION",
        )
        bundle.w1 = w1
        bundle.w2 = w2
        return bundle

    def test_continuation_of_cancelled_target_reports_state_error(self, api):
        """PRD §3.5: "Separately, at the moment of issuance the supersede
        target must currently be `ISSUED`; targeting a product that has left
        that state fails with `ERR_INVALID_PRODUCT_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/continuation_of_cancelled_with_bad_window_reports_state_error
        """
        bundle = self._setup(api)
        resp = api.issue_product(
            bundle.w2["id"], {"expected_product_version": bundle.w2["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PRODUCT_STATE)
        assert get_product(api, bundle.w2["id"], bundle.headers)["status"] == "DRAFT"
        assert get_product(api, bundle.w1["id"], bundle.headers)["status"] == "CANCELLED"

    def test_state_error_precedes_temporal_window_error(self, api):
        """PRD §2.8: "a request that would fail at several tiers is always
        rejected with the error from the earliest applicable tier"
        PRD §2.8: "Seventh, state-machine preconditions for the invoked
        transition (`ERR_INVALID_PRODUCT_STATE`, `ERR_INVALID_COORDINATION_STATE`,
        `ERR_INVALID_EVENT_STATE`, `ERR_INVALID_EM_ACTION_STATE`,
        `ERR_INVALID_STORM_STATE`, `ERR_RECORD_NOT_SETTLABLE`,
        `ERR_COORDINATION_NOT_ACKED`)."
        PRD §2.8: "Ninth, temporal window checks (`ERR_WINDOW_INVALID`,
        `ERR_DURATION_OUT_OF_RANGE`, `ERR_EFFECTIVE_IN_PAST`)."

        Design: Difficulty/priority_pair_validation_conflict/continuation_of_cancelled_with_bad_window_reports_state_error
        """
        bundle = self._setup(api)
        resp = api.issue_product(
            bundle.w2["id"], {"expected_product_version": bundle.w2["version"]}, bundle.headers
        )
        err = validate_error(resp, ApiErrorId.ERR_INVALID_PRODUCT_STATE)
        assert err["error_id"] != "ERR_WINDOW_INVALID", (
            "the continuation's expires_at 09:00 also precedes the 10:00 clock, "
            "but the state tier reports first"
        )


class TestSupersedeHandoffCoverage:
    def _setup_handoff(self, api):
        bundle = setup_issued_warning(
            api, polygon=LEFT_HALF, expires_at="2026-09-01T10:45:00Z"
        )
        set_clock(api, "2026-09-01T10:15:00Z")
        w2 = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm,
            polygon=LEFT_HALF, expires_at="2026-09-01T11:15:00Z",
            supersedes_product_id=bundle.product["id"], supersede_reason="CONTINUATION",
        )
        bundle.w2 = issue_product(api, w2["id"], bundle.headers)
        bundle.event = create_and_confirm_event(
            api, bundle.zone["id"], "SEVERE_THUNDERSTORM",
            "2026-09-01T10:15:00Z", 0.05, 0.02, "60mph",
        )
        return bundle

    def test_supersede_handoff_assigns_instant_to_replacement_only(self, api):
        """PRD §3.8: "a confirmed event matches a product when their hazards
        agree, the product is a `WARNING`, the product's `issued_at` is no
        later than the event's `observed_at`, the `observed_at` is strictly
        earlier than the product's `window_end`, and the observation point
        lies inside the product's polygon"
        PRD §3.5: "the prior product moves from `ISSUED` to `SUPERSEDED` with
        `superseded_at` set to the new product's `issued_at`"

        Design: Difficulty/compensating_invariant/supersede_chain_preserves_single_coverage_at_handoff
        """
        bundle = self._setup_handoff(api)
        w1 = get_product(api, bundle.product["id"], bundle.headers)
        assert w1["window_end"] == bundle.w2["issued_at"], (
            "the supersession closed W1's window at the handoff instant"
        )
        assert _instant(w1["window_end"]) == _instant("2026-09-01T10:15:00Z")
        assert bundle.event["matched_product_ids"] == [bundle.w2["id"]], (
            "the half-open [issued_at, window_end) assigns 10:15:00Z to W2 alone"
        )

    def test_handoff_event_verifies_replacement_not_prior(self, api):
        """PRD §3.8: "Every matched product has its `verified_event_count`
        increased by one, and a product whose count thereby leaves zero flips
        its `verification_status` from `UNVERIFIED` to `VERIFIED`."

        Design: Difficulty/compensating_invariant/supersede_chain_preserves_single_coverage_at_handoff
        """
        bundle = self._setup_handoff(api)
        w1 = get_product(api, bundle.product["id"], bundle.headers)
        w2 = get_product(api, bundle.w2["id"], bundle.headers)
        assert w1["verified_event_count"] == 0
        assert w1["verification_status"] == "UNVERIFIED"
        assert w2["verified_event_count"] == 1
        assert w2["verification_status"] == "VERIFIED"
