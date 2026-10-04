#!/usr/bin/env bash
# Smoke 4: placement timing errors, downtime via the dismiss path, molt cycle,
# auto-deplete, order window/volume errors, duplicate quotation, pagination,
# organic feed pool split, cert + commitment expiry via run-ops.
set -euo pipefail
cd "$(dirname "$0")"

PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
export PORT
echo "smoke4: starting on port $PORT"
bash start.sh > /tmp/smoke4_3426.log 2>&1 &
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
CLOCK() { curl -s -X POST "${ADMIN[@]}" "$BASE/_clock/set_current_utc" -d "{\"to_iso8601\":\"$1\"}" > /dev/null; }
CMV() { curl -s "${SALES[@]}" "$BASE/api/commitments/$1" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['version'])"; }

CLOCK "2026-09-01T00:00:00Z"
CXID=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes" -d '{"name":"A","region_code":"MIDWEST","mill_receiving_tons_per_day":100}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H1=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H1","housing_style":"CONVENTIONAL","capacity_hens":200000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H2=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H2","housing_style":"CONVENTIONAL","capacity_hens":200000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H3=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H3","housing_style":"CONVENTIONAL","capacity_hens":200000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
H4=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/houses" -d '{"house_code":"H4","housing_style":"CONVENTIONAL","capacity_hens":200000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")

