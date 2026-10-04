"""Boundaries: the inclusive TEN_DLC tier threshold and the exclusive
throughput cap.
"""

from test_helpers import validate_error
from test_helpers.api_errors import ERR_THROUGHPUT_EXCEEDED
from test_helpers.fixtures import (
    approve_campaign,
    attach_number,
    create_account,
    create_active_number,
    create_campaign,
    create_consent,
    create_verified_brand,
    send_message,
    set_clock,
    submit_campaign,
)
from test_helpers.constants import PATH_TEN_DLC, PATH_TOLL_FREE
from test_helpers.test_users import CAMPAIGN_MANAGER


class TestTenDlcTierBoundaryInclusive:
    def test_score_75_lands_in_the_top_tier(self, client):
        """PRD section 3.4: "a score of at least 75 allocates 10 messages
        per second; otherwise a score of at least 50 allocates 3". And: "A
        score of exactly 75 lands in the 10-per-second tier, not the
        3-per-second tier."

        Design: Difficulty/boundary_precision_check/ten_dlc_tier_boundary_score_75_inclusive
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="high75")
        assert brand["identity_score"] == 75

        campaign = create_campaign(client, account_id, brand["id"], path_kind=PATH_TEN_DLC)
        campaign = submit_campaign(client, account_id, campaign["id"])
        assert campaign["trust_score"] == 75
        assert campaign["allocated_mps"] == 10

    def test_score_70_falls_in_the_middle_tier(self, client):
        """PRD section 3.4: "A TEN_DLC campaign is tiered on trust_score
        with inclusive tier boundaries: a score of at least 75 allocates 10
        messages per second; otherwise a score of at least 50 allocates 3".

        Design: Difficulty/boundary_precision_check/ten_dlc_tier_boundary_score_75_inclusive
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="mid70")
        assert brand["identity_score"] == 70

        campaign = create_campaign(client, account_id, brand["id"], path_kind=PATH_TEN_DLC)
        campaign = submit_campaign(client, account_id, campaign["id"])
        assert campaign["trust_score"] == 70
        assert campaign["allocated_mps"] == 3


class TestThroughputCapIsExclusive:
    def test_capth_send_in_the_window_is_rejected(self, client):
        """PRD section 3.6: "When the count has reached exactly
        allocated_mps, the send is rejected with ERR_THROUGHPUT_EXCEEDED
        (HTTP 429) — the boundary is exclusive of the cap, so the cap-th
        send in the window fails."

        Design: Difficulty/boundary_precision_check/send_rejected_when_throughput_count_equals_cap
        """
        set_clock(client, "2026-09-01T00:00:00Z")
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="charity90")
        campaign = create_campaign(
            client, account_id, brand["id"],
            path_kind=PATH_TOLL_FREE, use_case="TRANSACTIONAL",
        )
        campaign = submit_campaign(client, account_id, campaign["id"])
        assert campaign["allocated_mps"] == 3
        campaign = approve_campaign(client, account_id, campaign["id"])
        number = create_active_number(
            client, account_id, number_type="TOLL_FREE", phone_number="+18005551234"
        )
        attach_number(client, account_id, number["id"], campaign["id"])
        for phone in ("+15550000041", "+15550000042", "+15550000043"):
            create_consent(client, account_id, brand["id"], phone)
        create_consent(client, account_id, brand["id"], "+15550000044")

        for phone in ("+15550000041", "+15550000042", "+15550000043"):
            message = send_message(
                client, account_id, campaign["id"], number["id"], phone
            )
            assert message["status"] == "QUEUED"

        fourth = client.send_message(
            account_id,
            {
                "campaign_id": campaign["id"],
                "sender_number_id": number["id"],
                "to_number": "+15550000044",
                "body": "four",
                "carrier_code": "VZW",
            },
            headers=CAMPAIGN_MANAGER,
        )
        validate_error(fourth, ERR_THROUGHPUT_EXCEEDED)

        messages = client.list_messages(
            account_id,
            params={"campaign_id": campaign["id"]},
            headers=CAMPAIGN_MANAGER,
        ).json()["data"]
        assert len(messages) == 3

    def test_send_after_the_window_advances_is_accepted(self, client):
        """PRD section 3.6: "Throughput: the count of this campaign's
        messages created within the trailing 1 second of the logical clock
        must be strictly below allocated_mps." Advancing the logical clock
        by two seconds empties the trailing window, so the next send is
        accepted again.

        Design: Difficulty/boundary_precision_check/send_rejected_when_throughput_count_equals_cap
        """
        set_clock(client, "2026-09-01T00:00:00Z")
        account = create_account(client, plan_tier="STANDARD")
        account_id = account["id"]
        brand = create_verified_brand(client, account_id, profile="charity90")
        campaign = create_campaign(
            client, account_id, brand["id"],
            path_kind=PATH_TOLL_FREE, use_case="TRANSACTIONAL",
        )
        campaign = submit_campaign(client, account_id, campaign["id"])
        campaign = approve_campaign(client, account_id, campaign["id"])
        number = create_active_number(
            client, account_id, number_type="TOLL_FREE", phone_number="+18005551234"
        )
        attach_number(client, account_id, number["id"], campaign["id"])
        for phone in ("+15550000051", "+15550000052", "+15550000053", "+15550000054"):
            create_consent(client, account_id, brand["id"], phone)

        for phone in ("+15550000051", "+15550000052", "+15550000053"):
            send_message(client, account_id, campaign["id"], number["id"], phone)

        set_clock(client, "2026-09-01T00:00:02Z")
        accepted = send_message(
            client, account_id, campaign["id"], number["id"], "+15550000054"
        )
        assert accepted["status"] == "QUEUED"
