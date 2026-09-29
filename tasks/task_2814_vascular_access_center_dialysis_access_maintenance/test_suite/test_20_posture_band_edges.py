"""One missed treatment, taken twice, walks a facility across two closed band edges.

Nothing about the two updates differs except the number they carry: 12 lands the score on
52 and 13 lands it on 48. The first crossing costs the facility its trust and holds its
only referral; the second closes triage to it altogether. The reason a single extra miss is
worth a full four points is that the grace credit has already collapsed to nothing along
with the tier.
"""

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

ACCESS_A_PLACED_ON = "2026-03-01"
ACCESS_B_PLACED_ON = "2026-03-05"
READING_AT = "2026-07-25T08:00:00Z"
INTAKE_NARRATIVE = "no missed treatments at intake"
PROBE_NARRATIVE = "probe referral raised while the contract is suspended"


def _one_facility_two_accesses_and_a_clean_referral(api):
    """A facility at full trust: one referral at zero missed treatments, score 100.

    Access B carries the only surveillance reading, so it is access B that is provably
    triageable on clinical grounds and can therefore only ever be refused on posture.
    """
    center = fx.seed_center(api)
    assert center["facility"]["partnership_tier"] == "SILVER"
    assert center["facility"]["partnership_score"] == 100
    assert center["facility"]["contract_status"] == "ACTIVE"
    assert center["facility"]["last_scored_at"] is None

    access_a = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVG",
        laterality="LEFT",
        site="FOREARM",
        placed_on=ACCESS_A_PLACED_ON,
    )
    access_b = fx.seed_access_in_use(
        api,
        center["patient_id"],
        access_type="AVF",
        laterality="RIGHT",
        site="UPPER_ARM",
        placed_on=ACCESS_B_PLACED_ON,
    )
    fx.seed_reading(
        api,
        access_b["id"],
        center["facility_id"],
        reading_at=READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=100,
        recirculation_pct=2.0,
        kind="ROUTINE",
    )
    referral_a = fx.seed_referral(
        api,
        access_a["id"],
        center["facility_id"],
        suspected_problem="STENOSIS",
        clinical_narrative=INTAKE_NARRATIVE,
        missed_treatment_count=0,
    )
    assert referral_a["status"] == "SUBMITTED"
    assert referral_a["missed_treatment_count"] == 0

    at_full_trust = fx.read_facility(api, center["facility_id"])
    assert at_full_trust["referral_volume_window"] == 1
    assert at_full_trust["raw_missed_count_window"] == 0
    assert at_full_trust["grace_credit_window"] == 0
    assert at_full_trust["adjusted_missed_count_window"] == 0
    assert at_full_trust["same_day_honored_window"] == 0
    assert at_full_trust["partnership_score"] == 100
    assert at_full_trust["partnership_tier"] == "GOLD"
    assert at_full_trust["contract_status"] == "ACTIVE"
    assertions.assert_instant_equals(
        at_full_trust["last_scored_at"], fx.CLOCK_STARTUP_UTC, "last_scored_at"
    )
    return center, access_a, access_b, referral_a, at_full_trust


