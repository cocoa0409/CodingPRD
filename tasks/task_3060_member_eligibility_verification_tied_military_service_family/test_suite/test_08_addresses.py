"""Address intervals: half-open overlap semantics and the retroactive
duty-station (PCS) guard."""
from test_helpers import ApiErrorId, factories, fixtures
from test_helpers import validate_error, validate_success
from test_helpers.fixtures import make_member_headers


def _address(**overrides):
    return factories.address_payload(**overrides)


class TestHalfOpenIntervals:
    def _member_with_first_interval(self, api):
        _, member_id = fixtures.approve_direct_member(api, name="Ria Road")
        headers = make_member_headers(member_id)
        validate_success(api.create_address(
            member_id,
            _address(line1="1 First St",
                     effective_from="2026-01-01", effective_to="2026-06-01"),
            headers,
        ), 201)
        return member_id, headers

    def test_touching_interval_accepted(self, api):
        """PRD §3.11: "The intervals are half-open — the end instant is
        excluded — so two intervals that merely touch, one ending exactly
        when the next begins, are legal."

        Design: Difficulty/resource_temporal_overlap/address_overlap_half_open_touching_allowed
        """
        member_id, headers = self._member_with_first_interval(api)
        created = validate_success(api.create_address(
            member_id,
            _address(line1="2 Second St", city="Austin",
                     postal_code="78701", effective_from="2026-06-01"),
            headers,
        ), 201)
        assert created["effective_from"].startswith("2026-06-01")

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.11: "Address intervals of the same `addr_type` for one
        member must not overlap... A collision, or an `effective_to` at or
        before its `effective_from`, is rejected with `ERR_ADDRESS_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/address_overlap_half_open_touching_allowed
        """
        member_id, headers = self._member_with_first_interval(api)
        resp = api.create_address(
            member_id,
            _address(line1="3 Third St", city="Dallas",
                     postal_code="75201", effective_from="2026-05-31"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_ADDRESS_OVERLAP, 409)


class TestDutyStationChange:
    def _member_with_open_duty_interval(self, api):
        _, member_id = fixtures.approve_direct_member(
            api, name="Pcs Pete", still_serving=True,
        )
        headers = make_member_headers(member_id)
        first = validate_success(api.create_address(
            member_id,
            _address(addr_type="MILITARY_APO_FPO_DPO",
                     line1="Unit 1 Box 1", city="APO", region_code="AE",
                     postal_code="09096", effective_from="2026-01-01",
                     is_duty_station=True),
            headers,
        ), 201)
        return member_id, headers, first

    def test_pcs_after_closing_prior_interval_accepted(self, api):
        """PRD §3.11: "Intervals may be adjusted after the fact — typically
        to close `effective_to` on a duty-station change — and every
        adjustment revalidates the same interval rules." and "two intervals
        that merely touch, one ending exactly when the next begins, are
        legal."

        Design: Corner/endpoints/duty_station_change_closes_prior_interval
        """
        member_id, headers, first = self._member_with_open_duty_interval(api)
        validate_success(api.patch_address(
            first["id"], {"effective_to": "2026-09-01"}, headers,
        ))
        created = validate_success(api.create_address(
            member_id,
            _address(addr_type="MILITARY_APO_FPO_DPO",
                     line1="Unit 2 Box 2", city="APO", region_code="AP",
                     postal_code="96271", effective_from="2026-09-01",
                     is_duty_station=True),
            headers,
        ), 201)
        assert created["is_duty_station"] is True
