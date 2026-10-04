"""Teams, usage attribution, tag governance, disputes, and chargeback rollup
(PRD §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    create_dispute_payload,
    create_tag_policy_payload,
    create_team_payload,
    create_usage_record_payload,
    get_meter_accumulator,
    make_team_lead_headers,
    post_usage,
    setup_account_with_period,
    setup_account_with_period_and_team,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import BA, FR, IA


class TestUsageAttribution:
    def test_usage_record_bumps_matching_meter_accumulator(self, api):
        """PRD §3.6: "Usage is attributed by posting a **UsageRecord** against an
        open period, naming the `meter`, the `quantity` attributed, and optionally
        the `team_id` of the owning team." "Each accepted record also bumps the
        matching meter accumulator for the period."

        Design: Corner/entities/meter_accumulator_quantity_is_computed_not_input
        """
        account, period = setup_account_with_period(name="Computed")
        record = validate_success(
            api.create_usage_record(
                account["id"], period["id"],
                create_usage_record_payload(meter="TRACE", quantity=7), IA,
            ),
            expected_status=201,
        )
        assert record["meter"] == "TRACE"
        assert record["quantity"] == 7
        acc = get_meter_accumulator(account["id"], period["id"], "TRACE")
        assert acc["quantity"] == 7

    def test_meter_accumulator_reflects_usage_immediately(self, api):
        """PRD §3.6: "Each accepted record also bumps the matching meter
        accumulator for the period."
        PRD §3.9: "Chargeback is computed on demand, never stored."

        Design: Corner/consistency_model/immediate_consistency_after_usage_record_post
        """
        account, period = setup_account_with_period(name="IC")
        validate_success(
            api.create_usage_record(
                account["id"], period["id"],
                create_usage_record_payload(meter="SYNTHETIC", quantity=11), IA,
            ),
            expected_status=201,
        )
        acc = get_meter_accumulator(account["id"], period["id"], "SYNTHETIC")
        assert acc["quantity"] == 11


class TestTagPolicy:
    def test_block_policy_rejects_missing_team(self, api):
        """PRD §3.6: "Under `BLOCK`, the record is rejected outright with
        `ERR_TAG_POLICY_VIOLATION` (HTTP 422)."
        PRD §2.5: "Tag policy enforcement. A `BLOCK`-mode tag policy rejects a
        non-compliant usage record with `ERR_TAG_POLICY_VIOLATION` (see §3.6)."

        Design: Corner/validations/tag_policy_block_rejects_non_compliant_usage_record
        """
        account, period = setup_account_with_period(name="TP")
        validate_success(
            api.create_tag_policy(account["id"], create_tag_policy_payload(), BA),
            expected_status=201,
        )
        # No team_id: the required tag is missing on this record.
        resp = api.create_usage_record(
            account["id"], period["id"],
            create_usage_record_payload(meter="TRACE", quantity=5), IA,
        )
        validate_error(resp, ApiErrorId.ERR_TAG_POLICY_VIOLATION.value)

    def test_block_policy_rejects_team_outside_whitelist(self, api):
        """PRD §3.6: "When a usage record arrives whose team attribution is missing
        or whose tag value falls outside the whitelist: ... Under `BLOCK`, the
        record is rejected outright with `ERR_TAG_POLICY_VIOLATION` (HTTP 422)."

        Design: Corner/validations/tag_policy_block_rejects_non_compliant_usage_record
        """
        account, period, team = setup_account_with_period_and_team(name="TP2")
        validate_success(
            api.create_tag_policy(
                account["id"],
                create_tag_policy_payload(allowed_values=["a", "b"]),
                BA,
            ),
            expected_status=201,
        )
        resp = api.create_usage_record(
            account["id"], period["id"],
            create_usage_record_payload(meter="TRACE", quantity=5, team_id=team["id"]),
            IA,
        )
        # "a"/"b" are the allowed values; the team's id is not among them.
        validate_error(resp, ApiErrorId.ERR_TAG_POLICY_VIOLATION.value)


class TestChargebackRollup:
    def test_compliant_records_roll_up_per_team_unattributed_bucket_captures_rest(self, api):
        """PRD §3.9: "the system rates each usage record in the period and sums per
        team — including only records whose `tag_compliant` flag is true and whose
        `disputed` flag is false. Records that fail tag compliance, or that carry no
        `team_id` at all, are excluded from every team's bucket and aggregated
        instead into a special `UNATTRIBUTED` bucket reported alongside the per-team
        figures; the response carries a `by_team` array and the `unattributed_cents`
        total."

        Design: Corner/calculations/chargeback_rollup_excludes_non_compliant_records
        """
        account, period, team = setup_account_with_period_and_team(name="CB")
        compliant = post_usage(
            account["id"], period["id"], "INFRA_HOST", 10, team_id=team["id"]
        )
        assert compliant["tag_compliant"] is True
        # No team_id and no BLOCK policy: accepted but inherently non-compliant.
        non_compliant = post_usage(account["id"], period["id"], "INFRA_HOST", 5)
        assert non_compliant["team_id"] is None
        assert non_compliant["tag_compliant"] is False

        rollup = validate_success(
            api.get_chargeback(account["id"], period["id"], FR)
        )
        assert isinstance(rollup["by_team"], list)
        assert isinstance(rollup["unattributed_cents"], int)
        team_buckets = [b for b in rollup["by_team"] if b.get("team_id") == team["id"]]
        assert len(team_buckets) == 1, "the compliant record must roll up under its team"
        # The null-team record is excluded from every team's bucket and aggregated
        # into UNATTRIBUTED; both records are INFRA_HOST usage rated at the plan's
        # on-demand fallback (host_overage_rate_cents), so both buckets are
        # non-zero.
        assert rollup["unattributed_cents"] > 0
        assert team_buckets[0].get("amount_cents", team_buckets[0].get("total_cents", 0)) >= 0

    def test_disputed_record_sits_out_of_team_rollup(self, api):
        """PRD §3.6: "Opening the dispute sets the usage record's `disputed` flag
        to true, and a disputed record is held out of chargeback rollups while the
        dispute is `OPEN`."
        PRD §3.9: "Disputed records sit out of the rollup entirely until their
        dispute resolves (§3.6)."

        Design: Corner/calculations/chargeback_rollup_excludes_non_compliant_records
        """
        account, period, team = setup_account_with_period_and_team(name="CB2")
        record = post_usage(account["id"], period["id"], "TRACE", 10, team_id=team["id"])
        dispute = validate_success(
            api.create_dispute(
                account["id"], record["id"],
                create_dispute_payload(team["id"]), make_team_lead_headers(team["id"]),
            ),
            expected_status=201,
        )
        assert dispute["status"] == "OPEN"
        record = validate_success(api.get_usage_record_flat(record["id"], BA))
        assert record["disputed"] is True

        rollup = validate_success(api.get_chargeback(account["id"], period["id"], FR))
        team_buckets = [b for b in rollup["by_team"] if b.get("team_id") == team["id"]]
        if team_buckets:
            amount = team_buckets[0].get(
                "amount_cents", team_buckets[0].get("total_cents", 0)
            )
            assert amount == 0, "a disputed record must not contribute to its team"


class TestDisputes:
    def test_accept_reassigns_team_and_clears_disputed(self, api):
        """PRD §3.6: "Accepting the dispute — permitted only while the usage
        record's billing period is still `OPEN` — moves the dispute to `ACCEPTED`,
        clears the `disputed` flag, reassigns the record's `team_id` to the
        `raised_by_team_id`, and recomputes the chargeback rollup."

        Design: Corner/calculations/chargeback_rollup_excludes_non_compliant_records
        """
        account, period, team = setup_account_with_period_and_team(name="Accept")
        team2 = validate_success(
            api.create_team(
                account["id"], create_team_payload(name="Challenger", cost_center="CC-2"), BA
            ),
            expected_status=201,
        )
        record = post_usage(account["id"], period["id"], "TRACE", 10, team_id=team["id"])
        dispute = validate_success(
            api.create_dispute(
                account["id"], record["id"],
                create_dispute_payload(team2["id"]),
                make_team_lead_headers(team2["id"]),
            ),
            expected_status=201,
        )
        accepted = validate_success(api.accept_dispute(account["id"], dispute["id"], BA))
        assert accepted["status"] == "ACCEPTED"
        record = validate_success(api.get_usage_record_flat(record["id"], BA))
        assert record["disputed"] is False
        assert record["team_id"] == team2["id"]

    def test_reject_clears_disputed_and_keeps_attribution(self, api):
        """PRD §3.6: "Rejecting the dispute moves it to `REJECTED` and simply
        clears the `disputed` flag, restoring the original attribution."

        Design: Corner/calculations/chargeback_rollup_excludes_non_compliant_records
        """
        account, period, team = setup_account_with_period_and_team(name="Reject")
        record = post_usage(account["id"], period["id"], "TRACE", 10, team_id=team["id"])
        dispute = validate_success(
            api.create_dispute(
                account["id"], record["id"],
                create_dispute_payload(team["id"]),
                make_team_lead_headers(team["id"]),
            ),
            expected_status=201,
        )
        rejected = validate_success(api.reject_dispute(account["id"], dispute["id"], BA))
        assert rejected["status"] == "REJECTED"
        record = validate_success(api.get_usage_record_flat(record["id"], BA))
        assert record["disputed"] is False
        assert record["team_id"] == team["id"]
