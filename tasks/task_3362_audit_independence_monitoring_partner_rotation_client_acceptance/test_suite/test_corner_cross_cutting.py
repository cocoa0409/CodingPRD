"""Breadth claims that cut across resources: concurrency, roll-ups and
read-after-write visibility."""

from test_helpers import (
    ApiErrorId,
    fixtures,
    get_client_data,
    get_engagement_data,
    get_service_data,
    validate_error,
)


class TestAssignmentConcurrencyGuard:
    """The staffing write is guarded by the engagement version."""

    def test_stale_snapshot_is_rejected_on_assignment_create(self, api):
        """PRD §2.8: "If the two differ — because a sibling assignment, an
        acceptance decision, an independence recompute or any other mutation
        advanced the engagement since the client last read it — the write is
        rejected with `ERR_STALE_VERSION` and HTTP status 412, and nothing is
        created."

        Design: Corner/cross_cutting_layers/stale_engagement_version_on_assignment_create_returns_412
        """
        world = fixtures.scenario_stale_assignment_version(api)
        engagement_id = world["engagement"]["id"]
        assert world["current_version"] == world["stale_version"] + 1

        stale = fixtures.staff(
            api, engagement_id, world["reviewer"]["id"], "EQ_REVIEWER",
            "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z",
            expected_version=world["stale_version"], ep_headers=world["ep_headers"],
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

        retry = fixtures.staff_ok(
            api, engagement_id, world["reviewer"]["id"], "EQ_REVIEWER",
            "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z",
            expected_version=world["current_version"], ep_headers=world["ep_headers"],
        )
        assert retry["status"] == "ACTIVE"

    def test_only_the_successful_assignments_contribute_workload(self, api):
        """PRD §2.8: "If the values match, the write proceeds and, on success,
        the engagement's `version` advances by 1 as part of the same
        operation."

        Design: Corner/cross_cutting_layers/stale_engagement_version_on_assignment_create_returns_412
        """
        world = fixtures.scenario_stale_assignment_version(api)
        engagement_id = world["engagement"]["id"]

        fixtures.staff(
            api, engagement_id, world["reviewer"]["id"], "EQ_REVIEWER",
            "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z",
            expected_version=world["stale_version"], ep_headers=world["ep_headers"],
        )
        fixtures.staff_ok(
            api, engagement_id, world["reviewer"]["id"], "EQ_REVIEWER",
            "2026-10-01T00:00:00Z", "2027-10-01T00:00:00Z",
            expected_version=world["current_version"], ep_headers=world["ep_headers"],
        )

        engagement = get_engagement_data(api, engagement_id)
        # LEAD_PARTNER 40 + EQ_REVIEWER 20 on low-tier engagements.
        assert engagement["assigned_workload_points"] == 60
        assert engagement["version"] == world["current_version"] + 1


class TestFindingConcurrencyGuard:
    """The finding write carries its own guard on the same parent."""

    def test_stale_snapshot_is_rejected_on_finding_create(self, api):
        """PRD §3.5: "the body must carry `expected_engagement_version`
        matching the engagement's current `version`, and a stale snapshot is
        rejected with `ERR_STALE_VERSION` and HTTP 412 rather than silently
        attaching the finding to an engagement the caller has not observed."

        Design: Corner/cross_cutting_layers/stale_engagement_version_on_finding_create_returns_412
        """
        world = fixtures.scenario_stale_finding_version(api)

        stale = fixtures.raise_finding(
            api, world["professional"]["id"], world["engagement"]["id"],
            expected_version=world["stale_version"], origin="INSPECTION",
            origin_ref_id="insp-mo-2", finding_type="WORKLOAD_LIMIT",
            severity="LOW", discovered_on="2026-09-16T00:00:00Z",
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_the_rejected_finding_contributes_nothing(self, api):
        """PRD §3.5: "Raising a finding immediately recomputes the engagement's
        independence posture and the client's `open_finding_count`, the counter
        of that client's findings that are not yet `CLOSED`."

        Design: Corner/cross_cutting_layers/stale_engagement_version_on_finding_create_returns_412
        """
        world = fixtures.scenario_stale_finding_version(api)

        fixtures.raise_finding(
            api, world["professional"]["id"], world["engagement"]["id"],
            expected_version=world["stale_version"], origin="INSPECTION",
            origin_ref_id="insp-mo-2", finding_type="WORKLOAD_LIMIT",
            severity="LOW", discovered_on="2026-09-16T00:00:00Z",
        )
        retry = fixtures.raise_finding_ok(
            api, world["professional"]["id"], world["engagement"]["id"],
            expected_version=world["current_version"], origin="INSPECTION",
            origin_ref_id="insp-mo-2", finding_type="WORKLOAD_LIMIT",
            severity="LOW", discovered_on="2026-09-16T00:00:00Z",
        )
        assert retry["status"] == "OPEN"

        client = get_client_data(api, world["client"]["id"])
        assert client["open_finding_count"] == 2


class TestClientAggregateRollUp:
    """The client posture is the worst posture among its engagements."""

    def test_client_roll_up_follows_the_worst_engagement(self, api):
        """PRD §2.6: "`Client.aggregate_independence_status` is `FROZEN` when
        any engagement of the client is `FROZEN`, `RESTRICTED` when none is
        `FROZEN` but at least one is `RESTRICTED`, and `CLEAR` otherwise."

        Design: Corner/cross_cutting_layers/client_aggregate_status_tracks_the_worst_engagement
        """
        world = fixtures.scenario_two_engagement_client(api)
        assert world["client"]["aggregate_independence_status"] == "CLEAR"
        assert world["client"]["open_finding_count"] == 0

        fixtures.raise_finding_ok(
            api, world["professional"]["id"], world["first"]["id"],
            origin="DECLARATION", origin_ref_id="decl-fx-1",
            finding_type="EMPLOYMENT_RELATIONSHIP", severity="HIGH",
            discovered_on="2026-09-20T00:00:00Z",
        )

        client = get_client_data(api, world["client"]["id"])
        first = get_engagement_data(api, world["first"]["id"])
        second = get_engagement_data(api, world["second"]["id"])
        assert first["independence_status"] == "RESTRICTED"
        assert second["independence_status"] == "CLEAR"
        assert client["aggregate_independence_status"] == "RESTRICTED"
        assert client["open_finding_count"] == 1

    def test_client_roll_up_returns_to_clear_when_the_finding_closes(self, api):
        """PRD §2.6: "a client whose aggregate posture becomes `FROZEN` moves
        from `ACTIVE` to `SUSPENDED`, and it returns to `ACTIVE` once no
        engagement of the client is `FROZEN`."

        Design: Corner/cross_cutting_layers/client_aggregate_status_tracks_the_worst_engagement
        """
        world = fixtures.scenario_two_engagement_client(api)
        status_before = get_client_data(api, world["client"]["id"])["status"]

        finding = fixtures.raise_finding_ok(
            api, world["professional"]["id"], world["first"]["id"],
            origin="DECLARATION", origin_ref_id="decl-fx-1",
            finding_type="EMPLOYMENT_RELATIONSHIP", severity="HIGH",
            discovered_on="2026-09-20T00:00:00Z",
        )
        fixtures.finding_transition_ok(api, finding["id"], "START_REMEDIATION")
        fixtures.finding_transition_ok(api, finding["id"], "SUBMIT_FOR_RETEST")
        fixtures.finding_transition_ok(api, finding["id"], "PASS_RETEST")

        client = get_client_data(api, world["client"]["id"])
        assert client["aggregate_independence_status"] == "CLEAR"
        assert client["open_finding_count"] == 0
        # A restricted posture never suspends the client.
        assert client["status"] == status_before


class TestReadAfterWriteConsistency:
    """Every derived value is visible in the write's own response."""

    def test_approval_response_already_carries_the_rounded_fee(self, api):
        """PRD §4: "every modification returns the updated resource object, so a
        caller never needs a follow-up read to observe the effect of a write."

        Design: Corner/consistency_model/immediate_consistency_read_after_write_returns_new_value
        """
        world = fixtures.scenario_immediate_consistency(api)

        approved = fixtures.service_transition_ok(
            api, world["service"]["id"], "APPROVE", committee_resolution_ref="AC-2026-1001"
        )
        assert approved["approved_fee_cents"] == 250100
        assert approved["status"] == "APPROVED"

    def test_the_client_read_immediately_reflects_the_approval(self, api):
        """PRD §3.6: "the client's `naf_approved_fee_cents` is recomputed
        through the fee pool rule, the client's `aggregate_independence_status`
        is recomputed, every engagement belonging to that client has its
        independence posture recomputed, and the client's `version` advances by
        1."

        Design: Corner/consistency_model/immediate_consistency_read_after_write_returns_new_value
        """
        world = fixtures.scenario_immediate_consistency(api)
        version_before = world["client"]["version"]

        fixtures.service_transition_ok(
            api, world["service"]["id"], "APPROVE", committee_resolution_ref="AC-2026-1001"
        )

        client = get_client_data(api, world["client"]["id"])
        service = get_service_data(api, world["service"]["id"])
        assert client["naf_approved_fee_cents"] == 250100
        assert client["version"] == version_before + 1
        assert service["approved_on"] is not None
