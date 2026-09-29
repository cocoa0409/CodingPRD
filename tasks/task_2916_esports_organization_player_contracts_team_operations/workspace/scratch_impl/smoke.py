import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:53187"


def call(method, path, role, user, body=None, expect=None):
    url = BASE + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-User-ID", user)
    req.add_header("X-User-Role", role)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = json.loads(exc.read())
    tag = "%s %s -> %s" % (method, path, status)
    if expect is not None and status != expect:
        print("!! UNEXPECTED", tag, json.dumps(payload.get("data"))[:300])
    return status, payload


def d(payload):
    return payload["data"]


fails = []


def check(label, got, want):
    ok = got == want
    print(("  ok  " if ok else "  FAIL") + " %-52s got=%r want=%r" % (label, got, want))
    if not ok:
        fails.append(label)


print("== auth ==")
s, p = call("GET", "/leagues", "", "")
check("missing headers", (s, d(p)["error_id"]), (401, "ERR_UNAUTHENTICATED"))
s, p = call("GET", "/leagues", "Wizard", "u1")
check("unknown role", (s, d(p)["error_id"]), (403, "ERR_UNAUTHORIZED"))
s, p = call("GET", "/leagues", "Scout", "u1")
check("role not on endpoint", (s, d(p)["error_id"]), (403, "ERR_UNAUTHORIZED"))

print("== league / org / player ==")
s, league = call("POST", "/leagues", "LeagueAdmin", "admin1", {
    "name": "Apex League",
    "season_start_at": "2026-07-01T00:00:00.000Z",
    "season_end_at": "2027-06-30T00:00:00.000Z",
    "roster_lock_at": "2027-05-01T00:00:00.000Z",
    "transfer_window_open_at": "2026-07-01T00:00:00.000Z",
    "transfer_window_close_at": "2026-12-31T00:00:00.000Z",
    "min_roster_size": 1, "max_roster_size": 5, "minimum_salary_cents": 1000000,
}, 201)
LID = d(league)["id"]
check("league defaults", (d(league)["player_association_levy_bp"],
                          d(league)["adult_max_weekly_minutes"],
                          d(league)["roster_lock_active"],
                          d(league)["version"]), (250, 2700, False, 1))

s, p = call("POST", "/leagues", "LeagueAdmin", "admin1", {
    "name": "Bad", "season_start_at": "2026-07-01T00:00:00.000Z",
    "season_end_at": "2026-06-01T00:00:00.000Z",
    "roster_lock_at": "2027-05-01T00:00:00.000Z",
    "transfer_window_open_at": "2026-07-01T00:00:00.000Z",
    "transfer_window_close_at": "2026-12-31T00:00:00.000Z"})
check("season end before start", (s, d(p)["error_id"]), (400, "ERR_INVALID_REQUEST"))

s, org = call("POST", "/organizations", "LeagueAdmin", "admin1", {
    "league_id": LID, "name": "Nova Esports", "tax_jurisdiction_code": "US",
    "annual_salary_budget_cents": 50000000}, 201)
OID = d(org)["id"]
check("org counters", (d(org)["committed_salary_cents"], d(org)["uncommitted_salary_cents"],
                      d(org)["active_roster_count"], d(org)["org_prize_share_bp"]),
      (0, 50000000, 0, 3500))

s, p = call("POST", "/organizations", "LeagueAdmin", "admin1", {
    "league_id": "nope", "name": "X", "tax_jurisdiction_code": "US",
    "annual_salary_budget_cents": 1})
check("bad league fk", (s, d(p)["error_id"]), (404, "ERR_LEAGUE_NOT_FOUND"))

s, p = call("GET", "/organizations/" + OID, "GeneralManager", "other-org")
check("not resource owner", (s, d(p)["error_id"]), (403, "ERR_NOT_RESOURCE_OWNER"))
s, p = call("GET", "/organizations/" + OID, "GeneralManager", OID, expect=200)

s, player = call("POST", "/players", "Scout", "scout1", {
    "full_name": "Ada Ryu", "birth_date": "2000-03-04", "region_code": "NA"}, 201)
