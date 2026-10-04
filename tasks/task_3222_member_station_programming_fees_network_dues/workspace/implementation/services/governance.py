"""Vote eligibility projections, weighted tallies, standings and the pool."""
from core import config as C
from core.base import new_record, touch
from core.errors import ApiError
from core.store import projection_eligible
from services import scoring

MEMBERSHIP_CLASS_VOTE_WEIGHT = {
    "CLASS_A": 3,
    "CLASS_B": 2,
    "CLASS_C": 1,
    "CLASS_D": 0,
}
NO_VOTE_FLOOR_DIVISOR = 2

STATION_TIER_SHARE_CENTS = 120000
WATERFALL_TIER_ORDER = ["CLASS_A", "CLASS_B", "CLASS_C", "CLASS_D"]


# --- projections -------------------------------------------------------------
def upsert_projection(store, station, fiscal_year=None):
    """Mirror the station's derived dues-vote eligibility into its row."""
    fy = int(fiscal_year or C.now().year)
    status = station.get("eligibility_status")
    member = status in ("ELIGIBLE", "PROBATION")
    if member and station.get("eligible_from") is None:
        station["eligible_from"] = C.iso(C.now())
    eligible = projection_eligible(station)
    station["dues_vote_eligible"] = bool(eligible)
    now_iso = C.iso(C.now())
    row = None
    for candidate in store.projections.values():
        if candidate.get("station_id") == station["id"] and candidate.get("fiscal_year") == fy:
            row = candidate
            break
    if row is None:
        row = new_record(
            "DuesVoteEligibilityProjection",
            common=False,
            station_id=station["id"],
            fiscal_year=fy,
            dues_vote_eligible=bool(eligible),
            eligible_from=station.get("eligible_from"),
            last_projected_at=now_iso,
        )
        store.put("projections", row)
    else:
        row["dues_vote_eligible"] = bool(eligible)
        row["eligible_from"] = station.get("eligible_from")
        row["last_projected_at"] = now_iso
    return row


def recompute_quorum_denominators(store):
    """Every live proposal recomputes how many stations its quorum needs."""
    count = store.eligible_voter_count()
    for proposal in store.proposals.values():
        if proposal.get("proposal_status") in ("OPEN", "TABLED", "PASSED"):
            proposal["eligible_station_count"] = count
    return count


def zero_arrears_and_reproject(store, station):
    """Seating a station zeroes its arrears and recomputes its projection."""
    station["dues_arrears_cents"] = 0
    touch(station)
    upsert_projection(store, station)
    return station


# --- weighted vote scoring ---------------------------------------------------
def base_weight(station):
    cls = (station or {}).get("membership_class") or "CLASS_D"
    return MEMBERSHIP_CLASS_VOTE_WEIGHT.get(cls, 0)


