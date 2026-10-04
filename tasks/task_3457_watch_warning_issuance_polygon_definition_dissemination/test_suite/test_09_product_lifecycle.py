"""Product lifecycle: initial state, terminal cancel, clock expiry, overlap.

Products are born DRAFT, terminate on cancel/expiry/supersession, and their
half-open windows never intersect when they merely touch (PRD §2.5, §3.4,
§3.5, §3.7).
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    cancel_product,
    create_watch_draft,
    create_warning_draft,
    dissipate_storm,
    get_product,
    get_storm,
    issue_product,
    set_clock,
    setup_issued_warning,
    setup_office_with_storm,
    setup_office_with_zone,
    validate_error,
)


def _instant(value):
    """Parse an ISO 8601 UTC instant regardless of fractional-digit rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestInitialState:
    def test_product_created_in_initial_state_draft(self, api):
        """PRD §3.4: "Newly created products sit in `DRAFT` with
        `verified_event_count` at zero and `verification_status` `UNVERIFIED`;
        `issued_at`, `cancelled_at`, `superseded_at`, and `expired_at` are all
        null."
        PRD §3.5: "`coordination_required` is true exactly when that set is
        non-empty."

        Design: Corner/state_machines/product_created_in_initial_state_draft
        """
        bundle = setup_office_with_zone(api)
        draft = create_watch_draft(
            api,
            bundle.office,
            bundle.headers,
            [bundle.zone["id"]],
            hazard_type="SEVERE_THUNDERSTORM",
            product_level="OUTLOOK",
            effective_from="2026-09-03T00:00:00Z",
            expires_at="2026-09-04T00:00:00Z",
        )
        assert draft["status"] == "DRAFT"
        assert draft["version"] == 1
        for field in ("issued_at", "cancelled_at", "superseded_at", "expired_at"):
            assert draft[field] is None, f"{field} is null before any lifecycle event"
        assert draft["coordination_required"] is False, (
            "own-CWA zone, non-HURRICANE hazard: the required-office set is empty"
        )
        assert draft["verified_event_count"] == 0
        assert draft["verification_status"] == "UNVERIFIED"


class TestTerminalCancel:
    def test_cancel_of_cancelled_product_returns_invalid_state(self, api):
        """PRD §3.7: "A forecaster may cancel an `ISSUED` product, moving it to
        the terminal `CANCELLED` status with `cancelled_at` stamped"
        PRD §2.7: "a product moves through `DRAFT`, `PENDING_COORDINATION`,
        and `ISSUED`, terminating in `EXPIRED`, `CANCELLED`, or `SUPERSEDED`."
        PRD §2.8: "Seventh, state-machine preconditions for the invoked
        transition (`ERR_INVALID_PRODUCT_STATE`, `ERR_INVALID_COORDINATION_STATE`,
        `ERR_INVALID_EVENT_STATE`, `ERR_INVALID_EM_ACTION_STATE`,
        `ERR_INVALID_STORM_STATE`, `ERR_RECORD_NOT_SETTLABLE`,
        `ERR_COORDINATION_NOT_ACKED`)."

        Design: Corner/state_machines/cancel_of_cancelled_product_returns_invalid_state
        """
        bundle = setup_issued_warning(api)
        set_clock(api, "2026-09-01T10:05:00Z")
        cancelled = cancel_product(api, bundle.product["id"], bundle.headers)
        assert cancelled["status"] == "CANCELLED"
        assert _instant(cancelled["cancelled_at"]) == _instant("2026-09-01T10:05:00Z")

        resp = api.cancel_product(bundle.product["id"], bundle.headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_PRODUCT_STATE)
        product = get_product(api, bundle.product["id"], bundle.headers)
        assert product["cancelled_at"] == cancelled["cancelled_at"], (
            "the first cancel's timestamp is preserved"
        )