def test_01_twelve_missed_treatments_land_on_fifty_two_and_hold_the_only_referral(api):
    """52 is inside the probation band, and the drop into it takes the referral with it.

    The arithmetic is fixed at every step. The tier the grace credit uses is not the one the
    update computes: "The tier to be used for the grace credit is read out of the facility's
    currently stored `partnership_tier` *before any field is written*." That stored tier is
    `GOLD`, and the PRD prices it — "The grace credit is the in-window referral volume
    multiplied by the rate for the tier read in Step A — one fifth for a `GOLD` partner, one
    tenth for a `SILVER` partner, and nothing at all for a `WATCH` partner — with the product
    taken to its **floor**, never rounded." One referral at a fifth floors to nothing, so all
    twelve misses are charged.

    The score follows: "The score starts at 100, loses four points for each adjusted missed
    treatment, gains three points for each honoured same-day case, and is then clamped into
    the range 0 to 100 inclusive." That is 100 minus 48, or 52, which the PRD bands twice
    over — "`partnership_tier` is set from that score: `GOLD` at 85 or above, otherwise
    `SILVER` at 70 or above, otherwise `WATCH`" and "`contract_status` is set from the same
    score: `ACTIVE` at 70 or above, otherwise `PROBATION` at 50 or above, otherwise
    `SUSPENDED`."

    The posture move is the edge itself: "`ACTIVE → PROBATION` fires when a freshly computed
    score lands between 50 and 69 inclusive." And it does not stop at the facility, because
    "**On a drop to `PROBATION`**, every referral of that facility whose `status` is
    `SUBMITTED` or `TRIAGED` is moved to `INFO_REQUESTED` with `hold_reason` set to
    `FACILITY_POSTURE_HOLD`, its `info_request_count` increased by one, and its
    `triage_score`, `triage_variant`, `urgency` and `triaged_at` cleared back to null".

    The held referral is nonetheless still counted, because Step A admits it by name: its
    membership filter takes referrals "whose `status` is one of `SUBMITTED`,
    `INFO_REQUESTED`, `TRIAGED`, `SCHEDULED` or `COMPLETED`" and only "`DECLINED` referrals
    are excluded from membership".

    Design: Corner/cross_cutting_complexity_layers/the_suspension_band_flips_the_posture_between_fifty_two_and_forty_eight
    """
    center, _access_a, _access_b, referral_a, at_full_trust = (
        _one_facility_two_accesses_and_a_clean_referral(api)
    )

    updated = fx.update_missed_treatments(
        api, referral_a["id"], 12, center["facility_headers"]
    )
    assert updated["missed_treatment_count"] == 12

    on_the_edge = fx.read_facility(api, center["facility_id"])
    assertions.assert_dialysis_facility(on_the_edge)
    assert on_the_edge["referral_volume_window"] == 1
    assert on_the_edge["raw_missed_count_window"] == 12
    assert on_the_edge["grace_credit_window"] == 0
    assert on_the_edge["adjusted_missed_count_window"] == 12
    assert on_the_edge["same_day_honored_window"] == 0
    assert on_the_edge["partnership_score"] == 52
    assert on_the_edge["partnership_tier"] == "WATCH"
    assert on_the_edge["contract_status"] == "PROBATION"
    assert on_the_edge["version"] > at_full_trust["version"]

    held = fx.read_referral(api, referral_a["id"])
    assertions.assert_referral(held)
    assert held["status"] == "INFO_REQUESTED"
    assert held["hold_reason"] == "FACILITY_POSTURE_HOLD"
    assert held["info_request_count"] == 1
    assert held["missed_treatment_count"] == 12
    assert held["triage_score"] is None
    assert held["triage_variant"] is None
    assert held["urgency"] is None
    assert held["triaged_at"] is None
    assert held["version"] > referral_a["version"]


