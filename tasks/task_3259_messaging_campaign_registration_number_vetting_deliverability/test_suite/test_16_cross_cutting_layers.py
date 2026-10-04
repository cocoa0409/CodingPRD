"""Cross-cutting layers: optimistic concurrency on campaign resubmission,
and the trust-score recompute with its spam-floor volume gate.
"""

from test_helpers import validate_error
from test_helpers.api_errors import ERR_STALE_VERSION
from test_helpers.fixtures import (
    create_account,
    create_campaign,
    create_verified_brand,
    reject_campaign,
    sent_message_stack,
    submit_campaign,
)
from test_helpers.test_users import CAMPAIGN_MANAGER, SYSTEM_DRIVER, ANALYST


class TestOccOnCampaignResubmit:
    def test_resubmit_with_stale_version_is_rejected_412(self, client):
        """PRD section 2.7: "Resubmitting a campaign for carrier review
        (the submit action taken while the campaign is REJECTED) must carry
        expected_campaign_version equal to the campaign's current version."
        And: "if the supplied expected_campaign_version does not match the
        campaign's current version, the request is rejected with
        ERR_STALE_VERSION (HTTP 412) and no state changes."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_campaign_resubmit
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submitted = submit_campaign(client, account_id, campaign["id"])
        stale_version = submitted["version"]
        reject_campaign(client, account_id, campaign["id"], "CONTENT_VIOLATION")

        resubmit = client.submit_campaign(
            account_id,
            campaign["id"],
            payload={"expected_campaign_version": stale_version},
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(resubmit, ERR_STALE_VERSION)
        after = client.get_campaign(
            account_id, campaign["id"], headers=CAMPAIGN_MANAGER
        ).json()["data"]
        assert after["status"] == "REJECTED"

    def test_resubmit_with_current_version_succeeds(self, client):
        """PRD section 2.7: "The submit endpoint accepts
        expected_campaign_version as optional on the first submission from
        DRAFT (no OCC check applies there) but it is effectively required
        on resubmission from REJECTED". Supplying the current version
        passes the check.

        Design: Corner/cross_cutting_layers/occ_stale_version_on_campaign_resubmit
        """
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(client, account_id, brand["id"])
        submit_campaign(client, account_id, campaign["id"])
        rejected = reject_campaign(
            client, account_id, campaign["id"], "CONTENT_VIOLATION"
        )

        resubmitted = submit_campaign(
            client,
            account_id,
            campaign["id"],
            expected_campaign_version=rejected["version"],
        )
        assert resubmitted["status"] == "PENDING_REVIEW"


class TestSpamFloorVolumeGate:
    def test_high_spam_rate_below_volume_floor_does_not_suspend(self, client):
        """PRD section 3.8: "the spam-floor check runs: if the snapshot's
        attempted is at least 2000 and its spam_rate_bps is at least 300 —
        both boundaries inclusive, so exactly 2000 attempts with exactly
        300 basis points suspends". With attempted 1 the volume gate blocks
        suspension regardless of rate.

        Design: Corner/cross_cutting_layers/spam_floor_suspends_campaign_and_numbers
        """
        stack = sent_message_stack(client, to_number="+15550000907")
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        message_id = stack["message"]["id"]

        client.report_delivery_outcome(
            account_id, message_id, {"outcome": "DELIVERED"}, headers=SYSTEM_DRIVER
        )
        fb = client.create_feedback_event(
            account_id,
            {
                "campaign_id": campaign_id,
                "kind": "SPAM_COMPLAINT",
                "message_id": message_id,
            },
            headers=SYSTEM_DRIVER,
        )
        assert fb.status_code == 201

        snap = client.create_snapshot(
            account_id, campaign_id, {"day_utc": "2026-09-01"}, headers=ANALYST
        )
        assert snap.status_code == 201
        snapshot = snap.json()["data"]
        assert snapshot["spam_rate_bps"] == 10000

        campaign = client.get_campaign(account_id, campaign_id).json()["data"]
        assert campaign["trust_score"] == 80, (
            "95 initial, minus 15 for spam_rate_bps >= 100"
        )
        assert campaign["status"] == "APPROVED"

    def test_trust_recompute_applies_block_and_spam_penalties(self, client):
        """PRD section 3.8: "Per snapshot, the recompute starts from the
        current trust_score and applies penalties before the good-day
        bonus, clamping last: minus 5 if the snapshot's block_rate_bps is
        at least 300; minus 15 if its spam_rate_bps is at least 100".

        Design: Corner/cross_cutting_layers/spam_floor_suspends_campaign_and_numbers
        """
        stack = sent_message_stack(client, to_number="+15550000917")
        account_id = stack["account"]["id"]
        campaign_id = stack["campaign"]["id"]
        message_id = stack["message"]["id"]

        client.report_delivery_outcome(
            account_id, message_id, {"outcome": "DELIVERED"}, headers=SYSTEM_DRIVER
        )
        for kind in ("SPAM_COMPLAINT", "BLOCK"):
            fb = client.create_feedback_event(
                account_id,
                {
                    "campaign_id": campaign_id,
                    "kind": kind,
                    "message_id": message_id,
                },
                headers=SYSTEM_DRIVER,
            )
            assert fb.status_code == 201

        snap = client.create_snapshot(
            account_id, campaign_id, {"day_utc": "2026-09-01"}, headers=ANALYST
        )
        assert snap.status_code == 201
        snapshot = snap.json()["data"]
        assert snapshot["block_rate_bps"] == 10000
        assert snapshot["spam_rate_bps"] == 10000

        campaign = client.get_campaign(account_id, campaign_id).json()["data"]
        assert campaign["trust_score"] == 75, (
            "95 initial, minus 5 block penalty, minus 15 spam penalty"
        )