class TestClockDrivenExpiry:
    def test_clock_advance_expires_warning_at_exact_expiry_instant(self, api):
        """PRD §3.7: "Expiry arrives with the clock: when an advance carries
        the logical time to or past a product's `expires_at`, the product moves
        from `ISSUED` to `EXPIRED` with `expired_at` set equal to `expires_at`,
        its `window_end` recomputes, and its `QUEUED` records are withdrawn
        during the same advance."
        PRD §2.5: "Time windows are half-open throughout: the start instant is
        included, the end instant is excluded."

        Design: Corner/state_machines/clock_advance_expires_warning_at_exact_expiry_instant
        """
        bundle = setup_issued_warning(
            api,
            issue_clock="2026-09-01T09:30:00Z",
            expires_at="2026-09-01T10:00:00Z",
        )
        set_clock(api, "2026-09-01T09:59:59Z")
        product = get_product(api, bundle.product["id"], bundle.headers)
        assert product["status"] == "ISSUED", "one second before expiry the product is live"

        set_clock(api, "2026-09-01T10:00:00Z")
        product = get_product(api, bundle.product["id"], bundle.headers)
        assert product["status"] == "EXPIRED", "reaching expires_at expires the product"
        assert product["expired_at"] == product["expires_at"], (
            "expired_at is set equal to expires_at"
        )
        assert product["window_end"] == product["expires_at"]


class TestDissipatedStormGate:
    def test_issue_against_dissipated_storm_returns_invalid_storm_state(self, api):
        """PRD §3.3: "Dissipation has teeth: a `DISSIPATED` storm can no longer
        anchor a warning or advisory, so a `DRAFT` product linked to one fails
        at issuance with `ERR_INVALID_STORM_STATE`"

        Design: Corner/state_machines/issue_against_dissipated_storm_returns_invalid_storm_state
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 60}
        )
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T00:45:00Z"
        )
        storm = dissipate_storm(api, bundle.storm["id"], bundle.headers)
        assert storm["status"] == "DISSIPATED"
        assert storm["dissipated_at"] is not None

        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STORM_STATE)
        assert get_product(api, draft["id"], bundle.headers)["status"] == "DRAFT"
        assert get_storm(api, bundle.storm["id"], bundle.headers)["status"] == "DISSIPATED"


class TestWatchWindowOverlap:
    def _three_watches(self, api):
        bundle = setup_office_with_zone(api)
        set_clock(api, "2026-09-01T09:00:00Z")
        watches = [
            create_watch_draft(
                api, bundle.office, bundle.headers, [bundle.zone["id"]],
                hazard_type="WINTER_STORM", effective_from=start, expires_at=end,
            )
            for start, end in (
                ("2026-09-01T10:00:00Z", "2026-09-01T12:00:00Z"),
                ("2026-09-01T12:00:00Z", "2026-09-01T14:00:00Z"),
                ("2026-09-01T11:00:00Z", "2026-09-01T13:00:00Z"),
            )
        ]
        return bundle, watches

    def test_adjacent_watch_windows_do_not_conflict(self, api):
        """PRD §3.5: "Two windows that merely touch at a single instant, this
        product's start equal to the other's expiration, do not conflict."
        PRD §2.5: "Time windows are half-open throughout: the start instant is
        included, the end instant is excluded."

        Design: Difficulty/resource_temporal_overlap/watch_windows_half_open_adjacency_allowed_overlap_rejected
        """
        bundle, (w1, w2, _w3) = self._three_watches(api)
        assert issue_product(api, w1["id"], bundle.headers)["status"] == "ISSUED"
        product = issue_product(api, w2["id"], bundle.headers)
        assert product["status"] == "ISSUED", (
            "W2's effective_from == W1's expires_at: zero-length intersection is not a conflict"
        )

    def test_straddling_watch_window_conflicts(self, api):
        """PRD §3.5: "Issuance is rejected with `ERR_PRODUCT_OVERLAP_CONFLICT`
        when a different product of the same issuing office, same hazard, and
        same level is currently `ISSUED`, is not this product's supersede
        target, has a half-open window intersecting this one — this window's
        start strictly earlier than the other's end, and the other's start
        strictly earlier than this window's end — and shares at least one
        resolved zone."

        Design: Difficulty/resource_temporal_overlap/watch_windows_half_open_adjacency_allowed_overlap_rejected
        """
        bundle, (w1, w2, w3) = self._three_watches(api)
        issue_product(api, w1["id"], bundle.headers)
        issue_product(api, w2["id"], bundle.headers)
        resp = api.issue_product(
            w3["id"], {"expected_product_version": w3["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_OVERLAP_CONFLICT)
        assert get_product(api, w3["id"], bundle.headers)["status"] == "DRAFT"
