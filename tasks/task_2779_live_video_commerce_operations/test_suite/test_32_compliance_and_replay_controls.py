"""Disclosure obligations, segregation of duties and the replay merchandising window."""

from test_helpers import (
    CLAIMS_OFFICER_ID,
    CLOCK_EPOCH,
    MERCHANDISER,
    PRODUCER,
    SIGNOFF_OFFICER_ID,
    ApiErrorId,
    acknowledge_disclosure,
    acknowledge_payload,
    api_client,
    assert_disclosure_record,
    assert_instant,
    assert_lineup_slot,
    assert_show,
    compliance_signoff,
    end_scenario,
    live_show_scenario,
    make_compliance_officer_headers,
    make_host_headers,
    prepared_draft_show,
    publish_marker,
    read_show,
    read_slot,
    ready_show,
    record_conversion,
    replay_conversion_payload,
    replay_marker_payload,
    set_marker,
    signoff_payload,
    validate_error,
    validate_success,
)


def _read_disclosure(record_id):
    return validate_success(api_client.get_disclosure_record(record_id, PRODUCER))


def test_acknowledging_with_the_wrong_script_code_is_a_malformed_request():
    """A host who quotes a script code other than the one the disclosure demands is
    refused, and the obligation stays outstanding until the right code is spoken.

    PRD 3.1: "the payload supplies `script_code_spoken`, which must equal the
    record's `required_script_code`, or the request is `ERR_INVALID_REQUEST`".

    Design: Corner/validations/acknowledge_with_the_wrong_script_code_returns_invalid_request
    """
    scenario = prepared_draft_show(acknowledge=False)
    record_id = scenario.disclosure["id"]

    wrong_code = api_client.acknowledge_disclosure_record(
        record_id,
        acknowledge_payload(script_code_spoken="SCRIPT-PAID-99"),
        make_host_headers(scenario.host_id),
    )
    validate_error(wrong_code, ApiErrorId.ERR_INVALID_REQUEST)

    outstanding = _read_disclosure(record_id)
    assert_disclosure_record(outstanding)
    assert outstanding["status"] == "PENDING", "the obligation is still outstanding"
    assert outstanding["acknowledged_at"] is None, "nothing was stamped"
    assert outstanding["version"] == scenario.disclosure["version"], (
        "a refused acknowledgement does not advance the record"
    )

    acknowledged = acknowledge_disclosure(record_id, scenario.host_id)
    assert acknowledged["status"] == "ACKNOWLEDGED", "the required code is accepted"
    assert_instant(acknowledged["acknowledged_at"], CLOCK_EPOCH, "acknowledged_at")
    assert acknowledged["acknowledged_late"] is False, (
        "the show has not gone live, so the acknowledgement is not late"
    )


def test_the_readiness_gate_refuses_a_show_with_an_outstanding_disclosure():
    """A single unacknowledged disclosure obligation keeps a show out of readiness,
    and the gate opens as soon as the host speaks the script.

    PRD 3.4: "No disclosure record belonging to this show may still be `PENDING`; a
    single unacknowledged obligation fails the gate with
    `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."

    Design: Corner/validations/ready_with_a_pending_disclosure_rejected_then_allowed_after_acknowledgement
    """
    scenario = prepared_draft_show(acknowledge=False)

    blocked = api_client.ready_show(scenario.show_id, PRODUCER)
    validate_error(blocked, ApiErrorId.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)

    still_draft = read_show(scenario.show_id)
    assert_show(still_draft)
    assert still_draft["status"] == "DRAFT", "the refused gate left the show in draft"

    acknowledge_disclosure(scenario.disclosure["id"], scenario.host_id)
    ready = ready_show(scenario.show_id)
    assert ready["status"] == "READY", "with the obligation met the gate opens"
    assert ready["simulcast_readiness_index"] == 100, (
        "one destination reporting the reference latency with no frame loss grades 100"
    )
    assert _read_disclosure(scenario.disclosure["id"])["status"] == "ACKNOWLEDGED"


