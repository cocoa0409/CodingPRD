#!/usr/bin/env bash
# Adversarial smoke: certification gating, occupancy, feed costing, mill
# capacity, quarantine cascade + depopulation + clearance, packing OCC.
set -euo pipefail
cd "$(dirname "$0")"

PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
export PORT
echo "smoke2: starting on port $PORT"
bash start.sh > /tmp/smoke2_3426.log 2>&1 &
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
PROC=(-H "X-User-ID: proc-1" -H "X-User-Role: ProcurementLead" -H "Content-Type: application/json")
VET=(-H "X-User-ID: vet-1" -H "X-User-Role: HealthOfficial" -H "Content-Type: application/json")
QA=(-H "X-User-ID: qa-1" -H "X-User-Role: QualityAuditor" -H "Content-Type: application/json")
BASE="http://127.0.0.1:$PORT"
J() { python3 -c "$1"; }

curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2026-09-01T00:00:00Z"}' > /dev/null

echo "--- setup complex + houses"
CXID=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes" -d '{"name":"A","region_code":"MIDWEST","mill_receiving_tons_per_day":50}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H1=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H1","housing_style":"CONVENTIONAL","capacity_hens":50000}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H2=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H2","housing_style":"CAGE_FREE","capacity_hens":50000}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H3=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H3","housing_style":"CONVENTIONAL","capacity_hens":50000}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")

echo "--- role gate: planner cannot create complex"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/complexes" -d '{"name":"X","region_code":"WEST","mill_receiving_tons_per_day":1}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_FORBIDDEN', d; print('ok')"