def test_02_the_thirteenth_missed_treatment_drops_the_score_to_forty_eight_and_closes_triage(api):
    """The second update charges four more points because there is no grace left to lose.

    The tier read in Step A is now `WATCH`, and Step B allows "nothing at all for a `WATCH`
    partner", so thirteen raw misses stand as thirteen adjusted misses: 100 minus 52 is 48.
    That is one
    point below the probation floor, and the PRD sends it straight down — "`ACTIVE →
    SUSPENDED` and `PROBATION → SUSPENDED` both fire when the fresh score is 49 or below."

    The referral is untouched by this second drop even though the suspension cascade is the
    wider one: "**On a drop to `SUSPENDED`**, the same hold applies but the eligible set
    widens to include `SCHEDULED` referrals" — and the referral is already `INFO_REQUESTED`,
    which appears in neither the probation set nor the widened one, so its count stays at the
    one hold it has already taken.

    The metrics view then scales what the facility persisted: "`missed_treatments_per_referral_x100`
    is the raw in-window missed count multiplied by 100 and divided by the in-window referral
    volume, rounded half up to a whole number".

    Intake is never what suspension closes. Submitting the probe referral succeeds and merely
    rescores to the same 48 — the PRD makes the score a pure function of the window, and this
    submission adds volume without adding misses — while it is triage that the posture gate
    stops: "The referring facility's `contract_status` must be `ACTIVE` or `PROBATION`; a
    `SUSPENDED` facility's referrals cannot be triaged and the attempt is refused with
    `ERR_FACILITY_SUSPENDED`."

    The refusal cannot be the surveillance gate wearing the wrong name, because the probe
    referral's access holds a reading well before the clock, and the PRD reserves a different
    identifier for that: "At least one surveillance reading must exist on the referral's
    access with a `reading_at` at or before the clock, otherwise `ERR_INSUFFICIENT_SURVEILLANCE`".
    The posture check is also the earlier of the two — the PRD lists "**Referring facility not
    suspended at triage**, otherwise `ERR_FACILITY_SUSPENDED` (409)." ahead of "**Surveillance
    sufficiency at triage**, otherwise `ERR_INSUFFICIENT_SURVEILLANCE` (422)."

    Design: Corner/cross_cutting_complexity_layers/the_suspension_band_flips_the_posture_between_fifty_two_and_forty_eight
    """
    center, _access_a, access_b, referral_a, _at_full_trust = (
        _one_facility_two_accesses_and_a_clean_referral(api)
    )
    fx.update_missed_treatments(api, referral_a["id"], 12, center["facility_headers"])
    on_probation = fx.read_facility(api, center["facility_id"])
    assert on_probation["partnership_score"] == 52
    assert on_probation["contract_status"] == "PROBATION"
    assert on_probation["partnership_tier"] == "WATCH"

    thirteenth = fx.update_missed_treatments(
        api, referral_a["id"], 13, center["facility_headers"]
    )
    assert thirteenth["missed_treatment_count"] == 13

    suspended = fx.read_facility(api, center["facility_id"])
    assert suspended["referral_volume_window"] == 1
    assert suspended["raw_missed_count_window"] == 13
    assert suspended["grace_credit_window"] == 0
    assert suspended["adjusted_missed_count_window"] == 13
    assert suspended["partnership_score"] == 48
    assert suspended["partnership_tier"] == "WATCH"
    assert suspended["contract_status"] == "SUSPENDED"
    assertions.assert_instant_equals(
        suspended["last_scored_at"], fx.CLOCK_STARTUP_UTC, "last_scored_at"
    )

    still_held_once = fx.read_referral(api, referral_a["id"])
    assert still_held_once["status"] == "INFO_REQUESTED"
    assert still_held_once["hold_reason"] == "FACILITY_POSTURE_HOLD"
    assert still_held_once["info_request_count"] == 1

    metrics = validate_success(
        api.get_facility_partnership_metrics(center["facility_id"], fx.ADMIN)
    )
    assertions.assert_partnership_metrics(metrics)
    assert metrics["raw_missed_count_window"] == 13
    assert metrics["adjusted_missed_count_window"] == 13
    assert metrics["missed_treatments_per_referral_x100"] == 1300
    assert metrics["same_day_honor_rate_pct"] == 0
    assert metrics["contract_status"] == "SUSPENDED"

    probe = fx.seed_referral(
        api,
        access_b["id"],
        center["facility_id"],
        center["facility_headers"],
        suspected_problem="STENOSIS",
        clinical_narrative=PROBE_NARRATIVE,
        missed_treatment_count=0,
    )
    assert probe["status"] == "SUBMITTED"

    unchanged_posture = fx.read_facility(api, center["facility_id"])
    assert unchanged_posture["referral_volume_window"] == 2
    assert unchanged_posture["raw_missed_count_window"] == 13
    assert unchanged_posture["grace_credit_window"] == 0
    assert unchanged_posture["adjusted_missed_count_window"] == 13
    assert unchanged_posture["partnership_score"] == 48
    assert unchanged_posture["contract_status"] == "SUSPENDED"

    refused = api.triage_referral(probe["id"], fx.COORDINATOR)
    validate_error(refused, "ERR_FACILITY_SUSPENDED", 409)
    assert refused.json()["data"]["error_id"] != "ERR_INSUFFICIENT_SURVEILLANCE"

    untriaged = fx.read_referral(api, probe["id"])
    assert untriaged["status"] == "SUBMITTED"
    assert untriaged["triage_score"] is None
    assert untriaged["triage_variant"] is None
    assert untriaged["urgency"] is None
    assert untriaged["triaged_at"] is None
    assert untriaged["version"] == probe["version"]

    assert fx.read_access(api, access_b["id"])["status"] == "IN_USE"