echo "--- organic pool split"
FCG=$(curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts" -d "{\"complex_id\":\"$CXID\",\"commodity\":\"CORN\",\"is_organic_certified\":true,\"total_tons\":10,\"basis_cents_per_ton\":0,\"spot_reference_cents_per_ton\":18000,\"delivery_start\":\"2026-09-01T00:00:00Z\",\"delivery_end\":\"2026-12-01T00:00:00Z\"}" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PROC[@]}" "$BASE/api/feed-contracts/$FCG/receive" -d '{"tons":10,"spot_cents_per_ton":18000}' > /dev/null
curl -s "${ADMIN[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['corn_organic_inventory_tons']==10 and d['corn_inventory_tons']==0, d; print('ok')"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/feed-batches" -d '{"program":"ORGANIC","corn_tons":4,"soybean_tons":0}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['blended_cost_cents_per_ton']==18000 and d['actual_cost_per_dozen_cents']==36.0, d; print('ok')"
curl -s "${ADMIN[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['corn_organic_inventory_tons']==6, d; print('ok, pool decremented')"

echo "--- cert (valid 365d) + quotation + customers/commitments"
CERTID=$(curl -s -X POST "${QA[@]}" "$BASE/api/houses/$H1/certifications" -d '{"program":"CAGE_FREE","auditor_name":"Aud","scheduled_date":"2026-09-01T00:00:00Z"}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${QA[@]}" "$BASE/api/certifications/$CERTID/record-result" -d '{"result":"PASSED"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":150,"effective_date":"2026-09-01T00:00:00Z"}' > /dev/null
echo "--- duplicate quotation -> 409"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":160,"effective_date":"2026-09-01T00:00:00Z"}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_DUPLICATE_QUOTATION', d; print('ok')"
echo "--- pagination meta"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":151,"effective_date":"2026-09-02T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":152,"effective_date":"2026-09-03T00:00:00Z"}' > /dev/null
curl -s -X POST "${ADMIN[@]}" "$BASE/api/market-quotations" -d '{"region_code":"MIDWEST","size_class":"LARGE","price_cents_per_dozen":153,"effective_date":"2026-09-04T00:00:00Z"}' > /dev/null
curl -s "${ADMIN[@]}" "$BASE/api/market-quotations?limit=2" | J "import sys,json; d=json.load(sys.stdin); assert d['response_type']=='array' and len(d['data'])==2 and d['meta']['limit']==2 and d['meta']['offset']==0 and d['meta']['total_count']==4 and d['meta']['has_more']==True, d; print('ok')"
curl -s "${ADMIN[@]}" "$BASE/api/market-quotations?limit=2&offset=2" | J "import sys,json; d=json.load(sys.stdin); assert len(d['data'])==2 and d['meta']['has_more']==False, d; print('ok')"

CUSTID=$(curl -s -X POST "${ADMIN[@]}" "$BASE/api/customers" -d '{"name":"C","segment":"RETAIL","credit_limit_cents":100000000}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
CM1=$(curl -s -X POST "${SALES[@]}" "$BASE/api/customers/$CUSTID/commitments" -d '{"program":"CONVENTIONAL","region_code":"MIDWEST","weekly_dozen_committed":100,"price_adjustment_cents_per_dozen":5,"effective_from":"2026-09-01T00:00:00Z","effective_to":"2027-12-31T00:00:00Z"}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
CM2=$(curl -s -X POST "${SALES[@]}" "$BASE/api/customers/$CUSTID/commitments" -d '{"program":"CONVENTIONAL","region_code":"WEST","weekly_dozen_committed":100,"price_adjustment_cents_per_dozen":0,"effective_from":"2026-09-01T00:00:00Z","effective_to":"2027-01-01T00:00:00Z"}' | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM1/activate" -d '{}' > /dev/null
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM2/activate" -d '{}' > /dev/null

echo "--- main flock F1 placed at age 18 (lands LAYING directly)"
F1=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H1/flocks" -d '{"flock_code":"F1","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2026-04-28T00:00:00Z","placed_hen_count":20000}')
F1ID=$(echo "$F1" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$F1ID/place" -d '{}' > /dev/null

echo "--- downtime via dismiss path"
FH2=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H2/flocks" -d '{"flock_code":"FH2","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":5000}')
FH2ID=$(echo "$FH2" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$FH2ID/place" -d '{}' > /dev/null
EVID=$(curl -s -X POST "${VET[@]}" "$BASE/api/complexes/$CXID/disease-events" -d "{\"pathogen\":\"LPAI\",\"detection_date\":\"2026-09-01T00:00:00Z\",\"scope_house_ids\":[\"$H2\"]}" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
DOID=$(curl -s -X POST "${VET[@]}" "$BASE/api/disease-events/$EVID/depopulation-orders" -d "{\"house_id\":\"$H2\",\"disposal_method\":\"BURIAL\"}" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['downtime_days']==28, d; print(d['id'])")
curl -s -X POST "${VET[@]}" "$BASE/api/depopulation-orders/$DOID/complete" -d '{}' > /dev/null
curl -s -X POST "${VET[@]}" "$BASE/api/disease-events/$EVID/dismiss" -d '{}' > /dev/null
curl -s "${VET[@]}" "$BASE/api/complexes/$CXID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['biosecurity_posture']=='NORMAL', d; print('ok, dismiss relaxes to NORMAL')"
H2B=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H2/flocks" -d '{"flock_code":"H2B","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2026-09-01T00:00:00Z","placed_hen_count":3000}')
H2BID=$(echo "$H2B" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$H2BID/place" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_HOUSE_IN_DOWNTIME', d; print('ok, downtime 409')"

echo "--- placement timing errors"
FND=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H3/flocks" -d '{"flock_code":"FND","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2027-01-01T00:00:00Z","placed_hen_count":100}')
FNDID=$(echo "$FND" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$FNDID/place" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_PLACEMENT_NOT_DUE', d; print('ok')"
FMS=$(curl -s -X POST "${PLANNER[@]}" "$BASE/api/houses/$H4/flocks" -d '{"flock_code":"FMS","program":"CONVENTIONAL","ownership":"OWNED","placement_date":"2025-09-01T00:00:00Z","placed_hen_count":100}')
FMSID=$(echo "$FMS" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$FMSID/place" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_PLACEMENT_WINDOW_MISSED', d; print('ok')"

echo "--- orders at 2026-11-03"
CLOCK "2026-11-03T00:00:00Z"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$H2BID/place" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='GROWING', d; print('ok, placement after downtime (half-open)')"
ORDA=$(curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM1/orders" -d "{\"ship_week_start\":\"2026-11-02T00:00:00Z\",\"dozen_ordered\":60,\"size_class\":\"LARGE\",\"expected_commitment_version\":$(CMV $CM1)}" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
echo "--- weekly volume exceeded"
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM1/orders" -d "{\"ship_week_start\":\"2026-11-02T00:00:00Z\",\"dozen_ordered\":50,\"size_class\":\"LARGE\",\"expected_commitment_version\":$(CMV $CM1)}" | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED', d; print('ok')"
ORDB=$(curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM1/orders" -d "{\"ship_week_start\":\"2026-11-02T00:00:00Z\",\"dozen_ordered\":40,\"size_class\":\"LARGE\",\"expected_commitment_version\":$(CMV $CM1)}" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
echo "--- exact fill allowed (60+40 == 100)"
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM1/orders" -d "{\"ship_week_start\":\"2026-11-02T00:00:00Z\",\"dozen_ordered\":1,\"size_class\":\"LARGE\",\"expected_commitment_version\":$(CMV $CM1)}" | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_COMMITMENT_WEEKLY_VOLUME_EXCEEDED', d; print('ok')"
echo "--- outside commitment window"
curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM1/orders" -d "{\"ship_week_start\":\"2028-01-03T00:00:00Z\",\"dozen_ordered\":10,\"size_class\":\"LARGE\",\"expected_commitment_version\":$(CMV $CM1)}" | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_ORDER_OUTSIDE_COMMITMENT_WINDOW', d; print('ok')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDA/allocate" -d '{}' > /dev/null
curl -s -X POST "${PLANT[@]}" "$BASE/api/orders/$ORDA/ship" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='SHIPPED', d; print('ok, shipped in window')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDB/allocate" -d '{}' > /dev/null
echo "--- complex orders list"
curl -s "${SALES[@]}" "$BASE/api/complexes/$CXID/orders" | J "import sys,json; d=json.load(sys.stdin); assert d['meta']['total_count']==2, d; print('ok')"

CLOCK "2026-11-16T00:00:00Z"
echo "--- ship outside window (clock == ship_week + 14d)"
curl -s -X POST "${PLANT[@]}" "$BASE/api/orders/$ORDB/ship" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_ORDER_OUTSIDE_SHIP_WINDOW', d; print('ok')"
ORDC=$(curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM1/orders" -d "{\"ship_week_start\":\"2026-11-16T00:00:00Z\",\"dozen_ordered\":10,\"size_class\":\"PEEWEE\",\"expected_commitment_version\":$(CMV $CM1)}" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDC/allocate" -d '{}' > /dev/null
echo "--- ship with no quotation for size class"
curl -s -X POST "${PLANT[@]}" "$BASE/api/orders/$ORDC/ship" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_NO_QUOTATION', d; print('ok')"
echo "--- allocate against empty region -> BLOCKED (200, counter 1)"
ORDW=$(curl -s -X POST "${SALES[@]}" "$BASE/api/commitments/$CM2/orders" -d "{\"ship_week_start\":\"2026-11-16T00:00:00Z\",\"dozen_ordered\":5,\"size_class\":\"LARGE\",\"expected_commitment_version\":$(CMV $CM2)}" | J "import sys,json; print(json.load(sys.stdin)['data']['id'])")
curl -s -X POST "${PLANNER[@]}" "$BASE/api/orders/$ORDW/allocate" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='BLOCKED' and d['allocated_complex_id'] is None, d; print('ok')"
curl -s "${SALES[@]}" "$BASE/api/commitments/$CM2" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['blocked_order_count']==1, d; print('ok')"

echo "--- molt cycle: F1 at age 69 (>= 50)"
CLOCK "2027-08-24T00:00:00Z"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null
curl -s "${PLANNER[@]}" "$BASE/api/flocks/$F1ID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='LAYING' and d['age_weeks']==69, d; print('ok, age 69 LAYING')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$F1ID/molt" -d '{}' | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='MOLT' and d['molt_start_age_weeks']==69, d; print('ok, molt started')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$F1ID/molt" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_INVALID_STATE', d; print('ok, MOLT cannot molt')"
CLOCK "2027-09-28T00:00:00Z"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null
curl -s "${PLANNER[@]}" "$BASE/api/flocks/$F1ID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='LAYING' and d['molt_count']==1 and d['molt_start_age_weeks'] is None and d['age_weeks']==74, d; print('ok, molt completed at +4wk')"
curl -s -X POST "${PLANNER[@]}" "$BASE/api/flocks/$F1ID/molt" -d '{}' | J "import sys,json; d=json.load(sys.stdin); assert d['data']['error_id']=='ERR_MOLT_NOT_ALLOWED', d; print('ok, second molt rejected')"
echo "--- cert expired at run-ops (valid_until 2027-09-01 passed)"
curl -s "${QA[@]}" "$BASE/api/houses/$H1/certifications" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d[0]['status']=='EXPIRED', d; print('ok')"
echo "--- commitment CM2 expired (effective_to 2027-01-01 passed)"
curl -s "${SALES[@]}" "$BASE/api/commitments/$CM2" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='EXPIRED', d; print('ok')"

echo "--- auto-deplete at age 80"
CLOCK "2027-11-16T00:00:00Z"
curl -s -X POST "${ADMIN[@]}" "$BASE/api/complexes/$CXID/run-ops" -d '{}' > /dev/null
curl -s "${PLANNER[@]}" "$BASE/api/flocks/$F1ID" | J "import sys,json; d=json.load(sys.stdin)['data']; assert d['status']=='DEPLETED' and d['current_hen_count']==0, d; print('ok')"

echo "SMOKE4 PASS"
kill $SERVER_PID 2>/dev/null || true
trap - EXIT