PID = d(player)["id"]
check("adult derivation", (d(player)["age_years"], d(player)["is_minor"],
                          d(player)["guardian_consent_status"], d(player)["player_status"]),
      (26, False, "NOT_REQUIRED", "PROSPECT"))

s, minor = call("POST", "/players", "Scout", "scout1", {
    "full_name": "Kid Lee", "birth_date": "2011-08-01", "region_code": "EU",
    "education_enrollment_status": "ENROLLED_FULL_TIME"}, 201)
MID = d(minor)["id"]
check("minor derivation", (d(minor)["age_years"], d(minor)["is_minor"],
                           d(minor)["guardian_consent_status"]), (15, True, "REQUIRED"))

print("== offer negotiation ==")
offer_body = {"organization_id": OID, "player_id": PID, "base_salary_cents": 12000000,
              "term_months": 12, "prize_split_player_pct_bp": 5000,
              "streaming_hours_per_week": 10, "tax_residency_code": "US"}
s, p = call("POST", "/contract-offers", "GeneralManager", "someone-else", offer_body)
check("offer ownership", (s, d(p)["error_id"]), (403, "ERR_NOT_RESOURCE_OWNER"))
s, offer = call("POST", "/contract-offers", "GeneralManager", OID, offer_body, 201)
OFID = d(offer)["id"]
check("offer initial", (d(offer)["offer_status"], d(offer)["round_number"],
                        d(offer)["sent_at"], d(offer)["expires_at"],
                        d(offer)["buyout_multiplier_bp"]),
      ("SENT", 1, "2026-08-01T00:00:00.000Z", "2026-08-04T00:00:00.000Z", 5000))

low = dict(offer_body, base_salary_cents=10)
s, p = call("POST", "/contract-offers", "GeneralManager", OID, low)
check("min salary", (s, d(p)["error_id"]), (422, "ERR_BELOW_MINIMUM_SALARY"))

s, p = call("POST", "/contract-offers/%s/counter" % OFID, "PlayerAgent", "wrong-player",
            {"counter_base_salary_cents": 1, "counter_prize_split_player_pct_bp": 1,
             "counter_streaming_hours_per_week": 1})
check("counter ownership", (s, d(p)["error_id"]), (403, "ERR_NOT_RESOURCE_OWNER"))

s, p = call("POST", "/contract-offers/%s/counter" % OFID, "PlayerAgent", PID,
            {"counter_base_salary_cents": 13000000,
             "counter_prize_split_player_pct_bp": 5500,
             "counter_streaming_hours_per_week": 8}, 200)
check("countered", (d(p)["offer_status"], d(p)["round_number"],
                    d(p)["counter_base_salary_cents"]), ("COUNTERED", 1, 13000000))

s, p = call("POST", "/contract-offers/%s/revise" % OFID, "GeneralManager", OID,
            {"base_salary_cents": 12500000, "prize_split_player_pct_bp": 5200,
             "streaming_hours_per_week": 9}, 200)
check("revised", (d(p)["offer_status"], d(p)["round_number"],
                  d(p)["counter_base_salary_cents"], d(p)["base_salary_cents"]),
      ("SENT", 2, None, 12500000))

print("== acceptance ==")
s, contract = call("POST", "/contract-offers/%s/accept" % OFID, "PlayerAgent", PID, {}, 201)
CID = d(contract)["id"]
# effective_at = 2026-08-01, season_end 2027-06-30 -> 333 whole days
# 12500000 * 333 / 365 = 11404109.589 -> 11404110
check("provisional charge", d(contract)["provisional_cap_charge_cents"], 11404110)
check("final charge", d(contract)["final_cap_charge_cents"], 12500000)
check("ends_at (12 * 30d)", d(contract)["ends_at"], "2027-07-27T00:00:00.000Z")
check("contract dims", (d(contract)["contract_status"], d(contract)["obligation_status"],
                        d(contract)["signed_by_user_id"]), ("ACTIVE", "COMPLIANT", PID))

