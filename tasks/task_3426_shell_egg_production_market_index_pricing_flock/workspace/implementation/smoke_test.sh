#!/usr/bin/env bash
# Self-smoke-test: boots the server on a dynamic free port, exercises a
# create/place/run-ops/order/settle flow, then kills exactly that PID.
set -euo pipefail
cd "$(dirname "$0")"

PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
export PORT
echo "smoke: starting on port $PORT"
bash start.sh > /tmp/smoke_3426.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 60); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/api/complexes/nope" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

ADMIN=(-H "X-User-ID: admin-1" -H "X-User-Role: PlatformAdmin" -H "Content-Type: application/json")
PLANNER=(-H "X-User-ID: planner-1" -H "X-User-Role: ProductionPlanner" -H "Content-Type: application/json")
SALES=(-H "X-User-ID: sales-1" -H "X-User-Role: SalesManager" -H "Content-Type: application/json")
PLANT=(-H "X-User-ID: plant-1" -H "X-User-Role: PlantManager" -H "Content-Type: application/json")
BASE="http://127.0.0.1:$PORT"

echo "--- no auth -> 401"
curl -s "$BASE/api/complexes/x" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['response_type']=='error' and d['data']['error_id']=='ERR_UNAUTHENTICATED', d; print('ok')"

echo "--- set clock"
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2026-09-01T00:00:00Z"}' | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['current_utc']=='2026-09-01T00:00:00Z', d; print('ok')"

echo "--- create complex"
CX=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes" -d '{"name":"Alpha","region_code":"MIDWEST","mill_receiving_tons_per_day":50}')
CXID=$(echo "$CX" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['biosecurity_posture']=='NORMAL', d; print(d['data']['id'])")
echo "complex=$CXID"

echo "--- create house"
H=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H1","housing_style":"CONVENTIONAL","capacity_hens":100000}')
HID=$(echo "$H" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['hen_inventory']==0, d; print(d['data']['id'])")

echo "--- create flock"
F=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$HID/flocks" -d '{"flock_code":"F1","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":10000}')
FID=$(echo "$F" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['status']=='PLANNED', d; print(d['data']['id'])")

echo "--- place flock"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$FID/place" -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['status']=='GROWING' and d['data']['current_hen_count']==10000 and d['data']['version']==2, d; print('ok')"

echo "--- advance clock 20 weeks, run-ops"
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2027-01-20T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' | python3 -c "
import sys, json
d = json.load(sys.stdin)['data']
assert d['ops_run_index'] == 1, d
# 20 weeks: age 0 -> 20 weeks; mortality 10 bps/wk; LAYING from week 18
assert d['ungraded_conventional_dozen'] > 0, d
print('ok, ungraded=', d['ungraded_conventional_dozen'])"

echo "--- flock should be LAYING at age 20"
curl -s "${PLANNER[@]}" "$BASE/api/flocks/$FID" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='LAYING' and d['age_weeks']==20, d; print('ok')"

echo "--- capacity projection"
curl -s "${PLANNER[@]}" "$BASE/api/complexes/$CXID/capacity-projection?week_offset=0" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['total_dozen']>0 and d['week_offset']==0, d; print('ok', d)"

echo "--- quotation + customer + commitment"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":150,"effective_date":"2026-09-01T00:00:00Z"}' | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert 'version' not in d and 'updated_at' not in d, d; print('ok')"
CUST=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/customers" -d '{"name":"Buyer","segment":"RETAIL","credit_limit_cents":100000000}')
CUSTID=$(echo "$CUST" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")
CM=$(curl -s -X POST "${SALES[@]}" "$BASE/api/customers/$CUSTID/commitments" -d '{"program":"CONVENTIONAL","region_code":"MIDWEST","weekly_dozen_committed":1000,"price_adjustment_cents_per_dozen":5,"effective_from":"2026-09-01T00:00:00Z","effective_to":"2027-12-31T00:00:00Z"}')
CMID=$(echo "$CM" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='PENDING', d; print(d['id'])")
CMV=$(echo "$CM" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['version'])")
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/activate" -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='ACTIVE' and d['version']==2, d; print('ok')"

echo "--- order: non-Monday rejected"
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/orders" -d "{\"ship_week_start\":\"2027-01-21T00:00:00Z\",\"dozen_ordered\":100,\"size_class\":\"LARGE\",\"expected_commitment_version\":2}" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_SHIP_WEEK_NOT_MONDAY', d; print('ok')"

echo "--- order: stale version rejected"
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/orders" -d "{\"ship_week_start\":\"2027-01-18T00:00:00Z\",\"dozen_ordered\":100,\"size_class\":\"LARGE\",\"expected_commitment_version\":1}" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_STALE_COMMITMENT_VERSION', d; print('ok')"

echo "--- order: create (Monday 2027-01-18), allocate, ship, finalize"
ORD=$(curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/orders" -d "{\"ship_week_start\":\"2027-01-18T00:00:00Z\",\"dozen_ordered\":100,\"size_class\":\"LARGE\",\"expected_commitment_version\":2}")
ORDID=$(echo "$ORD" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='BOOKED', d; print(d['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDID/allocate" -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='ALLOCATED' and d['allocated_dozen']==100, d; print('ok')"
curl -s -X POST "${PLANT[@]}" "$BASE/api/orders/$ORDID/ship" -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='SHIPPED', d; print('ok')"
SET=$(curl -s "${SALES[@]}" "$BASE/api/orders/$ORDID/settlements")
SETID=$(echo "$SET" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['response_type']=='array' and len(d['data'])==1, d; s=d['data'][0]; assert s['provisional_index_cents']==150 and s['provisional_unit_price_cents']==155 and s['provisional_total_cents']==15500, s; print(s['id'])")
echo "--- finalize before week close -> 409"
curl -s -X POST "${SALES[@]}" "$BASE/api/settlements/$SETID/finalize" -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_SETTLEMENT_NOT_FINALIZABLE', d; print('ok')"
echo "--- publish in-week quotation (after ship), then finalize"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":170,"effective_date":"2027-01-19T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2027-01-25T00:00:00Z"}' > /dev/null
curl -s -X POST "${SALES[@]}" "$BASE/api/settlements/$SETID/finalize" -d '{}' | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='FINAL' and d['final_index_average_cents']==170 and d['final_unit_price_cents']==175 and d['final_total_cents']==17500 and len(d['quotation_ids_used'])==1, d; print('ok')"

echo "--- customer outstanding reflects finalize"
curl -s "${SALES[@]}" "$BASE/api/customers/$CUSTID" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']; assert d['outstanding_cents']==17500 and d['status']=='ACTIVE', d; print('ok')"

echo "SMOKE PASS"
kill $SERVER_PID 2>/dev/null || true
trap - EXIT
