"""Depth tests for cross-entity state gates (batch approval, workshop sales)."""
from test_helpers import (
    api_client,
    create_active_developer,
    create_approved_title,
    create_buyer,
    create_key_batch_payload,
    create_released_title,
    create_user,
    create_workshop_item_payload,
    create_workshop_sale_payload,
    get_success_data,
    make_developer_headers,
    make_user_headers,
    validate_error,
    validate_success,
    ApiErrorId,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]


class TestKeyBatchApprovalGatedByTitleRelease:
    def _setup_approved_title_with_batch(self, quantity=10):
        developer, title = create_approved_title()
        dev_headers = make_developer_headers(developer["id"])
        batch = get_success_data(
            api_client.create_key_batch(
                create_key_batch_payload(
                    title["id"], requested_quantity=quantity, free_keys_in_batch=0
                ),
                dev_headers,
            )
        )
        return developer, title, dev_headers, batch

    def test_approve_blocked_until_title_released(self):
        """PRD §3.6: "Approval enforces four preconditions: the title must be
        `RELEASED`; the title's `refund_abuse_flag` must be false — a
        gray-market control whose violation is rejected with
        `ERR_GRAY_MARKET_RISK` (HTTP 422); the free keys granted so far across
        the title's already-`APPROVED` batches plus this batch's
        `free_keys_in_batch` must not exceed the batch's snapshotted allowance
        — a violation is `ERR_FREE_KEY_ALLOWANCE_EXCEEDED` (HTTP 422); and the
        owning developer account must still be `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/key_batch_approval_gated_by_title_release_state
        """
        developer, title, dev_headers, batch = self._setup_approved_title_with_batch()

        # Title is APPROVED, not RELEASED: no valid transition for approve.
        res = api_client.approve_key_batch(batch["id"], OPS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api_client.release_now(title["id"], dev_headers))

        approved = get_success_data(api_client.approve_key_batch(batch["id"], OPS))
        assert approved["status"] == "APPROVED"
        assert approved["allocated_keys"] == 10

    def test_failed_approval_leaves_batch_requested_and_reusable(self):
        """PRD §3.6: "`PlatformOps` approves or rejects the batch."

        Design: Difficulty/cross_entity_state_dependency/key_batch_approval_gated_by_title_release_state
        """
        developer, title, dev_headers, batch = self._setup_approved_title_with_batch(quantity=7)

        res = api_client.approve_key_batch(batch["id"], OPS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        unchanged = get_success_data(api_client.get_key_batch(batch["id"], dev_headers))
        assert unchanged["status"] == "REQUESTED"

        get_success_data(api_client.release_now(title["id"], dev_headers))
        approved = get_success_data(api_client.approve_key_batch(batch["id"], OPS))
        assert approved["status"] == "APPROVED"
        assert approved["allocated_keys"] == 7


class TestWorkshopSaleGatedByItemPublishAndHostRelease:
    def test_sale_rejected_while_item_pending_then_succeeds_after_publish(self):
        """PRD §3.8: "The item must be `PUBLISHED` and its host title
        `RELEASED`; otherwise the sale is rejected with
        `ERR_ITEM_NOT_PURCHASABLE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/workshop_sale_gated_by_item_publish_and_host_release
        """
        developer, title = create_released_title()
        creator = create_user()
        buyer = create_buyer()
        item = get_success_data(
            api_client.create_workshop_item(
                create_workshop_item_payload(
                    title["id"], creator["id"],
                    item_name="Map Pack", price_cents=300, creator_share_bps=2500,
                ),
                make_user_headers(creator["id"]),
            )
        )

        res = api_client.create_workshop_sale(
            create_workshop_sale_payload(item["id"], buyer["id"]),
            make_user_headers(buyer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ITEM_NOT_PURCHASABLE)

        get_success_data(
            api_client.publish_workshop_item(item["id"], make_user_headers(creator["id"]))
        )

        sale = get_success_data(
            api_client.create_workshop_sale(
                create_workshop_sale_payload(item["id"], buyer["id"]),
                make_user_headers(buyer["id"]),
            )
        )
        assert sale["gross_cents"] == 300
        assert sale["creator_share_cents"] == 75  # floor(300 * 2500 / 10000)
        assert sale["platform_share_cents"] == 225

    def test_publish_blocked_while_host_title_not_released(self):
        """PRD §3.8: "The creator alone may publish the item, and only while the
        host title is `RELEASED`; publishing by anyone else fails ownership, and
        publishing against a non-released title is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/workshop_sale_gated_by_item_publish_and_host_release
        """
        developer, title = create_approved_title()  # APPROVED, not RELEASED
        creator = create_user()
        buyer = create_buyer()
        item = get_success_data(
            api_client.create_workshop_item(
                create_workshop_item_payload(
                    title["id"], creator["id"],
                    item_name="Skin Set", price_cents=200, creator_share_bps=1000,
                ),
                make_user_headers(creator["id"]),
            )
        )

        # Publish fails: host title is not RELEASED.
        res = api_client.publish_workshop_item(item["id"], make_user_headers(creator["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        # And a sale against the still-PENDING item fails too.
        res = api_client.create_workshop_sale(
            create_workshop_sale_payload(item["id"], buyer["id"]),
            make_user_headers(buyer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_ITEM_NOT_PURCHASABLE)
