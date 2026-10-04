"""Compensating invariant: the report's matched/unmatched partition always
conserves total_usage_cents, including across a later MatchRun re-partition."""
from test_helpers import (
    TEST_USERS, validate_success,
    set_clock, create_active_schedule, setup_active_dsp, create_member,
    setup_work_with_share, create_report_with_lines, submit_report,
    accept_report, assert_report_partition_invariant,
    pad_report_for_match_floor,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]

# Pad line: 734 plays * 131 = 96154 matched cents, so the acceptance circuit
# breaker passes with 144100 unmatched (100*144100 <= 60*(144100+96154)).
_PAD_MATCHED_CENTS = 96154


def _setup_report_then_match():
    """Report 2026-06: L1 'Kestrel' 131000 (unmatched at accept), L2 'Petrel'
    13100 (unmatched), plus a matched pad line (96134, shareless pad work) so
    the acceptance circuit breaker passes; then work 'Kestrel' registered and
    a MatchRun re-matches L1."""
    set_clock("2026-09-01T00:00:00Z")
    create_active_schedule()
    dsp, dsp_headers, ack = setup_active_dsp()
    m_a = create_member()
    report, _lines = create_report_with_lines(dsp, dsp_headers, "2026-06", [
        {"track_title": "Kestrel", "plays_count": 1000, "duration_seconds": 100,
         "isrc": "USAA19900001"},
        {"track_title": "Petrel", "plays_count": 100, "duration_seconds": 100,
         "isrc": "USAA19900003"},
    ])
    pad = pad_report_for_match_floor(dsp, dsp_headers, report, 144100)
    assert pad["royalties_cents"] == _PAD_MATCHED_CENTS
    submit_report(dsp, dsp_headers, ack, report)
    accepted = accept_report(dsp, ack, report)
    setup_work_with_share("Kestrel", m_a)
    return dsp, report, accepted


def test_acceptance_partition_sums_to_total(api):
    """PRD §3.4: "The acceptance then freezes `matched_usage_cents` as the sum
    of `royalties_cents` over the lines the sweep moved to `MATCHED` and
    `unmatched_usage_cents` as the sum over those moved to `UNMATCHED`, and the
    invariant that their sum equals `total_usage_cents` must hold."

    Design: Difficulty/compensating_invariant/report_split_conserves_total_cents
    """
    _dsp, _report, accepted = _setup_report_then_match()
    assert accepted["total_usage_cents"] == 144100 + _PAD_MATCHED_CENTS, (
        f"1000*131 + 100*131 + pad; got {accepted['total_usage_cents']}")
    assert accepted["matched_usage_cents"] == _PAD_MATCHED_CENTS
    assert accepted["unmatched_usage_cents"] == 144100
    assert_report_partition_invariant(accepted)


def test_match_run_repartition_still_conserves_total(api):
    """PRD §2.9: "First, on every accepted usage report the matched and
    unmatched partitions must sum exactly to the report's total:
    `matched_usage_cents` plus `unmatched_usage_cents` always equals
    `total_usage_cents`, whether the split was frozen at acceptance or adjusted
    by a later audit."

    Design: Difficulty/compensating_invariant/report_split_conserves_total_cents
    """
    dsp, report, _accepted = _setup_report_then_match()
    validate_success(api_client.create_match_run(ADMIN), expected_status=201)
    after = validate_success(
        api_client.get_usage_report(dsp["id"], report["id"], ADMIN))
    assert after["total_usage_cents"] == 144100 + _PAD_MATCHED_CENTS
    assert after["matched_usage_cents"] == 131000 + _PAD_MATCHED_CENTS, (
        f"the re-matched Kestrel line moves its cents into the matched "
        f"partition; got {after['matched_usage_cents']}")
    assert after["unmatched_usage_cents"] == 13100
    assert_report_partition_invariant(after)