def test_the_officer_who_substantiated_a_claim_may_not_sign_the_show_off():
    """Sign-off by the compliance officer who substantiated a merchandised product is
    refused, and a second officer settles the same show.

    PRD 2.12: "If the signing officer's identifier equals any of them, sign-off is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) and the show remains
    `ENDED`." PRD 3.9: "Sign-off stamps `settled_at` with the logical instant and
    `compliance_signoff_by_user_id` with the officer's `X-User-ID`".

    Design: Corner/validations/signoff_by_the_substantiating_officer_rejected_then_allowed_for_another
    """
    scenario = live_show_scenario()
    end_scenario(scenario, "2026-08-10T19:30:00Z")

    conflicted = api_client.compliance_signoff_show(
        scenario.show_id,
        make_compliance_officer_headers(CLAIMS_OFFICER_ID),
        signoff_payload(),
    )
    validate_error(conflicted, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    unsettled = read_show(scenario.show_id)
    assert unsettled["status"] == "ENDED", "the show remains ended after the refusal"
    assert unsettled["compliance_signoff_by_user_id"] is None, "no officer is recorded"
    assert unsettled["settled_at"] is None, "nothing was settled"

    settled = compliance_signoff(scenario.show_id, SIGNOFF_OFFICER_ID)
    assert settled["status"] == "SETTLED", "an independent officer may settle the show"
    assert settled["compliance_signoff_by_user_id"] == SIGNOFF_OFFICER_ID, (
        "the signing officer is recorded on the show"
    )
    assert_instant(settled["settled_at"], "2026-08-10T19:30:00Z", "settled_at")
    assert settled["margin_final_cents"] == 0, "the show captured no revenue to settle"


def test_a_replay_marker_at_the_aired_duration_is_accepted_and_one_second_past_it_is_not():
    """A replay marker may be anchored at the very last second of material that
    aired, but one second beyond the broadcast's own length is out of range.

    PRD 3.9: "The offset must land inside the material that actually aired: at least
    0 and no more than the whole number of seconds between the show's `went_live_at`
    and its `ended_at`, truncated downwards. An offset outside that range is
    `ERR_MARKER_OFFSET_OUT_OF_RANGE`."

    Design: Corner/validations/replay_marker_offset_at_the_aired_duration_accepted_one_second_past_rejected
    """
    scenario = live_show_scenario()
    ended = end_scenario(scenario, "2026-08-10T19:00:00Z")
    assert_instant(ended["went_live_at"], "2026-08-10T17:50:00Z", "went_live_at")
    assert_instant(ended["ended_at"], "2026-08-10T19:00:00Z", "ended_at")

    past_the_end = api_client.set_replay_marker(
        scenario.slot_id,
        replay_marker_payload(marker_offset_sec=4201),
        MERCHANDISER,
    )
    validate_error(past_the_end, ApiErrorId.ERR_MARKER_OFFSET_OUT_OF_RANGE)

    untouched = read_slot(scenario.slot_id)
    assert_lineup_slot(untouched)
    assert untouched["replay_marker_status"] == "NONE", "no marker was anchored"
    assert untouched["replay_marker_offset_sec"] is None
    assert untouched["replay_product_link_url"] is None

    anchored = set_marker(
        scenario.slot_id,
        marker_offset_sec=4200,
        product_link_url="https://shop.example.com/robe",
    )
    assert anchored["replay_marker_offset_sec"] == 4200, (
        "seventy minutes of airtime is four thousand two hundred seconds"
    )
    assert anchored["replay_marker_status"] == "DRAFT", "a fresh marker starts as a draft"
    assert anchored["replay_product_link_url"] == "https://shop.example.com/robe"


def test_a_replay_conversion_is_refused_until_the_marker_is_published():
    """A post-show conversion cannot be attributed to a slot whose marker is still a
    draft, and the same conversion is accepted once the marker is published.

    PRD 3.9: "The slot's `replay_marker_status` must be `PUBLISHED`, or the
    conversion is refused with `ERR_REPLAY_MARKER_NOT_PUBLISHED`, and `occurred_at`
    must be at or after the show's `ended_at`, or the conversion is
    `ERR_INVALID_REQUEST`." PRD 3.9 on the weight: "Within the first day — an
    elapsed figure of 24 hours or fewer — the conversion carries full weight of
    `1.0`."

    Design: Corner/validations/replay_conversion_before_the_marker_is_published_rejected
    """
    scenario = live_show_scenario()
    end_scenario(scenario, "2026-08-10T19:00:00Z")
    drafted = set_marker(scenario.slot_id, marker_offset_sec=600)
    assert drafted["replay_marker_status"] == "DRAFT", "the marker is not published yet"

    unpublished = api_client.record_replay_conversion(
        scenario.slot_id,
        replay_conversion_payload(
            scenario.viewer_id,
            net_revenue_cents=4000,
            occurred_at="2026-08-10T20:00:00Z",
        ),
        MERCHANDISER,
    )
    validate_error(unpublished, ApiErrorId.ERR_REPLAY_MARKER_NOT_PUBLISHED)

    unattributed = read_slot(scenario.slot_id)
    assert unattributed["replay_conversions_count"] == 0, "no conversion was registered"
    assert unattributed["replay_attributed_revenue_cents"] == 0, "no revenue was attributed"
    assert read_show(scenario.show_id)["replay_attributed_revenue_cents"] == 0

    publish_marker(scenario.slot_id)
    slot = record_conversion(
        scenario.slot_id,
        scenario.viewer_id,
        net_revenue_cents=4000,
        occurred_at="2026-08-10T20:00:00Z",
    )
    assert slot["replay_marker_status"] == "PUBLISHED", "only a published marker earns attribution"
    assert slot["replay_conversions_count"] == 1, "the conversion is registered"
    assert slot["replay_attributed_revenue_cents"] == 4000, (
        "one hour after the show ends the conversion carries full weight"
    )
    assert read_show(scenario.show_id)["replay_attributed_revenue_cents"] == 4000, (
        "the show sums attributed revenue across its slots in the same request"
    )


def test_a_replay_marker_cannot_be_anchored_while_the_broadcast_is_still_on_air():
    """Replay merchandising is refused outright while the show is still live.

    PRD 3.9: "Replay merchandising begins once the broadcast is off air, and all
    three of its operations are refused while the show is still `DRAFT`, `READY` or
    `LIVE`, with `ERR_SHOW_NOT_ENDED`."

    Design: Corner/errors/replay_marker_before_the_show_ends_returns_show_not_ended
    """
    scenario = live_show_scenario()
    before = read_slot(scenario.slot_id)

    too_early = api_client.set_replay_marker(
        scenario.slot_id,
        replay_marker_payload(marker_offset_sec=600),
        MERCHANDISER,
    )
    validate_error(too_early, ApiErrorId.ERR_SHOW_NOT_ENDED)

    slot = read_slot(scenario.slot_id)
    assert slot["replay_marker_status"] == "NONE", "no marker was anchored"
    assert slot["replay_marker_offset_sec"] is None
    assert slot["replay_product_link_url"] is None
    assert slot["version"] == before["version"], "the refused call wrote nothing"

    show = read_show(scenario.show_id)
    assert show["status"] == "LIVE", "the broadcast is still on air"
    assert show["ended_at"] is None
