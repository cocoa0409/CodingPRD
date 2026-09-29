#!/usr/bin/env bash
set -uo pipefail
B="http://127.0.0.1:41287"
AD=(-H "X-User-ID: admin1" -H "X-User-Role: LeagueAdmin" -H "Content-Type: application/json")
FIN=(-H "X-User-ID: fin1" -H "X-User-Role: FinanceOfficer" -H "Content-Type: application/json")
SC=(-H "X-User-ID: scout1" -H "X-User-Role: Scout" -H "Content-Type: application/json")
CO=(-H "X-User-ID: coach1" -H "X-User-Role: CoachingStaff" -H "Content-Type: application/json")
PS=(-H "X-User-ID: ps1" -H "X-User-Role: PerformanceSupport" -H "Content-Type: application/json")

jqv() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval('d'+'$1'))"; }

echo "--- unauthenticated"
curl -s "$B/leagues" | python3 -m json.tool | head -12

echo "--- create league"
L=$(curl -s -X POST "$B/leagues" "${AD[@]}" -d '{"name":"Apex League","season_start_at":"2026-07-01T00:00:00.000Z","season_end_at":"2027-06-30T00:00:00.000Z","roster_lock_at":"2027-05-01T00:00:00.000Z","transfer_window_open_at":"2026-07-01T00:00:00.000Z","transfer_window_close_at":"2026-12-31T00:00:00.000Z","min_roster_size":1,"max_roster_size":5,"minimum_salary_cents":1000000}')
echo "$L" | python3 -m json.tool | head -40
LID=$(echo "$L" | jqv "['data']['id']")

echo "--- create organization"
O=$(curl -s -X POST "$B/organizations" "${AD[@]}" -d "{\"league_id\":\"$LID\",\"name\":\"Nova Esports\",\"tax_jurisdiction_code\":\"US\",\"annual_salary_budget_cents\":50000000}")
echo "$O" | python3 -m json.tool
OID=$(echo "$O" | jqv "['data']['id']")
OVER=$(echo "$O" | jqv "['data']['version']")
GM=(-H "X-User-ID: $OID" -H "X-User-Role: GeneralManager" -H "Content-Type: application/json")
OM=(-H "X-User-ID: $OID" -H "X-User-Role: OpsManager" -H "Content-Type: application/json")
SM=(-H "X-User-ID: $OID" -H "X-User-Role: SponsorshipManager" -H "Content-Type: application/json")

echo "--- create player (adult)"
P=$(curl -s -X POST "$B/players" "${SC[@]}" -d '{"full_name":"Ada Ryu","birth_date":"2000-03-04","region_code":"NA"}')
echo "$P" | python3 -m json.tool
PID=$(echo "$P" | jqv "['data']['id']")
AG=(-H "X-User-ID: $PID" -H "X-User-Role: PlayerAgent" -H "Content-Type: application/json")

echo "--- wrong owner (other org GM reads org)"
curl -s "$B/organizations/$OID" -H "X-User-ID: someoneelse" -H "X-User-Role: GeneralManager" | python3 -m json.tool | tail -8

echo "--- send offer"
OF=$(curl -s -X POST "$B/contract-offers" "${GM[@]}" -d "{\"organization_id\":\"$OID\",\"player_id\":\"$PID\",\"base_salary_cents\":12000000,\"term_months\":12,\"prize_split_player_pct_bp\":5000,\"streaming_hours_per_week\":10,\"tax_residency_code\":\"US\"}")
echo "$OF" | python3 -m json.tool
OFID=$(echo "$OF" | jqv "['data']['id']")

echo "--- below minimum salary"
curl -s -X POST "$B/contract-offers" "${GM[@]}" -d "{\"organization_id\":\"$OID\",\"player_id\":\"$PID\",\"base_salary_cents\":10,\"term_months\":12,\"prize_split_player_pct_bp\":5000,\"streaming_hours_per_week\":10,\"tax_residency_code\":\"US\"}" | jqv "['data']"

