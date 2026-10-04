"""Ad campaign cyclic lifecycle (PRD §3.7)."""
from test_helpers import (
    AD,
    ApiErrorId,
    create_ad_campaign_payload,
    set_clock,
    validate_error,
    validate_success,
)


def _create_campaign(api, flight_end="2026-09-10T00:00:00Z"):
    payload = create_ad_campaign_payload(flight_end=flight_end)
    resp = api.create_ad_campaign(payload, AD)
    return validate_success(resp, expected_status=201)


def test_campaign_booked_paused_booked_cycle_then_clock_gated_resume(api):
    """PRD §3.7: "A `BOOKED` campaign can be paused (no preconditions),
    moving it to `PAUSED`, and a `PAUSED` campaign can be resumed back to
    `BOOKED` provided `flight_end` is still greater than or equal to the
    current logical time."

    First pause/resume succeeds inside the flight; after the clock passes
    flight_end the second resume fails and the campaign stays PAUSED.

    Design: Difficulty/non_linear_state_machine/ad_campaign_booked_paused_booked_cycle
    """
    campaign = _create_campaign(api)
    cid = campaign["id"]
    validate_success(api.book_ad_campaign(cid, AD))
    paused = validate_success(api.pause_ad_campaign(cid, AD))
    assert paused["campaign_status"] == "PAUSED"
    resumed = validate_success(api.resume_ad_campaign(cid, AD))
    assert resumed["campaign_status"] == "BOOKED"
    set_clock("2026-09-11T00:00:00Z")
    # PRD pins both "campaign completion when current logical time passes
    # flight_end fires as the clock advances" (§2.8/§3.7) and "a BOOKED
    # campaign can be paused" (§3.7), without stating whether the completion
    # materializes at clock-set time (making the second pause hit the state
    # check) or is evaluated lazily (pause succeeds; resume then fails the
    # flight_end gate with ERR_INVALID_STATE). Accept either reading, then
    # assert the covered end state: the campaign must not be BOOKED.
    resp_pause = api.pause_ad_campaign(cid, AD)
    if resp_pause.status_code == 200:
        resp = api.resume_ad_campaign(cid, AD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_ad_campaign(cid, AD))
        assert after["campaign_status"] == "PAUSED"
    else:
        validate_error(resp_pause, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_ad_campaign(cid, AD))
        assert after["campaign_status"] in ("BOOKED", "COMPLETED")
        # If still BOOKED (lazy sweep), the resume must be clock-gated.
        if after["campaign_status"] == "BOOKED":
            resp = api.resume_ad_campaign(cid, AD)
            validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_campaign_cycle_versions_increment_each_transition(api):
    """PRD §3.7: "Booking moves the campaign from `DRAFT` to `BOOKED` and is
    permitted only when `flight_start` is strictly before `flight_end` and
    `flight_end` is greater than or equal to the current logical time."
    and "Each transition increments the campaign's `version`."

    The BOOKED -> PAUSED -> BOOKED loop is repeatable while the flight is
    open, and version advances on each leg.

    Design: Difficulty/non_linear_state_machine/ad_campaign_booked_paused_booked_cycle
    """
    campaign = _create_campaign(api)
    cid = campaign["id"]
    assert campaign["campaign_status"] == "DRAFT"
    booked = validate_success(api.book_ad_campaign(cid, AD))
    assert booked["campaign_status"] == "BOOKED"
    assert booked["version"] == campaign["version"] + 1
    paused = validate_success(api.pause_ad_campaign(cid, AD))
    assert paused["version"] == booked["version"] + 1
    resumed = validate_success(api.resume_ad_campaign(cid, AD))
    assert resumed["campaign_status"] == "BOOKED"
    assert resumed["version"] == paused["version"] + 1
    # The loop can be taken a second time while flight_end is still ahead.
    paused2 = validate_success(api.pause_ad_campaign(cid, AD))
    resumed2 = validate_success(api.resume_ad_campaign(cid, AD))
    assert resumed2["campaign_status"] == "BOOKED"
    assert resumed2["version"] == paused2["version"] + 1