s, p = call("GET", "/players/" + PID, "LeagueAdmin", "admin1", expect=200)
check("player signed", (d(p)["player_status"], d(p)["current_organization_id"]),
      ("SIGNED", OID))
s, p = call("GET", "/organizations/" + OID, "LeagueAdmin", "admin1", expect=200)
check("org committed", (d(p)["committed_salary_cents"], d(p)["uncommitted_salary_cents"],
                        d(p)["active_roster_count"]), (11404110, 38595890, 1))
check("budget identity",
      d(p)["committed_salary_cents"] + d(p)["uncommitted_salary_cents"],
      d(p)["annual_salary_budget_cents"])

s, p = call("GET", "/organizations/%s/cap-summary" % OID, "LeagueAdmin", "admin1", expect=200)
check("cap summary variants", (d(p)["provisional_committed_cents"],
                              d(p)["final_committed_cents"]), (11404110, 12500000))

print("== minor gates ==")
minor_offer = {"organization_id": OID, "player_id": MID, "base_salary_cents": 5000000,
               "term_months": 6, "prize_split_player_pct_bp": 4000,
               "streaming_hours_per_week": 5, "tax_residency_code": "DE"}
s, mo = call("POST", "/contract-offers", "GeneralManager", OID, minor_offer, 201)
MOFID = d(mo)["id"]
s, p = call("POST", "/contract-offers/%s/accept" % MOFID, "PlayerAgent", MID, {})
check("guardian consent gate", (s, d(p)["error_id"]), (422, "ERR_GUARDIAN_CONSENT_REQUIRED"))
s, p = call("POST", "/players/%s/guardian-consent" % MID, "GuardianRepresentative", MID,
            {"guardian_name": "Lee Sr", "guardian_email": "lee@example.com",
             "guardian_weekly_cap_minutes": 900}, 200)
check("consent granted", d(p)["guardian_consent_status"], "GRANTED")
s, p = call("POST", "/contract-offers/%s/accept" % MOFID, "PlayerAgent", MID, {})
check("player already signed check n/a; roster ok", s, 201)
MCID = d(p)["id"]

print("== facilities and practice ==")
s, house = call("POST", "/organizations/%s/team-houses" % OID, "OpsManager", OID,
                {"name": "Nova House", "timezone": "America/Los_Angeles",
                 "turnaround_buffer_minutes": 30, "concurrent_seat_capacity": 2}, 201)
THID = d(house)["id"]
s, block = call("POST", "/practice-blocks", "CoachingStaff", "coach1",
                {"organization_id": OID, "team_house_id": THID, "block_type": "SCRIM",
                 "starts_at": "2026-08-01T10:00:00.000Z",
                 "ends_at": "2026-08-01T13:00:00.000Z",
                 "participant_player_ids": [PID]}, 201)
BID = d(block)["id"]
check("duration", d(block)["duration_minutes"], 180)

s, p = call("POST", "/practice-blocks", "CoachingStaff", "coach1",
            {"organization_id": OID, "team_house_id": THID, "block_type": "REVIEW",
             "starts_at": "2026-08-01T13:20:00.000Z",
             "ends_at": "2026-08-01T14:00:00.000Z",
             "participant_player_ids": [PID]})
check("room buffer conflict", (s, d(p)["error_id"]), (409, "ERR_FACILITY_SLOT_CONFLICT"))
s, p = call("POST", "/practice-blocks", "CoachingStaff", "coach1",
            {"organization_id": OID, "team_house_id": THID, "block_type": "REVIEW",
             "starts_at": "2026-08-01T13:30:00.000Z",
             "ends_at": "2026-08-01T14:00:00.000Z",
             "participant_player_ids": [PID]}, 201)
BID2 = d(p)["id"]
check("exactly one buffer later is allowed", s, 201)

s, p = call("POST", "/practice-blocks", "CoachingStaff", "coach1",
            {"organization_id": OID, "team_house_id": THID, "block_type": "SCRIM",
             "starts_at": "2026-08-02T10:00:00.000Z",
             "ends_at": "2026-08-02T20:00:00.000Z",
             "participant_player_ids": [MID]})