echo "--- counter then revise"
curl -s -X POST "$B/contract-offers/$OFID/counter" "${AG[@]}" -d '{"counter_base_salary_cents":13000000,"counter_prize_split_player_pct_bp":5500,"counter_streaming_hours_per_week":8}' | jqv "['data']['offer_status'],d['data']['round_number']"
curl -s -X POST "$B/contract-offers/$OFID/revise" "${GM[@]}" -d '{"base_salary_cents":12500000,"prize_split_player_pct_bp":5200,"streaming_hours_per_week":9}' | jqv "['data']['offer_status'],d['data']['round_number'],d['data']['counter_base_salary_cents']"

echo "--- accept -> contract"
C=$(curl -s -X POST "$B/contract-offers/$OFID/accept" "${AG[@]}" -d '{}')
echo "$C" | python3 -m json.tool
CID=$(echo "$C" | jqv "['data']['id']")

echo "--- cap summary"
curl -s "$B/organizations/$OID/cap-summary" "${AD[@]}" | python3 -m json.tool

echo "--- team house + practice block"
TH=$(curl -s -X POST "$B/organizations/$OID/team-houses" "${OM[@]}" -d '{"name":"Nova House","timezone":"America/Los_Angeles","turnaround_buffer_minutes":30,"concurrent_seat_capacity":5}')
THID=$(echo "$TH" | jqv "['data']['id']")
echo "$TH" | jqv "['data']"
BK=$(curl -s -X POST "$B/practice-blocks" "${CO[@]}" -d "{\"organization_id\":\"$OID\",\"team_house_id\":\"$THID\",\"block_type\":\"SCRIM\",\"starts_at\":\"2026-08-01T10:00:00.000Z\",\"ends_at\":\"2026-08-01T13:00:00.000Z\",\"participant_player_ids\":[\"$PID\"]}")
echo "$BK" | jqv "['data']"
BKID=$(echo "$BK" | jqv "['data']['id']")

echo "--- room conflict (inside 30-minute buffer)"
curl -s -X POST "$B/practice-blocks" "${CO[@]}" -d "{\"organization_id\":\"$OID\",\"team_house_id\":\"$THID\",\"block_type\":\"REVIEW\",\"starts_at\":\"2026-08-01T13:20:00.000Z\",\"ends_at\":\"2026-08-01T14:00:00.000Z\",\"participant_player_ids\":[\"$PID\"]}" | jqv "['data']"

echo "--- complete too early, then move clock and complete"
curl -s -X POST "$B/practice-blocks/$BKID/complete" "${CO[@]}" -d '{}' | jqv "['data']"
curl -s -X POST "$B/_clock/set_current_utc" "${AD[@]}" -d '{"current_utc":"2026-08-01T14:00:00.000Z"}' | jqv "['data']"
curl -s -X POST "$B/practice-blocks/$BKID/complete" "${CO[@]}" -d '{"coach_note":"good scrim"}' | jqv "['data']['block_status']"
curl -s "$B/contracts/$CID" "${AD[@]}" | jqv "['data']['season_practice_minutes'],d['data']['burnout_score'],d['data']['obligation_status']"

echo "--- wellness report escalating to BREACH"
curl -s -X POST "$B/contracts/$CID/wellness-report" "${PS[@]}" -d '{"last_self_reported_load":10,"reported_streaming_minutes_7d":600}' | jqv "['data']['burnout_score'],d['data']['obligation_status'],d['data']['wellness_hold_until']"
curl -s "$B/contracts/$CID/obligation-summary" "${AD[@]}" | python3 -m json.tool

echo "--- sponsorship deal + deliverable"
D=$(curl -s -X POST "$B/sponsorship-deals" "${SM[@]}" -d "{\"organization_id\":\"$OID\",\"sponsor_name\":\"KeyCo\",\"exclusivity_category\":\"PERIPHERALS\",\"total_fee_cents\":1000,\"deliverable_count_required\":3,\"starts_at\":\"2026-08-01T00:00:00.000Z\",\"ends_at\":\"2026-12-01T00:00:00.000Z\"}")
DID=$(echo "$D" | jqv "['data']['id']")
echo "$D" | jqv "['data']"
DV=$(curl -s -X POST "$B/sponsorship-deals/$DID/activate" "${SM[@]}" -d '{}' | jqv "['data']['version']")
echo "activated version=$DV"
echo "stale token:"; curl -s -X POST "$B/sponsorship-deals/$DID/deliverables" "${SM[@]}" -d "{\"contract_id\":\"$CID\",\"deliverable_type\":\"SOCIAL_POST\",\"due_at\":\"2026-09-01T00:00:00.000Z\",\"expected_deal_version\":1}" | jqv "['data']"
echo "breach blocks:"; curl -s -X POST "$B/sponsorship-deals/$DID/deliverables" "${SM[@]}" -d "{\"contract_id\":\"$CID\",\"deliverable_type\":\"SOCIAL_POST\",\"due_at\":\"2026-09-01T00:00:00.000Z\",\"expected_deal_version\":$DV}" | jqv "['data']"

