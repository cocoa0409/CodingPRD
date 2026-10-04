#!/usr/bin/env bash
# Smoke 3: settlement credit loop (suspend/dispute/resolve/mark-paid) and the
# capital-project conversion flow with commitment progress recompute.
set -euo pipefail
cd "$(dirname "$0")"

PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
export PORT
echo "smoke3: starting on port $PORT"
bash start.sh > /tmp/smoke3_3426.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/api/complexes/nope" 2>/dev/null; then break; fi
  sleep 0.5
done

ADMIN=(-H "X-User-ID: admin-1" -H "X-User-Role: PlatformAdmin" -H "Content-Type: application/json")
PLANNER=(-H "X-User-ID: planner-1" -H "X-User-Role: ProductionPlanner" -H "Content-Type: application/json")
SALES=(-H "X-User-ID: sales-1" -H "X-User-Role: SalesManager" -H "Content-Type: application/json")
PLANT=(-H "X-User-ID: plant-1" -H "X-User-Role: PlantManager" -H "Content-Type: application/json")
BASE="http://127.0.0.1:$PORT"
J() { python3 -c "$1"; }

curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2026-09-01T00:00:00Z"}' > /dev/null
CXID=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes" -d '{"name":"A","region_code":"MIDWEST","mill_receiving_tons_per_day":50}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H1=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H1","housing_style":"CONVENTIONAL","capacity_hens":50000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H2=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H2","housing_style":"CAGE_FREE","capacity_hens":30000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" -d '{"flock_code":"F1","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":10000}' > /dev/null
F1ID=$(curl -s "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" | J "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$F1ID/place" -d '{}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":150,"effective_date":"2026-09-01T00:00:00Z"}' > /dev/null

echo "--- customer with tight credit; commitment with transition targets"
CUSTID=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/customers" -d '{"name":"C","segment":"RETAIL","credit_limit_cents":10000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
CM=$(curl -s -X POST "${SALES[@]}" "$BASE/api/customers/$CUSTID/commitments" -d '{"program":"CONVENTIONAL","region_code":"MIDWEST","weekly_dozen_committed":1000,"price_adjustment_cents_per_dozen":5,"effective_from":"2026-09-01T00:00:00Z","effective_to":"2027-12-31T00:00:00Z","cage_free_transition_deadline":"2028-01-01T00:00:00Z","required_cage_free_pct":0.5}')
CMID=$(echo "$CM" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['required_conversion_hens']==1000 and d['achieved_conversion_hens']==0 and d['transition_on_track']==True, d; print(d['id'])")
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/activate" -d '{}' > /dev/null

echo "--- capital project: propose, approve, promote at run-ops"
P=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/commitments/$CMID/capital-projects" -d "{\"house_id\":\"$H1\",\"investment_cents\":5000,\"target_style\":\"CAGE_FREE\",\"construction_weeks\":2}")
PID=$(echo "$P" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='PROPOSED', d; print(d['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/capital-projects/$PID/commission" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_INVALID_STATE', d; print('ok, commission gated')"
PR2=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/commitments/$CMID/capital-projects" -d "{\"house_id\":\"$H2\",\"investment_cents\":5000,\"target_style\":\"CAGE_FREE\",\"construction_weeks\":2}")
PR2ID=$(echo "$PR2" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/capital-projects/$PR2ID/approve" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_CONVERSION_REDUNDANT', d; print('ok, redundant rejected')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/capital-projects/$PID/approve" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='APPROVED', d; print('ok')"

echo "--- order/ship lifecycle at 2027-01-20"
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2027-01-20T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null
ORDID=$(curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/orders" -d '{"ship_week_start":"2027-01-18T00:00:00Z","dozen_ordered":100,"size_class":"LARGE","expected_commitment_version":2}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='BOOKED', d; print(d['id'])")
echo "--- customer ownership on order create"
curl -s -X POST -H "X-User-ID: not-the-customer" -H "X-User-Role: Customer" -H "Content-Type: application/json" "$BASE/api/commitments/$CMID/orders" -d '{"ship_week_start":"2027-01-18T00:00:00Z","dozen_ordered":10,"size_class":"LARGE","expected_commitment_version":3}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_FORBIDDEN', d; print('ok')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDID/allocate" -d '{}' > /dev/null
curl -s -X POST "${PLANT[@]}" "$BASE/api/orders/$ORDID/ship" -d '{}' > /dev/null
SETID=$(curl -s "${SALES[@]}" "$BASE/api/orders/$ORDID/settlements" | J "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
curl -s "${PLANNER[@]}" "$BASE/api/commitments/$CMID/capital-projects" | J "import sys,json; d=json.load(sys.stdin)['data']; p=[x for x in d if x['id']=='$PID'][0]; assert p['status']=='IN_CONSTRUCTION' and p['construction_started_at']=='2027-01-20T00:00:00.000Z', p; print('ok, promoted')"

echo "--- commission too early"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/capital-projects/$PID/commission" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_CONSTRUCTION_INCOMPLETE', d; print('ok')"

echo "--- finalize -> suspension"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":150,"effective_date":"2027-01-19T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2027-01-25T00:00:00Z"}' > /dev/null
curl -s -X POST "${SALES[@]}" "$BASE/api/settlements/$SETID/finalize" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='FINAL' and d['final_total_cents']==15500, d; print('ok')"
curl -s "${SALES[@]}" "$BASE/api/customers/$CUSTID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['outstanding_cents']==15500 and d['status']=='SUSPENDED', d; print('ok, SUSPENDED')"
echo "--- new order against suspended customer"
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/orders" -d '{"ship_week_start":"2027-01-25T00:00:00Z","dozen_ordered":10,"size_class":"LARGE","expected_commitment_version":3}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_CUSTOMER_SUSPENDED', d; print('ok')"

echo "--- dispute loop preserves amounts"
curl -s -X POST -H "X-User-ID: $CUSTID" -H "X-User-Role: Customer" -H "Content-Type: application/json" "$BASE/api/settlements/$SETID/dispute" -d '{"reason":"price wrong"}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='DISPUTED' and d['disputed_reason']=='price wrong', d; print('ok')"
curl -s -X POST -H "X-User-ID: somebody-else" -H "X-User-Role: Customer" -H "Content-Type: application/json" "$BASE/api/settlements/$SETID/dispute" -d '{"reason":"x"}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_FORBIDDEN', d; print('ok, ownership')"
curl -s -X POST "${SALES[@]}" "$BASE/api/settlements/$SETID/resolve" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='FINAL' and d['disputed_reason'] is None and d['final_total_cents']==15500, d; print('ok, amounts preserved')"

echo "--- mark-paid restores standing"
curl -s -X POST "${SALES[@]}" "$BASE/api/settlements/$SETID/mark-paid" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='PAID', d; print('ok')"
curl -s "${SALES[@]}" "$BASE/api/customers/$CUSTID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['outstanding_cents']==0 and d['status']=='ACTIVE', d; print('ok, ACTIVE again')"

echo "--- commission after construction elapses flips the house"
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2027-02-03T00:00:00Z"}' > /dev/null
CMV_BEFORE=$(curl -s "${SALES[@]}" "$BASE/api/commitments/$CMID" | J "import sys,json; print(json.load(sys.stdin)['data']['version'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/capital-projects/$PID/commission" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='COMMISSIONED' and d['commissioned_at']=='2027-02-03T00:00:00.000Z', d; print('ok')"
curl -s "${PLANNER[@]}" "$BASE/api/houses/$H1" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['housing_style']=='CAGE_FREE', d; print('ok, house flipped')"
curl -s "${SALES[@]}" "$BASE/api/commitments/$CMID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['achieved_conversion_hens']==50000 and d['required_conversion_hens']==1000 and d['transition_on_track']==True and d['version']==$CMV_BEFORE+1, d; print('ok, progress recomputed + bumped')"

echo "SMOKE3 PASS"
kill $SERVER_PID 2>/dev/null || true
trap - EXIT