check("education reservation decisive", (s, d(p)["error_id"]),
      (422, "ERR_EDUCATION_HOURS_RESERVED"))
s, p = call("POST", "/practice-blocks", "CoachingStaff", "coach1",
            {"organization_id": OID, "team_house_id": THID, "block_type": "SCRIM",
             "starts_at": "2026-08-02T02:00:00.000Z",
             "ends_at": "2026-08-02T19:00:00.000Z",
             "participant_player_ids": [MID]})
check("plain weekly cap", (s, d(p)["error_id"]), (422, "ERR_WEEKLY_HOUR_CAP_EXCEEDED"))

s, p = call("POST", "/practice-blocks", "CoachingStaff", "coach1",
            {"organization_id": OID, "team_house_id": THID, "block_type": "SCRIM",
             "starts_at": "2026-08-02T10:00:00.000Z",
             "ends_at": "2026-08-02T11:00:00.000Z",
             "participant_player_ids": [PID, MID, "x"]})
check("participant fk", (s, d(p)["error_id"]), (404, "ERR_PLAYER_NOT_FOUND"))
s, p = call("POST", "/practice-blocks", "CoachingStaff", "coach1",
            {"organization_id": OID, "team_house_id": THID, "block_type": "SCRIM",
             "starts_at": "2026-08-02T10:00:00.000Z",
             "ends_at": "2026-08-02T11:00:00.000Z",
             "participant_player_ids": [PID, PID]})
check("duplicate participants", (s, d(p)["error_id"]), (400, "ERR_INVALID_REQUEST"))

s, p = call("POST", "/practice-blocks/%s/complete" % BID, "CoachingStaff", "coach1", {})
check("not finished", (s, d(p)["error_id"]), (409, "ERR_BLOCK_NOT_FINISHED"))
s, p = call("POST", "/_clock/set_current_utc", "LeagueAdmin", "admin1",
            {"current_utc": "2026-08-01T14:00:00.000Z"}, 200)
check("clock echo", d(p)["current_utc"], "2026-08-01T14:00:00.000Z")
s, p = call("POST", "/practice-blocks/%s/complete" % BID, "CoachingStaff", "coach1",
            {"coach_note": "good scrim"}, 200)
check("held", d(p)["block_status"], "HELD")
s, p = call("GET", "/contracts/" + CID, "LeagueAdmin", "admin1", expect=200)
# practice 180/2700 = .0666*.5 = .03333 ; load 0 ; stream 0 -> 3.33 -> 3
check("burnout after block", (d(p)["season_practice_minutes"], d(p)["burnout_score"],
                             d(p)["obligation_status"]), (180, 3, "COMPLIANT"))

print("== wellness escalation ==")
s, p = call("POST", "/contracts/%s/wellness-report" % CID, "PerformanceSupport", "ps1",
            {"last_self_reported_load": 10, "reported_streaming_minutes_7d": 600}, 200)
# .5*180/2700 + .3*1 + .2*min(1,600/600) = .03333+.3+.2 = .5333 -> 53
check("warn not yet", (d(p)["burnout_score"], d(p)["obligation_status"]), (53, "COMPLIANT"))
s, p = call("GET", "/contracts/%s/obligation-summary" % CID, "LeagueAdmin", "admin1", 200)
check("summary keys", sorted(d(p).keys()),
      sorted(["contract_id", "obligation_status", "burnout_score", "season_burnout_score",
              "scheduled_minutes_this_week", "streaming_minutes_this_week", "cap_minutes",
              "provisional_cap_charge_cents", "final_cap_charge_cents",
              "wellness_hold_until"]))
check("weekly arithmetic", (d(p)["scheduled_minutes_this_week"],
                            d(p)["streaming_minutes_this_week"], d(p)["cap_minutes"]),
      (210, 0, 2700))

print("== sponsorship ==")
s, deal = call("POST", "/sponsorship-deals", "SponsorshipManager", OID,
               {"organization_id": OID, "sponsor_name": "KeyCo",
                "exclusivity_category": "PERIPHERALS", "total_fee_cents": 1000,
                "deliverable_count_required": 3,
                "starts_at": "2026-08-01T00:00:00.000Z",
                "ends_at": "2026-12-01T00:00:00.000Z"}, 201)