def recorded_weight_for(choice, weight):
    if choice == "YES":
        return int(weight)
    if weight > 0:
        return max(1, (int(weight) + 1) // NO_VOTE_FLOOR_DIVISOR)
    return 0


def recompute_vote_weights(store, proposal):
    """Re-derive every recorded row's weight and the proposal's three tallies."""
    rows = [
        v for v in store.votes.values()
        if v.get("parent_proposal_id") == proposal["id"]
    ]
    for vote in rows:
        if vote.get("vote_status") != "RECORDED":
            continue
        station = store.member_stations.get(vote.get("station_id"))
        vote["recorded_weight"] = recorded_weight_for(
            vote.get("vote_choice"), base_weight(station)
        )
    yes = 0
    no = 0
    stations = set()
    for vote in rows:
        if vote.get("vote_status") != "RECORDED":
            continue
        weight = int(vote.get("recorded_weight") or 0)
        if vote.get("vote_choice") == "YES":
            yes += weight
        else:
            no += weight
        stations.add(vote.get("station_id"))
    proposal["yes_votes"] = yes
    proposal["no_votes"] = no
    proposal["votes_cast_count"] = len(stations)
    return proposal


def quorum_met(proposal):
    return int(proposal.get("votes_cast_count") or 0) >= int(
        proposal.get("quorum_required_votes") or 0
    )


def proposal_passes(proposal):
    return quorum_met(proposal) and int(proposal.get("yes_votes") or 0) > int(
        proposal.get("no_votes") or 0
    )


# --- network_dues_pool_allocation -------------------------------------------
def selector_key(assessment, station):
    cls = (station or {}).get("membership_class") or "CLASS_D"
    try:
        cls_rank = WATERFALL_TIER_ORDER.index(cls)
    except ValueError:
        cls_rank = len(WATERFALL_TIER_ORDER)
    return (
        cls_rank,
        -float((station or {}).get("operations_score") or 0),
        -int((station or {}).get("dues_arrears_cents") or 0),
        (station or {}).get("created_at") or "",
    )


def eligible_for_pool(store, batch):
    out = []
    for assessment in batch:
        station = store.member_stations.get(assessment.get("station_id"))
        if station is None:
            continue
        if station.get("eligibility_status") in ("ELIGIBLE", "PROBATION"):
            out.append((assessment, station))
    return out


def allocate_pool(store, batch, total_pot_cents, fiscal_year=None):
    """Flat tier share first, then the remainder in whole cents by rank.

    A negative remainder is refused outright rather than scaled down.
    """
    pairs = eligible_for_pool(store, batch)
    remainder = int(total_pot_cents) - STATION_TIER_SHARE_CENTS * len(pairs)
    if remainder < 0:
        raise ApiError(
            "ERR_POOL_OVER_ALLOCATED",
            "the pool cannot be distributed without exceeding it",
        )
    pairs.sort(key=lambda pair: selector_key(pair[0], pair[1]))
    for rank, (assessment, _station) in enumerate(pairs):
        assessment["allocated_dues_cents"] = STATION_TIER_SHARE_CENTS + (
            1 if rank < remainder else 0
        )
        assessment["total_pot_cents"] = int(total_pot_cents)
        if fiscal_year is not None:
            assessment["fiscal_year"] = int(fiscal_year)
    return [pair[0] for pair in pairs]


# --- board seat allocation ---------------------------------------------------
def fill_seat_for_candidate(store, seat, candidate):
    """VACANT -> FILLED, then zero the seated station's arrears and reproject."""
    from datetime import timedelta
    awarded_end = seat.get("term_end")
    if awarded_end is None or C.parse_dt(awarded_end) is None:
        awarded_end = C.iso(C.now() + timedelta(days=730))
    seat["station_id"] = candidate.get("station_id")
    seat["seat_status"] = "FILLED"
    seat["term_start"] = C.iso(C.now())
    seat["term_end"] = awarded_end
    touch(seat)
    station = store.member_stations.get(candidate.get("station_id"))
    if station is not None:
        zero_arrears_and_reproject(store, station)
    return seat


def candidate_rank_key(candidate):
    """votes DESC, then the seat's board_rank ASC as the tie-break."""
    return (
        -int(candidate.get("votes_recorded") or 0),
        int(candidate.get("_board_rank") or 0),
    )


def rank_qualified(store, election):
    """Rank the election's QUALIFIED candidacies and pair them to region seats."""
    rows = [
        c for c in store.candidates.values()
        if c.get("parent_election_id") == election["id"]
        and c.get("candidate_status") == "QUALIFIED"
    ]
    seats = sorted(
        [s for s in store.seats.values()
         if s.get("board_region") == election.get("board_region")],
        key=lambda s: int(s.get("board_rank") or 0),
    )
    for index, candidate in enumerate(rows):
        candidate["_board_rank"] = index
        candidate["_seat_id"] = seats[index]["id"] if index < len(seats) else None
    rows.sort(key=candidate_rank_key)
    return rows


def standings_rows(store):
    """member_station_standings: dense rank over the four-key ranking key."""
    return scoring.standings(store)


def cost_efficiency_candidate(store, requesting_station_id):
    rows = standings_rows(store)
    for station, _rank in rows:
        if station["id"] == requesting_station_id:
            continue
        return station
    raise ApiError("ERR_NO_ELIGIBLE_STATION_CAUSE")