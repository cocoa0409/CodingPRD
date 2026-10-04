"""Dual-variant rules: one formula, two paths, observably different answers.

PRD section 3.7 prices a message per segment and adds the long-message
surcharge only once a message runs longer than 3 segments, while PRD
section 3.4 gives TOLL_FREE a flat throughput and TEN_DLC a tiered one.
"""

from test_helpers.assertions import charges_for
from test_helpers.constants import (
    CARRIER_VZW,
    CHARGE_CARRIER_PASSTHROUGH,
    CHARGE_MESSAGE,
    PATH_TEN_DLC,
    PATH_TOLL_FREE,
    REFERENCE_MESSAGE,
    USE_CASE_TRANSACTIONAL,
)
from test_helpers.fixtures import (
    attach_number,
    charges,
    create_account,
    create_active_number,
    create_approved_campaign,
    create_campaign,
    create_consent,
    create_verified_brand,
    run_ops,
    send_message,
    set_clock,
    submit_campaign,
)


class TestShortVsLongMessageFees:
    def test_short_and_long_message_bill_different_fee_profiles(self, client):
        """PRD section 3.7: "When a message runs longer than 3 segments, a
        one-time long-message surcharge of 50 cents is added to the message's
        fee once, after the per-segment sum."

        Design: Difficulty/dual_variant_calc/message_fee_short_vs_long_message
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_approved_campaign(client, account_id, brand["id"])
        number = create_active_number(client, account_id)
        attach_number(client, account_id, number["id"], campaign["id"])
        create_consent(client, account_id, brand["id"], "+15550000001")
        create_consent(client, account_id, brand["id"], "+15550000002")

        short = send_message(
            client, account_id, campaign["id"], number["id"],
            "+15550000001", body="A" * 160, carrier_code=CARRIER_VZW,
        )
        long = send_message(
            client, account_id, campaign["id"], number["id"],
            "+15550000002", body="B" * 640, carrier_code=CARRIER_VZW,
        )
        assert short["segments"] == 1, "160 GSM-7 chars must be 1 segment"
        assert long["segments"] == 4, "640 GSM-7 chars must be 4 segments"
        run_ops(client, account_id)

        all_charges = charges(client, account_id)
        short_msg = charges_for(
            all_charges, REFERENCE_MESSAGE, short["id"], CHARGE_MESSAGE
        )
        short_passthrough = charges_for(
            all_charges, REFERENCE_MESSAGE, short["id"], CHARGE_CARRIER_PASSTHROUGH
        )
        long_msg = charges_for(
            all_charges, REFERENCE_MESSAGE, long["id"], CHARGE_MESSAGE
        )
        long_passthrough = charges_for(
            all_charges, REFERENCE_MESSAGE, long["id"], CHARGE_CARRIER_PASSTHROUGH
        )
        assert [c["amount_cents"] for c in short_msg] == [75]
        assert [c["amount_cents"] for c in short_passthrough] == [45]
        assert [c["amount_cents"] for c in long_msg] == [4 * 75 + 50]
        assert [c["amount_cents"] for c in long_passthrough] == [4 * 45]
        total = (
            75 + 45 + (4 * 75 + 50) + (4 * 45)
        )
        observed = sum(
            c["amount_cents"]
            for c in charges_for(all_charges, REFERENCE_MESSAGE)
        )
        assert observed == total, "message-linked charges must total {0}".format(total)

    def test_long_message_boundary_three_segments_carries_no_surcharge(self, client):
        """PRD section 3.7: "The MESSAGE charge is the segment count times 75
        cents." The surcharge applies only when a message runs longer than 3
        segments, so exactly 3 segments bills 3 x 75 with no surcharge.

        Design: Difficulty/dual_variant_calc/message_fee_short_vs_long_message
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_approved_campaign(client, account_id, brand["id"])
        number = create_active_number(client, account_id)
        attach_number(client, account_id, number["id"], campaign["id"])
        create_consent(client, account_id, brand["id"], "+15550000003")

        three_seg = send_message(
            client, account_id, campaign["id"], number["id"],
            "+15550000003", body="C" * 480, carrier_code=CARRIER_VZW,
        )
        assert three_seg["segments"] == 3, "480 GSM-7 chars must be 3 segments"
        run_ops(client, account_id)

        all_charges = charges(client, account_id)
        msg_charges = charges_for(
            all_charges, REFERENCE_MESSAGE, three_seg["id"], CHARGE_MESSAGE
        )
        passthrough = charges_for(
            all_charges, REFERENCE_MESSAGE, three_seg["id"], CHARGE_CARRIER_PASSTHROUGH
        )
        assert [c["amount_cents"] for c in msg_charges] == [3 * 75]
        assert [c["amount_cents"] for c in passthrough] == [3 * 45]


class TestFlatTollFreeVsTieredTenDlc:
    def test_tollfree_ignores_trust_where_tendlc_tiers_on_it(self, client):
        """PRD section 3.4: "A TOLL_FREE campaign is allocated a flat 3
        messages per second; the path is gated at submit by the vetting score
        instead (§3.3)."

        Design: Difficulty/dual_variant_calc/throughput_flat_tollfree_vs_tiered_tendlc
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand_a = create_verified_brand(client, account_id, profile="high95")
        brand_b = create_verified_brand(client, account_id, profile="charity90")
        assert brand_a["identity_score"] == 95
        assert brand_b["identity_score"] == 90

        camp1 = create_campaign(client, account_id, brand_a["id"], path_kind=PATH_TEN_DLC)
        camp1 = submit_campaign(client, account_id, camp1["id"])
        camp2 = create_campaign(
            client, account_id, brand_b["id"],
            path_kind=PATH_TOLL_FREE, use_case=USE_CASE_TRANSACTIONAL,
        )
        camp2 = submit_campaign(client, account_id, camp2["id"])

        assert camp1["trust_score"] == 95
        assert camp1["allocated_mps"] == 10
        assert camp2["trust_score"] == 50
        assert camp2["allocated_mps"] == 3
        assert camp2["allocated_mps"] != camp1["allocated_mps"]

    def test_shortcode_ignores_trust_with_flat_hundred_mps(self, client):
        """PRD section 3.4: "A SHORT_CODE campaign is allocated a flat 100
        messages per second; trust_score is ignored entirely."

        Design: Difficulty/dual_variant_calc/throughput_flat_tollfree_vs_tiered_tendlc
        """
        set_clock(client)
        account = create_account(client)
        account_id = account["id"]
        brand = create_verified_brand(client, account_id)
        campaign = create_campaign(
            client, account_id, brand["id"], path_kind="SHORT_CODE"
        )
        campaign = submit_campaign(client, account_id, campaign["id"])
        assert campaign["trust_score"] == 50
        assert campaign["allocated_mps"] == 100