DID = d(deal)["id"]
check("deal draft", (d(deal)["deal_status"], d(deal)["minor_permitted"],
                     d(deal)["assigned_count"], d(deal)["per_deliverable_fee_cents"]),
      ("DRAFT", True, 0, 333))
s, p = call("POST", "/sponsorship-deals/%s/deliverables" % DID, "SponsorshipManager", OID,
            {"contract_id": CID, "deliverable_type": "SOCIAL_POST",
             "due_at": "2026-09-01T00:00:00.000Z", "expected_deal_version": 1})
check("deal must be active", (s, d(p)["error_id"]), (409, "ERR_DEAL_NOT_ACTIVE"))
s, p = call("POST", "/sponsorship-deals/%s/activate" % DID, "SponsorshipManager", OID, {}, 200)
DVER = d(p)["version"]
check("activated", (d(p)["deal_status"], DVER), ("ACTIVE", 2))
s, p = call("POST", "/sponsorship-deals/%s/deliverables" % DID, "SponsorshipManager", OID,
            {"contract_id": CID, "deliverable_type": "SOCIAL_POST",
             "due_at": "2026-09-01T00:00:00.000Z", "expected_deal_version": 1})
check("stale deal version", (s, d(p)["error_id"]), (412, "ERR_DEAL_VERSION_STALE"))
s, p = call("POST", "/sponsorship-deals/%s/deliverables" % DID, "SponsorshipManager", OID,
            {"contract_id": CID, "deliverable_type": "SOCIAL_POST",
             "due_at": "2027-01-01T00:00:00.000Z", "expected_deal_version": DVER})
check("due outside deal", (s, d(p)["error_id"]), (422, "ERR_DELIVERABLE_DUE_OUTSIDE_DEAL"))
assign_ids = []
for i in range(3):
    s, dv = call("GET", "/sponsorship-deals/" + DID, "SponsorshipManager", OID, expect=200)
    s, p = call("POST", "/sponsorship-deals/%s/deliverables" % DID, "SponsorshipManager",
                OID, {"contract_id": CID, "deliverable_type": "SOCIAL_POST",
                      "due_at": "2026-09-01T00:00:00.000Z",
                      "expected_deal_version": d(dv)["version"]}, 201)
    assign_ids.append(d(p)["id"])
    check("fee share %d" % i, d(p)["fee_share_cents"], 333)
s, dv = call("GET", "/sponsorship-deals/" + DID, "SponsorshipManager", OID, expect=200)
s, p = call("POST", "/sponsorship-deals/%s/deliverables" % DID, "SponsorshipManager", OID,
            {"contract_id": CID, "deliverable_type": "SOCIAL_POST",
             "due_at": "2026-09-01T00:00:00.000Z",
             "expected_deal_version": d(dv)["version"]})
check("quota", (s, d(p)["error_id"]), (422, "ERR_DELIVERABLE_QUOTA_EXCEEDED"))

for idx, aid in enumerate(assign_ids):
    s, p = call("POST", "/deliverable-assignments/%s/submit" % aid, "PlayerAgent", PID,
                {"submission_note": "done"}, 200)
    if idx == 0:
        s, p = call("POST", "/deliverable-assignments/%s/review" % aid,
                    "SponsorshipManager", OID, {"decision": "REJECT"}, 200)
        check("rejected tally", (d(p)["assignment_status"], d(p)["rejection_count"]),
              ("REJECTED", 1))
        s, p = call("POST", "/deliverable-assignments/%s/submit" % aid, "PlayerAgent", PID,
                    {}, 200)
    s, p = call("POST", "/deliverable-assignments/%s/review" % aid, "SponsorshipManager",
                OID, {"decision": "APPROVE"}, 200)
