"""Read-your-writes and counter reconciliation.

The platform exposes derived counters and a synthesised status; both must agree
with the writes that produced them at the very next read.
"""

from test_helpers import (
    TEST_USERS,
    approve_artwork_for_set,
    approve_card_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    is_iso8601_timestamp,
    validate_success,
)

LM = TEST_USERS["licensing_manager_headers"]
PM = TEST_USERS["product_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_a_read_immediately_after_an_approval_reports_the_new_state(api):
    """PRD §2.12: "This field is recomputed on every mutation of the card set
    itself, on every transition of a print-run decision, and on every read of
    the card set, so a client can never observe a stale value."

    Design: Corner/consistency_model/an_immediate_read_after_a_write_reflects_the_new_state
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))

    approving = validate_success(
        approve_card_set(api, card_set["id"], submitted["version"])
    )
    assert approving["status"] == "APPROVED"

    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["status"] == "APPROVED"
    assert read["updated_at"] >= approving["updated_at"]
    assert is_iso8601_timestamp(read["updated_at"])


def test_a_freeze_is_visible_on_the_very_next_read(api):
    """PRD §2.12: "once a decision is frozen it reads as `LOCKED` — and
    thereafter resolves to either `DISCLOSED` or `UNDISCLOSED` according to
    whether the frozen decision published its quantity."

    Design: Corner/consistency_model/an_immediate_read_after_a_write_reflects_the_new_state
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    approved = get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))

    decision = get_success_data(
        api.create_print_run_decision(
            {
                "card_set_id": approved["id"],
                "authority": "BRAND_DIRECTIVE",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 12000,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        )
    )
    frozen = validate_success(
        api.approve_print_run_decision(
            decision["id"],
            {
                "expected_card_set_version": approved["version"],
                "expected_product_line_version": line["version"],
            },
            PLANNER,
        )
    )
    read = validate_success(api.get_card_set(approved["id"], PM))
    assert read["print_run_status"] in ("LOCKED", "DISCLOSED", "UNDISCLOSED")
    assert read["print_run_quantity"] == frozen["final_quantity"]


def test_the_print_run_summary_agrees_with_the_set_it_describes(api):
    """PRD §2.12: "The corresponding read capability returns the compound status
    together with the frozen quantity, the announced flag and the decision
    record it was derived from, in one response."

    Design: Corner/consistency_model/an_immediate_read_after_a_write_reflects_the_new_state
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    approved = get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))
    decision = get_success_data(
        api.create_print_run_decision(
            {
                "card_set_id": approved["id"],
                "authority": "BRAND_DIRECTIVE",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 12000,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        )
    )
    validate_success(
        api.approve_print_run_decision(
            decision["id"],
            {
                "expected_card_set_version": approved["version"],
                "expected_product_line_version": line["version"],
            },
            PLANNER,
        )
    )
    summary = validate_success(api.get_card_set_print_run_summary(approved["id"], PLANNER))
    read = validate_success(api.get_card_set(approved["id"], PM))
    assert summary["print_run_status"] == read["print_run_status"]
    assert summary["print_run_quantity"] == read["print_run_quantity"] == 12000


def test_a_count_refresh_on_a_set_does_not_bump_its_version(api):
    """PRD §2.5: "Refreshing `quality_claim_count` on a card set because a quality
    claim moved does not increment that card set's `version`, and refreshing
    `collector_notification_count` on a redemption because a notification moved
    does not increment that redemption's `version`."

    Design: Corner/consistency_model/an_immediate_read_after_a_write_reflects_the_new_state
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    before = get_success_data(api.get_card_set(card_set["id"], PM))
    before_version = get_success_data(
        api.get_card_set(card_set["id"], TEST_USERS["quality_analyst_headers"])
    )["version"]

    get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 10,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            TEST_USERS["quality_analyst_headers"],
        )
    )
    after = validate_success(api.get_card_set(card_set["id"], PM))
    assert after["quality_claim_count"] == 1
    assert after["version"] == before_version, (
        "a count refresh on the described entity is not a mutation of it"
    )
    assert after["version"] == before["version"]


