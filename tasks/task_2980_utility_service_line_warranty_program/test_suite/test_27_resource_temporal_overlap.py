"""Two contended calendars, each walked at its own smallest unit.

A contractor's day is contended in minutes with a symmetric travel buffer, and a
partner's household file is contended in whole calendar days. Both tests probe
one unit either side of the edge and prove the losing candidate wrote nothing.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.api_client import canonical_instant
from test_helpers.api_errors import (
    ERR_CONTRACTOR_WINDOW_CONFLICT,
    ERR_DROP_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_ids_in_order,
    assert_list_envelope,
    assert_refused,
)
from test_helpers.test_users import (
    MARKETING_OPS,
    MARKETING_OPS_USER_ID,
    OPERATIONS_ADMIN,
)


class TestContractorWindowTravelBuffer:
    """One minute decides whether a contractor can take the second job."""

    def test_visit_windows_collide_across_the_travel_buffer_on_both_ends(self, api):
        """13:44 is refused, 13:45 is admitted, and the mirror image is refused too.

        PRD: "Because of the buffer, two windows that merely touch at `window_end` still conflict, and the earliest non-conflicting start is exactly `window_end` plus 45 minutes."

        Design: Difficulty/resource_temporal_overlap/contractor_visit_windows_collide_across_the_travel_buffer
        """
        world = fixtures.active_coverage(api)
        enrollment_id = world["enrollment_id"]

        # Five open slots, so capacity can never mask the window rule.
        alder = fixtures.create_contractor(api)
        assert alder["max_open_dispatches"] == 5

        def approved(defect_location, description):
            claim = fixtures.file_claim(
                api,
                enrollment_id,
                defect_location=defect_location,
                incident_description=description,
            )
            decided = fixtures.approve_claim(api, claim["id"], coverage_note="Covered.")
            return claim["id"], decided["version"]

        anchor_id, anchor_version = approved(
            "CURB_STOP_TO_METER", "Claim 1: the anchor job."
        )
        trailing_id, trailing_version = approved(
            "METER_TO_HOME", "Claim 2: one minute inside the trailing buffer."
        )
        edge_id, edge_version = approved(
            "CURB_STOP_TO_METER", "Claim 3: exactly on the trailing buffer edge."
        )
        leading_id, leading_version = approved(
            "METER_TO_HOME", "Claim 4: mirror-image probe on the leading buffer."
        )

        # ── the blocking dispatch, left in ASSIGNED so it keeps blocking ──
        anchor_dispatch = fixtures.dispatch_claim_to(
            api, anchor_id, anchor_version, alder["id"], "2026-09-10T09:00:00.000Z"
        )
        assert canonical_instant(anchor_dispatch["window_start"]) == "2026-09-10T09:00:00.000Z"
        # A water service line takes 240 minutes.
        assert canonical_instant(anchor_dispatch["window_end"]) == "2026-09-10T13:00:00.000Z"
        assert anchor_dispatch["status"] == "ASSIGNED"

        # ── one minute inside the trailing buffer ──
        trailing = api.create_dispatch(
            trailing_id,
            factories.manual_dispatch_payload(
                trailing_version, "2026-09-10T13:44:00.000Z", alder["id"]
            ),
            OPERATIONS_ADMIN,
        )
        assert_refused(trailing, ERR_CONTRACTOR_WINDOW_CONFLICT, 422)

        # ── the mirror image: a candidate that ends before the anchor starts ──
        # 04:16 runs to 08:16, and the anchor's 09:00 is still inside 08:16 plus
        # the buffer, so the padding bites on the leading end as well.
        leading = api.create_dispatch(
            leading_id,
            factories.manual_dispatch_payload(
                leading_version, "2026-09-10T04:16:00.000Z", alder["id"]
            ),
            OPERATIONS_ADMIN,
        )
        assert_refused(leading, ERR_CONTRACTOR_WINDOW_CONFLICT, 422)

        # ── exactly on the trailing edge ──
        edge_dispatch = validate_success(
            api.create_dispatch(
                edge_id,
                factories.manual_dispatch_payload(
                    edge_version, "2026-09-10T13:45:00.000Z", alder["id"]
                ),
                OPERATIONS_ADMIN,
            ),
            201,
        )
        assert edge_dispatch["status"] == "ASSIGNED"
        assert canonical_instant(edge_dispatch["window_start"]) == "2026-09-10T13:45:00.000Z"
        assert canonical_instant(edge_dispatch["window_end"]) == "2026-09-10T17:45:00.000Z"

        # Both refusals wrote nothing at all.
        rows, _ = assert_list_envelope(
            api.list_dispatches(OPERATIONS_ADMIN, params={"contractor_id": alder["id"]}),
            expected_total=2,
        )
        assert_ids_in_order(rows, [anchor_dispatch["id"], edge_dispatch["id"]])

        booked = fixtures.refresh_contractor(api, alder["id"])
        # Well under the ceiling, so capacity never participated.
        assert booked["open_dispatch_count"] == 2

        for claim_id, version in ((trailing_id, trailing_version), (leading_id, leading_version)):
            untouched = fixtures.refresh_claim(api, claim_id)
            assert untouched["status"] == "APPROVED"
            assert untouched["version"] == version

        # Exactly two provisional reservations of 6 hours at 18000 plus 120000.
        enrollment = fixtures.refresh_enrollment(api, enrollment_id)
        assert enrollment["annual_benefit_reserved_cents"] == 456000


class TestCampaignDropSpacing:
    """One calendar day decides whether a partner's next drop may be submitted."""

    def test_drop_dates_collide_inside_the_partner_spacing_window(self, api):
        """A 20-day gap is refused at submission and a 21-day gap is admitted.

        PRD: "A conflict exists when that gap is strictly fewer days than the partner's `min_days_between_drops`; a gap exactly equal to `min_days_between_drops` is permitted."

        Design: Difficulty/resource_temporal_overlap/campaign_drop_dates_collide_inside_the_partner_spacing_window
        """
        world = fixtures.active_partner_with_product(api)
        partner_id = world["partner_id"]
        product_id = world["product_id"]
        assert world["partner"]["min_days_between_drops"] == 21

        anchor = fixtures.create_campaign(
            api,
            partner_id,
            product_id,
            name="Anchor drop",
            drop_date="2026-08-05",
            requested_quantity=500,
        )
        assert fixtures.submit_campaign(api, anchor["id"])["status"] == "PARTNER_REVIEW"
        approved_anchor = fixtures.approve_campaign(
            api, anchor["id"], partner_id, approved_quantity=500
        )
        # Only PARTNER_REVIEW, APPROVED and MAILED siblings are considered.
        assert approved_anchor["status"] == "APPROVED"
        assert approved_anchor["drop_date"] == "2026-08-05"

        # Creation never evaluates spacing, so both conflicting drafts may exist.
        inside = fixtures.create_campaign(
            api,
            partner_id,
            product_id,
            name="Twenty-day follow-up",
            piece_type="DIRECT_MAIL_LETTER",
            drop_date="2026-08-25",
            requested_quantity=300,
        )
        on_edge = fixtures.create_campaign(
            api,
            partner_id,
            product_id,
            name="Twenty-one-day follow-up",
            piece_type="DIRECT_MAIL_LETTER",
            drop_date="2026-08-26",
            requested_quantity=300,
        )
        assert inside["status"] == "DRAFT"
        assert on_edge["status"] == "DRAFT"

        # ── one day inside the window ──
        refused = api.submit_campaign(
            inside["id"],
            factories.campaign_submission_payload(note="Submitting the 20-day follow-up."),
            MARKETING_OPS,
        )
        assert_refused(refused, ERR_DROP_WINDOW_CONFLICT, 422)

        blocked = validate_success(api.get_campaign(inside["id"], MARKETING_OPS))
        assert blocked["status"] == "DRAFT"
        assert blocked["submitted_by_user_id"] is None
        # A refused submission is not a revision.
        assert blocked["revision_count"] == 0

        # ── exactly on the edge ──
        admitted = fixtures.submit_campaign(
            api, on_edge["id"], note="Submitting the 21-day follow-up."
        )
        assert admitted["status"] == "PARTNER_REVIEW"
        assert admitted["submitted_by_user_id"] == MARKETING_OPS_USER_ID
        assert admitted["revision_count"] == 0

        draft_rows, _ = assert_list_envelope(
            api.list_campaigns(
                MARKETING_OPS, params={"partner_id": partner_id, "status": "DRAFT"}
            ),
            expected_total=1,
        )
        assert_ids_in_order(draft_rows, [inside["id"]])

        all_rows, _ = assert_list_envelope(
            api.list_campaigns(MARKETING_OPS, params={"partner_id": partner_id}),
            expected_total=3,
        )
        assert_ids_in_order(all_rows, [anchor["id"], inside["id"], on_edge["id"]])