s, p = call("GET", "/sponsorship-deals/" + DID, "SponsorshipManager", OID, expect=200)
check("fulfilled + residue", (d(p)["deal_status"], d(p)["approved_count"],
                              d(p)["earned_fee_cents"]), ("FULFILLED", 3, 1000))

print("== prize waterfall ==")
s, dist = call("POST", "/prize-distributions", "FinanceOfficer", "fin1",
               {"organization_id": OID, "league_id": LID, "tournament_name": "Summer Cup",
                "placement": 1, "gross_prize_cents": 1000000,
                "tournament_end_at": "2026-08-01T12:00:00.000Z"}, 201)
PDID = d(dist)["id"]
check("draft ledger", (d(dist)["unallocated_cents"], d(dist)["allocated_cents"]),
      (1000000, 0))
s, p = call("POST", "/prize-distributions/%s/calculate" % PDID, "FinanceOfficer", "fin1",
            {}, 200)
# levy 250bp of 1,000,000 = 25000 -> distributable 975000
# org share 3500bp of 975000 = 341250 -> pool 633750
# eligible: adult 5200bp, minor 4000bp -> total 9200
# floor adult = 633750*5200//9200 = 358119 ; floor minor = 633750*4000//9200 = 275543
# sum 633662, remainder 88 -> to adult (largest floor) = 358207
check("levy/org/pool", (d(p)["association_levy_cents"], d(p)["org_share_cents"],
                        d(p)["allocated_cents"], d(p)["unallocated_cents"]),
      (25000, 341250, 633750, 0))
check("ledger identity",
      d(p)["gross_prize_cents"],
      d(p)["association_levy_cents"] + d(p)["org_share_cents"] + d(p)["allocated_cents"]
      + d(p)["unallocated_cents"])
s, p = call("GET", "/prize-distributions/%s/allocations" % PDID, "FinanceOfficer", "fin1",
            expect=200)
rows = {r["contract_id"]: r for r in d(p)}
check("remainder row", rows[CID]["gross_share_cents"], 358207)
check("other row", rows[MCID]["gross_share_cents"], 275543)
check("resident withholding", (rows[CID]["withholding_rate_bp"],
                               rows[CID]["withholding_cents"]), (1500, 53731))
check("nonresident + minor escrow", (rows[MCID]["withholding_rate_bp"],
                                    rows[MCID]["withholding_cents"],
                                    rows[MCID]["escrow_holdback_cents"]),
      (3000, 82663, 27554))
check("net", rows[CID]["net_cents"], 358207 - 53731)
s, p = call("POST", "/prize-distributions/%s/approve" % PDID, "LeagueAdmin", "fin1", {})
check("segregation", (s, d(p)["error_id"]), (403, "ERR_SEGREGATION_OF_DUTIES"))
s, p = call("POST", "/prize-distributions/%s/approve" % PDID, "LeagueAdmin", "admin1",
            {}, 200)
check("approved", d(p)["distribution_status"], "APPROVED")
s, p = call("GET", "/organizations/" + OID, "LeagueAdmin", "admin1", expect=200)
check("prize payable", d(p)["prize_payable_cents"], 341250)

print("== roster move ==")
s, p = call("GET", "/organizations/" + OID, "LeagueAdmin", "admin1", expect=200)
OVER = d(p)["version"]
s, p = call("POST", "/roster-moves", "GeneralManager", OID,
            {"organization_id": OID, "player_id": PID, "move_type": "RELEASE",
             "contract_id": CID, "expected_organization_version": OVER + 5})
check("stale org version", (s, d(p)["error_id"]), (412, "ERR_ORGANIZATION_VERSION_STALE"))
s, move = call("POST", "/roster-moves", "GeneralManager", OID,
               {"organization_id": OID, "player_id": PID, "move_type": "RELEASE",
                "contract_id": CID, "expected_organization_version": OVER}, 201)
RMID = d(move)["id"]
check("pending money zero", (d(move)["move_status"], d(move)["released_cap_cents"],
                             d(move)["requested_by_user_id"]), ("PENDING", 0, OID))
s, p = call("POST", "/roster-moves/%s/decision" % RMID, "LeagueAdmin", OID,
            {"decision": "APPROVE"})
