"""Custom metric cardinality: threshold detection, incident lifecycle cycle, and
the quarantine cascades (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    CARDINALITY_SOFT_CAP,
    create_custom_metric_series_payload,
    create_rollup_payload,
    set_clock,
    setup_account_with_period_and_team,
    setup_remediated_incident,
    setup_series_with_open_incident,
    setup_verified_incident,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BA, IA


def _open_incident_id(api, account_id):
    incidents = validate_success(
        api.list_cardinality_incidents_flat(BA, params={"status": "OPEN"})
    )
    assert len(incidents) >= 1, "expected at least one OPEN incident"
    return incidents[0]["id"]


class TestThresholdBoundary:
    def test_equality_does_not_open_incident(self, api):
        """PRD §3.7: "At each rollup snapshot, if the series' recomputed
        `cardinality_estimate` is **strictly greater** than the plan's
        `included_custom_metrics` plus the ten-thousand soft cap — equality does not
        trigger — and the series has no `OPEN` incident, the system opens a
        **CardinalityIncident**".

        Design: Corner/calculations/cardinality_threshold_boundary_strictly_greater
        """
        account, period, team = setup_account_with_period_and_team(name="Thr")
        series = validate_success(
            api.create_custom_metric_series(
                account["id"], create_custom_metric_series_payload(team["id"], metric_name="m"), BA
            ),
            expected_status=201,
        )
        # included_custom_metrics=200 and soft cap 10000 -> threshold 10200.
        threshold = 200 + CARDINALITY_SOFT_CAP
        validate_success(
            api.post_rollup(
                account["id"], series["id"],
                create_rollup_payload(cardinality_estimate=threshold), IA,
            )
        )
        incidents = validate_success(api.list_cardinality_incidents(account["id"], BA))
        assert incidents == [], "equality with the threshold must not open an incident"

    def test_one_above_threshold_opens_incident(self, api):
        """PRD §3.7: "if the series' recomputed `cardinality_estimate` is
        **strictly greater** than the plan's `included_custom_metrics` plus the
        ten-thousand soft cap — equality does not trigger — and the series has no
        `OPEN` incident, the system opens a **CardinalityIncident**, recording the
        `opened_at_cardinality` and the `threshold_used` that fired."

        Design: Corner/calculations/cardinality_threshold_boundary_strictly_greater
        """
        account, period, team = setup_account_with_period_and_team(name="Thr+1")
        series = validate_success(
            api.create_custom_metric_series(
                account["id"], create_custom_metric_series_payload(team["id"], metric_name="m"), BA
            ),
            expected_status=201,
        )
        threshold = 200 + CARDINALITY_SOFT_CAP
        validate_success(
            api.post_rollup(
                account["id"], series["id"],
                create_rollup_payload(cardinality_estimate=threshold + 1), IA,
            )
        )
        incidents = validate_success(api.list_cardinality_incidents(account["id"], BA))
        assert len(incidents) == 1
        assert incidents[0]["status"] == "OPEN"
        assert incidents[0]["opened_at_cardinality"] == threshold + 1
        assert incidents[0]["threshold_used"] == threshold


class TestIncidentLifecycle:
    def test_recurrence_loop_verified_back_to_open(self, api):
        """PRD §3.7: "When the series' `cardinality_estimate` has stayed below the
        threshold for two consecutive snapshots, a `REMEDIATED` incident advances
        automatically to `VERIFIED`. If instead the estimate crosses the threshold
        again while the incident is `VERIFIED`, the incident loops back to `OPEN` on
        recurrence and the parent series is quarantined again."

        Design: Difficulty/non_linear_state_machine/cardinality_incident_recurrence_loop
        """
        account, period, team, series, incident = setup_verified_incident(
            name="Cycle Test", opening_estimate=20000, below_threshold=(5000, 4000)
        )
        assert incident["status"] == "VERIFIED"
        validate_success(
            api.post_rollup(
                account["id"], series["id"],
                create_rollup_payload(cardinality_estimate=25000), IA,
            )
        )
        incident = validate_success(
            api.get_cardinality_incident_flat(incident["id"], BA)
        )
        assert incident["status"] == "OPEN"
        series = validate_success(
            api.get_custom_metric_series_flat(series["id"], BA)
        )
        assert series["status"] == "QUARANTINED"

    def test_close_verified_incident_restores_series(self, api):
        """PRD §3.7: "A `BillingAdmin` closes a `VERIFIED` incident, moving it to
        the terminal `CLOSED` state and restoring the parent series to `ACTIVE` so
        it resumes contributing to billable cardinality."

        Design: Difficulty/non_linear_state_machine/cardinality_incident_recurrence_loop
        """
        account, period, team, series, incident = setup_verified_incident(name="Cycle Close")
        closed = validate_success(
            api.close_incident(account["id"], incident["id"], BA)
        )
        assert closed["status"] == "CLOSED"
        series = validate_success(
            api.get_custom_metric_series_flat(series["id"], BA)
        )
        assert series["status"] == "ACTIVE"


class TestRemediateCascade:
    def test_remediate_quarantines_parent_series(self, api):
        """PRD §3.7: "Remediation then requires a non-empty `remediation_note`
        describing the fix; on remediation the incident becomes `REMEDIATED` and two
        cascades fire: the parent series' `status` flips to `QUARANTINED`, and a
        quarantined series stops contributing to the account's billable
        custom-metric cardinality — the `CUSTOM_METRIC` meter accumulator no longer
        counts it."

        Design: Difficulty/transitive_cascade/remediate_cascade_quarantines_series
        """
        account, period, team, series, incident = setup_series_with_open_incident(
            name="Remediate Cascade", metric_name="api.req"
        )
        validate_success(api.triage_incident(account["id"], incident["id"], BA))
        remediated = validate_success(
            api.remediate_incident(
                account["id"], incident["id"],
                {"remediation_note": "Quarantined"}, BA,
            )
        )
        assert remediated["status"] == "REMEDIATED"
        series = validate_success(
            api.get_custom_metric_series_flat(series["id"], BA)
        )
        assert series["status"] == "QUARANTINED"

    def test_remediate_requires_non_empty_note(self, api):
        """PRD §3.7: "Remediation then requires a non-empty `remediation_note`
        describing the fix".
        PRD §2.5: "Entity state preconditions. The action-specific state machine
        precondition must hold ... — otherwise `ERR_INVALID_STATE`." / "Payload
        schema. Required fields present, types correct, enum values valid —
        otherwise `ERR_INVALID_REQUEST`."

        Design: Difficulty/transitive_cascade/remediate_cascade_quarantines_series
        """
        account, period, team, series, incident = setup_series_with_open_incident(
            name="Remediate Note", metric_name="api.req"
        )
        validate_success(api.triage_incident(account["id"], incident["id"], BA))
        resp = api.remediate_incident(
            account["id"], incident["id"], {"remediation_note": ""}, BA
        )
        assert resp.status_code in (400, 409), (
            f"empty remediation_note must be rejected, got {resp.status_code}"
        )
        incident = validate_success(
            api.get_cardinality_incident_flat(incident["id"], BA)
        )
        assert incident["status"] == "TRIAGED"


class TestIncidentBlocksClose:
    def test_close_rejected_while_incident_open(self, api):
        """PRD §3.7: "a billing period cannot be closed while any incident under
        the account is still `OPEN`, unless each such incident is explicitly waived;
        the attempt is rejected with `ERR_OPEN_INCIDENTS_BLOCK_CLOSE`."

        Design: Corner/errors/open_incidents_block_period_close
        """
        account, period, team = setup_account_with_period_and_team(name="Blk")
        series = validate_success(
            api.create_custom_metric_series(
                account["id"], create_custom_metric_series_payload(team["id"], metric_name="m"), BA
            ),
            expected_status=201,
        )
        validate_success(
            api.post_rollup(
                account["id"], series["id"],
                create_rollup_payload(cardinality_estimate=20000), IA,
            )
        )
        set_clock("2026-10-01T00:00:00Z")
        resp = api.close_billing_period(account["id"], period["id"], BA)
        validate_error(resp, ApiErrorId.ERR_OPEN_INCIDENTS_BLOCK_CLOSE.value)
        period = validate_success(
            api.get_billing_period(account["id"], period["id"], BA)
        )
        assert period["status"] == "OPEN"

    def test_close_succeeds_after_incident_closed(self, api):
        """PRD §3.7: "a billing period cannot be closed while any incident under
        the account is still `OPEN`". "A `BillingAdmin` closes a `VERIFIED`
        incident, moving it to the terminal `CLOSED` state".
        PRD §3.9: "a `BillingAdmin` may close it, moving the period from `OPEN` to
        `CLOSED`."

        Design: Corner/errors/open_incidents_block_period_close
        """
        account, period, team, series, incident = setup_verified_incident(name="Blk OK")
        validate_success(api.close_incident(account["id"], incident["id"], BA))
        set_clock("2026-10-01T00:00:00Z")
        closed = validate_success(api.close_billing_period(account["id"], period["id"], BA))
        assert closed["status"] == "CLOSED"