def test_an_approve_then_rollback_is_reconciled_by_traversal(api):
    """PRD §2.9: "Aggregate counters — how many sets sit under a license, how
    many redemptions remain outstanding against a set, how many claims have
    been filed — are recomputed by full traversal rather than by incremental
    adjustment, so a value that moves backwards (a set rolled out of approval,
    a claim credited rather than approved) immediately lowers the counter
    rather than leaving a stale increment behind."

    Design: Corner/consistency_model/license_counts_are_reconciled_by_traversal_not_by_a_running_delta
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    first_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Base", set_tier="BASE", print_run_quantity=500
    )
    approve_artwork_for_set(api, first_set["id"], license_obj["id"])
    first_submitted = get_success_data(api.submit_card_set(first_set["id"], PM))
    get_success_data(approve_card_set(api, first_set["id"], first_submitted["version"]))

    second_set = create_card_set_raw(
        api, line["id"], set_name="Flagship Auto", set_tier="BASE", print_run_quantity=1000
    )
    approve_artwork_for_set(api, second_set["id"], license_obj["id"])
    second_submitted = get_success_data(api.submit_card_set(second_set["id"], PM))
    get_success_data(approve_card_set(api, second_set["id"], second_submitted["version"]))

    during = validate_success(api.get_license(license_obj["id"], LM))
    assert during["approved_set_count"] == 2
    assert during["set_count"] == 2

    get_success_data(api.return_card_set_to_draft(second_set["id"], PM))
    after = validate_success(api.get_license(license_obj["id"], LM))
    assert after["approved_set_count"] == 1
    assert after["set_count"] == 2


def test_a_second_approve_rollback_cycle_does_not_drift_the_counter(api):
    """PRD §2.9: "a value that moves backwards (a set rolled out of approval,
    a claim credited rather than approved) immediately lowers the counter
    rather than leaving a stale increment behind."

    Design: Corner/consistency_model/license_counts_are_reconciled_by_traversal_not_by_a_running_delta
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    submitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    get_success_data(approve_card_set(api, card_set["id"], submitted["version"]))
    get_success_data(api.return_card_set_to_draft(card_set["id"], PM))
    first_cycle = validate_success(api.get_license(license_obj["id"], LM))
    assert first_cycle["approved_set_count"] == 0

    resubmitted = get_success_data(api.submit_card_set(card_set["id"], PM))
    get_success_data(approve_card_set(api, card_set["id"], resubmitted["version"]))
    get_success_data(api.return_card_set_to_draft(card_set["id"], PM))
    second_cycle = validate_success(api.get_license(license_obj["id"], LM))
    assert second_cycle["approved_set_count"] == 0, "no drift across repeated cycles"
    assert second_cycle["set_count"] == 1


def test_the_set_status_of_the_two_sets_diverges_after_the_rollback(api):
    """PRD §3.2: "From `UNDER_REVIEW`, a set can be returned to draft by the
    `ProductManager`".

    Design: Corner/consistency_model/license_counts_are_reconciled_by_traversal_not_by_a_running_delta
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    kept = create_card_set_raw(
        api, line["id"], set_name="Flagship Base", set_tier="BASE", print_run_quantity=500
    )
    approve_artwork_for_set(api, kept["id"], license_obj["id"])
    kept_submitted = get_success_data(api.submit_card_set(kept["id"], PM))
    get_success_data(approve_card_set(api, kept["id"], kept_submitted["version"]))

    rolled = create_card_set_raw(
        api, line["id"], set_name="Flagship Auto", set_tier="BASE", print_run_quantity=1000
    )
    approve_artwork_for_set(api, rolled["id"], license_obj["id"])
    rolled_submitted = get_success_data(api.submit_card_set(rolled["id"], PM))
    get_success_data(approve_card_set(api, rolled["id"], rolled_submitted["version"]))
    get_success_data(api.return_card_set_to_draft(rolled["id"], PM))

    assert validate_success(api.get_card_set(rolled["id"], PM))["status"] == "DRAFT"
    assert validate_success(api.get_card_set(kept["id"], PM))["status"] == "APPROVED"