check("move segregation", (s, d(p)["error_id"]), (403, "ERR_SEGREGATION_OF_DUTIES"))
s, p = call("POST", "/roster-moves/%s/decision" % RMID, "LeagueAdmin", "admin1",
            {"decision": "APPROVE"}, 200)
check("approved", d(p)["move_status"], "APPROVED")
s, p = call("POST", "/roster-moves/%s/execute" % RMID, "GeneralManager", OID, {}, 200)
check("release settlement", (d(p)["move_status"], d(p)["released_cap_cents"],
                             d(p)["buyout_credit_cents"], d(p)["commission_tier_bp"]),
      ("EXECUTED", 11404110, 0, 0))
s, p = call("GET", "/contracts/" + CID, "LeagueAdmin", "admin1", expect=200)
check("terminated", d(p)["contract_status"], "TERMINATED")
s, p = call("GET", "/players/" + PID, "LeagueAdmin", "admin1", expect=200)
check("free agent", (d(p)["player_status"], d(p)["current_organization_id"],
                     d(p)["free_agency_window_ends_at"],
                     d(p)["last_release_organization_id"]),
      ("FREE_AGENT", None, "2026-08-15T14:00:00.000Z", OID))
s, p = call("GET", "/deliverable-assignments?contract_id=" + CID, "SponsorshipManager", OID,
            expect=200)
check("assignments voided", sorted({a["assignment_status"] for a in d(p)}), ["VOIDED"])
s, p = call("GET", "/sponsorship-deals/" + DID, "SponsorshipManager", OID, expect=200)
check("deal reverted", (d(p)["deal_status"], d(p)["assigned_count"],
                        d(p)["approved_count"]), ("ACTIVE", 0, 0))
s, p = call("GET", "/organizations/" + OID, "LeagueAdmin", "admin1", expect=200)
check("committed released", (d(p)["committed_salary_cents"], d(p)["active_roster_count"]),
      (4561644, 1))
s, p = call("POST", "/roster-moves/%s/reverse" % RMID, "LeagueAdmin", "admin1",
            {"reversal_reason": "filed in error"}, 200)
check("reversed", (d(p)["move_status"], d(p)["released_cap_cents"]), ("REVERSED", 0))
s, p = call("GET", "/organizations/" + OID, "LeagueAdmin", "admin1", expect=200)
check("committed restored", (d(p)["committed_salary_cents"], d(p)["active_roster_count"]),
      (11404110 + 4561644, 2))
s, p = call("GET", "/players/" + PID, "LeagueAdmin", "admin1", expect=200)
check("player restored", (d(p)["player_status"], d(p)["current_organization_id"],
                          d(p)["free_agency_window_ends_at"]), ("SIGNED", OID, None))
s, p = call("POST", "/roster-moves/%s/reverse" % RMID, "LeagueAdmin", "admin1",
            {"reversal_reason": "again"})
check("not executed", (s, d(p)["error_id"]), (409, "ERR_MOVE_NOT_EXECUTED"))

print("== pagination + 404 ==")
s, p = call("GET", "/leagues?limit=500", "LeagueAdmin", "admin1")
check("limit range", (s, d(p)["error_id"]), (400, "ERR_INVALID_REQUEST"))
s, p = call("GET", "/leagues?limit=1&offset=0", "LeagueAdmin", "admin1", expect=200)
check("meta", (p["meta"]["limit"], p["meta"]["offset"], p["meta"]["total_count"],
               p["meta"]["has_more"], p["response_type"]), (1, 0, 1, False, "array"))
s, p = call("GET", "/contract-offers/does-not-exist", "LeagueAdmin", "admin1")
check("offer 404", (s, d(p)["error_id"]), (404, "ERR_OFFER_NOT_FOUND"))
s, p = call("GET", "/organizations/nope/team-houses", "OpsManager", OID)
check("left-to-right path", (s, d(p)["error_id"]), (404, "ERR_ORGANIZATION_NOT_FOUND"))

print()
print("FAILURES:", len(fails))
for f in fails:
    print(" -", f)
