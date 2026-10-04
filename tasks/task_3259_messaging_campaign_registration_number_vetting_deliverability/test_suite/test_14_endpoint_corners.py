"""Endpoint corners: the ops-run counters and the filtered charge ledger
read.
"""

from test_helpers.fixtures import (
    charges,
    create_account,
    create_approved_campaign,
    create_verified_brand,
    queued_message_stack,
    run_ops,
    set_clock,
)
from test_helpers.constants import (
    CHARGE_CAMPAIGN_RECURRING,
    CHARGE_CAMPAIGN_REGISTRATION,
    REFERENCE_CAMPAIGN,
)
from test_helpers.assertions import charges_for


class TestRunOpsCounters:
    def test_first_run_reports_index_one_and_one_dequeued_message(self, client):
        """PRD section 3.1: "Each ops run stamps a new OpsRun record whose
        run_index is a monotone per-account counter starting at 1 on the
        first run" and "The run's messages_dequeued counts drained
        messages." (PRD section 3.7)

        Design: Corner/endpoints/run_ops_returns_opsrun_counters
        """
        stack = queued_message_stack(client, to_number="+15550000906")
        account_id = stack["account"]["id"]

        run = run_ops(client, account_id)
        assert run["run_index"] == 1
        assert run["messages_dequeued"] == 1

    def test_run_index_increments_monotonically_per_account(self, client):
        """PRD section 3.1: "Each ops run stamps a new OpsRun record whose
        run_index is a monotone per-account counter starting at 1 on the
        first run and whose executed_at is the logical clock at execution
        time".

        Design: Corner/endpoints/run_ops_returns_opsrun_counters
        """
        account = create_account(client, plan_tier="STANDARD")
        run1 = run_ops(client, account["id"])
        run2 = run_ops(client, account["id"])
        assert run1["run_index"] == 1
        assert run2["run_index"] == 2


class TestChargesFilteredByReference:
    def test_charges_list_filters_by_reference_type_and_id(self, client):
        """PRD section 2.3: "Filter query parameters specific to each
        collection (for example status, brand_id, campaign_id, account_id,
        phone_number, kind, message_id, sender_number_id, consent_record_id,
        reference_type, reference_id, day_utc where supported) narrow the
        result set before pagination is applied."

        Design: Corner/endpoints/charges_filtered_list_by_reference
        """
        set_clock(client)
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_approved_campaign(client, account_id, brand["id"])
        run_ops(client, account_id)

        filtered = charges(
            client, account_id,
            reference_type=REFERENCE_CAMPAIGN, reference_id=campaign["id"],
        )
        kinds = sorted(c["kind"] for c in filtered)
        assert kinds == [CHARGE_CAMPAIGN_RECURRING, CHARGE_CAMPAIGN_REGISTRATION]
        amounts = {c["kind"]: c["amount_cents"] for c in filtered}
        assert amounts[CHARGE_CAMPAIGN_REGISTRATION] == 1500
        assert amounts[CHARGE_CAMPAIGN_RECURRING] == 1000
        assert all(c["reference_id"] == campaign["id"] for c in filtered)

    def test_charges_list_for_brand_reference_returns_vetting_fees(self, client):
        """PRD section 3.2: "Each submission round does two things: it
        computes the brand's identity_score, and it records a BRAND_VETTING
        charge of 200 cents (reference_type BRAND, reference_id the brand's
        id)".

        Design: Corner/endpoints/charges_filtered_list_by_reference
        """
        set_clock(client)
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)

        filtered = charges(
            client, account_id, reference_type="BRAND", reference_id=brand["id"]
        )
        assert len(filtered) == 1
        assert filtered[0]["kind"] == "BRAND_VETTING"
        assert filtered[0]["amount_cents"] == 200