echo "--- feed: capacity window checks"
FC1=$(curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts" -d "{\"complex_id\":\"$CXID\",\"commodity\":\"CORN\",\"total_tons\":100,\"basis_cents_per_ton\":100,\"spot_reference_cents_per_ton\":18000,\"delivery_start\":\"2026-09-01T00:00:00Z\",\"delivery_end\":\"2026-09-11T00:00:00Z\"}")
FC1ID=$(echo "$FC1" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='OPEN', d; print(d['id'])")
curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts" -d "{\"complex_id\":\"$CXID\",\"commodity\":\"CORN\",\"total_tons\":500,\"basis_cents_per_ton\":100,\"spot_reference_cents_per_ton\":18000,\"delivery_start\":\"2026-09-01T00:00:00Z\",\"delivery_end\":\"2026-09-11T00:00:00Z\"}" | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_MILL_RECEIVING_CAPACITY_EXCEEDED', d; print('ok')"
curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts" -d "{\"complex_id\":\"$CXID\",\"commodity\":\"SOYBEAN_MEAL\",\"total_tons\":400,\"basis_cents_per_ton\":50,\"spot_reference_cents_per_ton\":36000,\"delivery_start\":\"2026-09-01T00:00:00Z\",\"delivery_end\":\"2026-09-11T00:00:00Z\"}" | J "import sys,json; d=json.load(sys.stdin); assert d['response_type']=='object', d; print('ok, exact-fit allowed')"

echo "--- feed: hedge + two receipts costing"
curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts/$FC1ID/hedge" -d '{"hedged_tons":60,"hedge_futures_cents_per_ton":20000}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['hedged_tons']==60, d; print('ok')"
curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts/$FC1ID/receive" -d '{"tons":40,"spot_cents_per_ton":18000}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['received_tons']==40 and d['status']=='PARTIALLY_RECEIVED' and d['total_cost_cents']==804000 and d['average_received_cost_cents_per_ton']==20100 and d['hedged_applied_tons']==40, d; print('ok')"
curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts/$FC1ID/receive" -d '{"tons":60,"spot_cents_per_ton":19000}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['received_tons']==100 and d['status']=='FILLED' and d['total_cost_cents']==1970000 and d['average_received_cost_cents_per_ton']==19700, d; print('ok')"
curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts/$FC1ID/receive" -d '{"tons":1,"spot_cents_per_ton":19000}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_INVALID_STATE', d; print('ok, FILLED rejects')"

echo "--- feed: batch dual costing + pool rules"
curl -s -X POST -H "X-User-ID: $CXID" -H "X-User-Role: ComplexManager" -H "Content-Type: application/json" "$BASE/api/complexes/$CXID/feed-batches" -d '{"program":"CONVENTIONAL","corn_tons":50,"soybean_tons":0}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['tons_produced']==50 and d['blended_cost_cents_per_ton']==19700 and d['actual_cost_per_dozen_cents']==39.4 and d['standard_cost_per_dozen_cents']==50.4, d; print('ok')"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/feed-batches" -d '{"program":"ORGANIC","corn_tons":1,"soybean_tons":0}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_ORGANIC_INPUTS_REQUIRED', d; print('ok')"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/feed-batches" -d '{"program":"CONVENTIONAL","corn_tons":51,"soybean_tons":0}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_INSUFFICIENT_FEED_INVENTORY', d; print('ok')"
curl -s -X POST -H "X-User-ID: some-other-complex" -H "X-User-Role: ComplexManager" -H "Content-Type: application/json" "$BASE/api/complexes/$CXID/feed-batches" -d '{"program":"CONVENTIONAL","corn_tons":1,"soybean_tons":0}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_FORBIDDEN', d; print('ok, manager ownership')"

echo "--- flocks: cert gate, mismatch, grower, occupancy"
G1=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H2/flocks" -d '{"flock_code":"G1","program":"CAGE_FREE","ownership":"OWNED","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":10000}')
G1ID=$(echo "$G1" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$G1ID/place" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_CERTIFICATION_REQUIRED', d; print('ok')"
CERT=$(curl -s -X POST "${QA[@]}" "$BASE/api/houses/$H2/certifications" -d '{"program":"CAGE_FREE","auditor_name":"Aud","scheduled_date":"2026-09-01T00:00:00Z"}')
CERTID=$(echo "$CERT" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${QA[@]}" "$BASE/api/certifications/$CERTID/record-result" -d '{"result":"PASSED"}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='PASSED' and d['valid_from']=='2026-09-01T00:00:00.000Z' and d['valid_until']=='2027-09-01T00:00:00.000Z', d; print('ok')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$G1ID/place" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='GROWING', d; print('ok')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" -d '{"flock_code":"BAD","program":"ORGANIC","ownership":"OWNED","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":10}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_PROGRAM_HOUSING_MISMATCH', d; print('ok')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" -d '{"flock_code":"CT","program":"CONVENTIONAL","ownership":"CONTRACT","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":10}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_GROWER_REQUIRED', d; print('ok')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" -d '{"flock_code":"F1","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":10000}' > /dev/null
curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" -d '{"flock_code":"F2","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2026-09-02T00:00:00Z","placed_hen_count":10}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_HOUSE_OCCUPANCY_CONFLICT', d; print('ok')"
F1ID=$(curl -s "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" | J "import sys,json; print(json.load(sys.stdin)['data'][0]['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$F1ID/place" -d '{}' > /dev/null
F3=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H3/flocks" -d '{"flock_code":"F3","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2027-02-01T00:00:00Z","placed_hen_count":5000}')
F3ID=$(echo "$F3" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")

echo "--- advance 20 weeks, run-ops"
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2027-01-20T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null

echo "--- sales: order allocated to the complex"
CUSTID=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/customers" -d '{"name":"B","segment":"RETAIL","credit_limit_cents":100000000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
CM=$(curl -s -X POST "${SALES[@]}" "$BASE/api/customers/$CUSTID/commitments" -d '{"program":"CONVENTIONAL","region_code":"MIDWEST","weekly_dozen_committed":1000,"price_adjustment_cents_per_dozen":5,"effective_from":"2026-09-01T00:00:00Z","effective_to":"2027-12-31T00:00:00Z"}')
CMID=$(echo "$CM" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/activate" -d '{}' > /dev/null
ORDID=$(curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CMID/orders" -d '{"ship_week_start":"2027-02-08T00:00:00Z","dozen_ordered":100,"size_class":"LARGE","expected_commitment_version":2}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDID/allocate" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='ALLOCATED' and d['allocated_complex_id']=='$CXID', d; print('ok')"

echo "--- disease: report -> ELEVATED, confirm -> QUARANTINE cascade"
EV=$(curl -s -X POST "${VET[@]}" "$BASE/api/complexes/$CXID/disease-events" -d "{\"pathogen\":\"HPAI\",\"detection_date\":\"2027-01-20T00:00:00Z\",\"scope_house_ids\":[\"$H1\"]}")
EVID=$(echo "$EV" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='SUSPECTED', d; print(d['id'])")
curl -s "${VET[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['biosecurity_posture']=='ELEVATED', d; print('ok, ELEVATED')"
curl -s -X POST "${VET[@]}" "$BASE/api/disease-events/$EVID/confirm" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='CONFIRMED' and d['confirmed_at']=='2027-01-20T00:00:00.000Z', d; print('ok')"
curl -s "${VET[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['biosecurity_posture']=='QUARANTINE', d; print('ok, QUARANTINE')"
curl -s "${PLANNER[@]}" "$BASE/api/flocks/$F3ID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='CANCELLED', d; print('ok, planned flock cancelled')"
curl -s "${SALES[@]}" "$BASE/api/orders/$ORDID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='BLOCKED' and d['allocated_complex_id'] is None and d['allocated_dozen'] is None, d; print('ok, order blocked')"
curl -s "${SALES[@]}" "$BASE/api/commitments/$CMID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['blocked_order_count']==1, d; print('ok, blocked count 1')"

echo "--- packing blocked while quarantined"
curl -s -X POST "${PLANT[@]}" "$BASE/api/complexes/$CXID/packing-runs" -d '{"program":"CAGE_FREE","dozen_input":300,"run_date":"2027-01-20T00:00:00Z","expected_complex_version":999}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_STALE_COMPLEX_VERSION', d; print('ok, OCC first')"
CXV=$(curl -s "${PLANT[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; print(json.load(sys.stdin)['data']['version'])")
curl -s -X POST "${PLANT[@]}" "$BASE/api/complexes/$CXID/packing-runs" -d "{\"program\":\"CAGE_FREE\",\"dozen_input\":300,\"run_date\":\"2027-01-20T00:00:00Z\",\"expected_complex_version\":$CXV}" | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_COMPLEX_QUARANTINED', d; print('ok')"

echo "--- depopulation order: scope/guards, complete, downtime"
curl -s -X POST "${VET[@]}" "$BASE/api/disease-events/$EVID/depopulation-orders" -d "{\"house_id\":\"$H3\",\"disposal_method\":\"BURIAL\"}" | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_HOUSE_NOT_IN_SCOPE', d; print('ok')"
DO=$(curl -s -X POST "${VET[@]}" "$BASE/api/disease-events/$EVID/depopulation-orders" -d "{\"house_id\":\"$H1\",\"disposal_method\":\"INCINERATION\"}")
DOID=$(echo "$DO" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['downtime_days']==21 and d['status']=='ISSUED', d; print(d['id'])")
curl -s -X POST "${VET[@]}" "$BASE/api/disease-events/$EVID/depopulation-orders" -d "{\"house_id\":\"$H1\",\"disposal_method\":\"BURIAL\"}" | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_DEPOPULATION_ORDER_EXISTS', d; print('ok')"
curl -s -X POST "${VET[@]}" "$BASE/api/depopulation-orders/$DOID/complete" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='COMPLETED', d; print('ok')"
curl -s "${VET[@]}" "$BASE/api/houses/$H1" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['hen_inventory']==0 and d['downtime_until']=='2027-02-10T00:00:00.000Z', d; print('ok, downtime set')"
curl -s "${PLANNER[@]}" "$BASE/api/flocks/$F1ID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='DEPOPULATED' and d['current_hen_count']==0, d; print('ok, depopulated')"

echo "--- run-ops before downtime elapsed: event stays CONFIRMED"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null
curl -s "${VET[@]}" "$BASE/api/disease-events/$EVID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='CONFIRMED', d; print('ok')"

echo "--- allocate while quarantined -> stays BLOCKED, counter unchanged"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDID/allocate" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='BLOCKED', d; print('ok')"
curl -s "${SALES[@]}" "$BASE/api/commitments/$CMID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['blocked_order_count']==1, d; print('ok')"

echo "--- advance to downtime end, run-ops -> CLEARED, posture NORMAL"
curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d '{"to_iso8601":"2027-02-10T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null
curl -s "${VET[@]}" "$BASE/api/disease-events/$EVID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='CLEARED' and d['cleared_at']=='2027-02-10T00:00:00.000Z', d; print('ok')"
curl -s "${VET[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['biosecurity_posture']=='NORMAL', d; print('ok, NORMAL')"

echo "--- re-allocate the blocked order"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDID/allocate" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='ALLOCATED' and d['allocated_complex_id']=='$CXID', d; print('ok')"
curl -s "${SALES[@]}" "$BASE/api/commitments/$CMID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['blocked_order_count']==0, d; print('ok, counter decremented')"

echo "--- packing run: distribution reconciles to total_cases"
CXV=$(curl -s "${PLANT[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; print(json.load(sys.stdin)['data']['version'])")
PR=$(curl -s -X POST "${PLANT[@]}" "$BASE/api/complexes/$CXID/packing-runs" -d "{\"program\":\"CAGE_FREE\",\"dozen_input\":300,\"run_date\":\"2027-02-10T00:00:00Z\",\"expected_complex_version\":$CXV}")
PRID=$(echo "$PR" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='PACKED' and d['total_cases']==10 and sum(d['cases_by_size'].values())==10, d; assert d['cases_by_size']=={'JUMBO':0,'EXTRA_LARGE':1,'LARGE':4,'MEDIUM':3,'SMALL':2,'PEEWEE':0}, d['cases_by_size']; print(d['id'])")
echo "  cases_by_size exact-match ok"
curl -s -X POST "${PLANT[@]}" "$BASE/api/packing-runs/$PRID/verify" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='VERIFIED', d; print('ok')"
curl -s -X POST "${PLANT[@]}" "$BASE/api/packing-runs/$PRID/verify" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_INVALID_STATE', d; print('ok, terminal')"

echo "SMOKE2 PASS"
kill $SERVER_PID 2>/dev/null || true
trap - EXIT