echo "--- prize distribution waterfall"
PD=$(curl -s -X POST "$B/prize-distributions" "${FIN[@]}" -d "{\"organization_id\":\"$OID\",\"league_id\":\"$LID\",\"tournament_name\":\"Summer Cup\",\"placement\":1,\"gross_prize_cents\":1000000,\"tournament_end_at\":\"2026-08-01T12:00:00.000Z\"}")
PDID=$(echo "$PD" | jqv "['data']['id']")
curl -s -X POST "$B/prize-distributions/$PDID/calculate" "${FIN[@]}" -d '{}' | python3 -m json.tool
curl -s "$B/prize-distributions/$PDID/allocations" "${FIN[@]}" | python3 -m json.tool
echo "same-user approve:"; curl -s -X POST "$B/prize-distributions/$PDID/approve" -H "X-User-ID: fin1" -H "X-User-Role: LeagueAdmin" -d '{}' | jqv "['data']"
curl -s -X POST "$B/prize-distributions/$PDID/approve" "${AD[@]}" -d '{}' | jqv "['data']['distribution_status']"
curl -s "$B/organizations/$OID" "${AD[@]}" | jqv "['data']['prize_payable_cents'],d['data']['committed_salary_cents'],d['data']['uncommitted_salary_cents'],d['data']['active_roster_count'],d['data']['wellness_flag_count']"

echo "--- roster move RELEASE: file, decide, execute, reverse"
OVER=$(curl -s "$B/organizations/$OID" "${AD[@]}" | jqv "['data']['version']")
RM=$(curl -s -X POST "$B/roster-moves" "${GM[@]}" -d "{\"organization_id\":\"$OID\",\"player_id\":\"$PID\",\"move_type\":\"RELEASE\",\"contract_id\":\"$CID\",\"expected_organization_version\":$OVER}")
echo "$RM" | jqv "['data']"
RMID=$(echo "$RM" | jqv "['data']['id']")
echo "self-decide:"; curl -s -X POST "$B/roster-moves/$RMID/decision" -H "X-User-ID: $OID" -H "X-User-Role: LeagueAdmin" -H "Content-Type: application/json" -d '{"decision":"APPROVE"}' | jqv "['data']"
curl -s -X POST "$B/roster-moves/$RMID/decision" "${AD[@]}" -d '{"decision":"APPROVE"}' | jqv "['data']['move_status']"
curl -s -X POST "$B/roster-moves/$RMID/execute" "${GM[@]}" -d '{}' | jqv "['data']"
curl -s "$B/contracts/$CID" "${AD[@]}" | jqv "['data']['contract_status']"
curl -s "$B/players/$PID" "${AD[@]}" | jqv "['data']['player_status'],d['data']['free_agency_window_ends_at'],d['data']['last_release_organization_id']==\"$OID\""
curl -s "$B/organizations/$OID" "${AD[@]}" | jqv "['data']['committed_salary_cents'],d['data']['active_roster_count']"
curl -s -X POST "$B/roster-moves/$RMID/reverse" "${AD[@]}" -d '{"reversal_reason":"filed in error"}' | jqv "['data']['move_status'],d['data']['released_cap_cents']"
curl -s "$B/organizations/$OID" "${AD[@]}" | jqv "['data']['committed_salary_cents'],d['data']['active_roster_count']"
curl -s "$B/players/$PID" "${AD[@]}" | jqv "['data']['player_status'],d['data']['current_organization_id']==\"$OID\""

echo "--- pagination guard"
curl -s "$B/leagues?limit=500" "${AD[@]}" | jqv "['data']"
curl -s "$B/leagues?limit=1&offset=0" "${AD[@]}" | jqv "['meta']"
echo "--- 404 unknown path"
curl -s "$B/nope" "${AD[@]}" | jqv "['data']"
