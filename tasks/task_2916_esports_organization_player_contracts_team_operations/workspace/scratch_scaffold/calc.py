from decimal import Decimal, ROUND_HALF_UP
import math
def rhu(x): return int(Decimal(str(x)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

# ---- C1 cap charge
base=12_000_000; bonus=500_000; SEASON_DAYS=365
# accept at 2026-08-10, season_end 2027-07-31
from datetime import datetime, timezone
d1=datetime(2026,8,10,tzinfo=timezone.utc); send=datetime(2027,7,31,tzinfo=timezone.utc)
rem=(send-d1).days
prov=rhu(Decimal(base)*rem/SEASON_DAYS)+bonus
fin=base+bonus
print("C1 remaining_days",rem,"provisional",prov,"final",fin,"delta",fin-prov)
budget=50_000_000
print("committed",prov,"uncommitted",budget-prov)

# second contract for cap-exceed test: budget 50M, existing committed prov
base2=40_000_000; bonus2=0
prov2=rhu(Decimal(base2)*rem/SEASON_DAYS)+bonus2
print("C1b base2 prov",prov2,"sum",prov+prov2,"> budget?",prov+prov2>budget)
# final-variant fail-at-approve case: contract that passes provisional but fails final
# committed_prov + prov3 <= budget but committed_final + fin3 > budget
base3=38_000_000
prov3=rhu(Decimal(base3)*rem/SEASON_DAYS)
print("C1c prov3",prov3,"fin3",base3,"prov_sum",prov+prov3,"fin_sum",fin+base3, "prov_ok",prov+prov3<=budget,"fin_bad",fin+base3>budget)

# ---- C3 prize
gross=10_000_000; levy_bp=250; org_bp=3500
levy=math.floor(gross*levy_bp/10000); dist=gross-levy
org=math.floor(dist*org_bp/10000); pool=dist-org
print("C3 levy",levy,"dist",dist,"org",org,"pool",pool)
ws=[('c1',4000,'US-CA',False),('c2',4500,'KR',False),('c3',4200,'US-CA',True)]
tot=sum(w for _,w,_,_ in ws)
raw={n:Decimal(pool)*w/tot for n,w,_,_ in ws}
fl={n:math.floor(v) for n,v in raw.items()}
rem_c=pool-sum(fl.values())
print("tot_w",tot,"raw",{k:str(v) for k,v in raw.items()},"floors",fl,"remainder",rem_c)
mx=max(fl.items(), key=lambda kv: kv[1])
fl[mx[0]]+=rem_c
print("after remainder ->",mx[0],fl,"sum",sum(fl.values()))
tot_wh=0; tot_esc=0; tot_net=0
for n,w,res,minor in ws:
    g=fl[n]; rate=1500 if res=='US-CA' else 3000
    wh=rhu(Decimal(g)*rate/10000); esc=rhu(Decimal(g)*1000/10000) if minor else 0
    net=g-wh-esc; tot_wh+=wh; tot_esc+=esc; tot_net+=net
    print(f"  {n} gross={g} rate_bp={rate} wh={wh} escrow={esc} net={net}")
print("totals wh",tot_wh,"esc",tot_esc,"net",tot_net,"allocated",sum(fl.values()))
print("invariant", gross == 0 + sum(fl.values()) + org + levy)

# sum-then-round contrast
print("naive sum-then-round pool check", rhu(sum(raw.values())))

# ---- C4 transfer
b=12_000_000; term=12; mult_bp=5000
eff=datetime(2026,8,10,tzinfo=timezone.utc); ends=eff.timestamp()+term*30*86400
clock=datetime(2026,8,20,tzinfo=timezone.utc)
rem_days=math.floor((ends-clock.timestamp())/86400)
rtm=math.ceil(rem_days/30); monthly=math.floor(b/term)
buyout=math.ceil(rtm*monthly*mult_bp/10000)
for grossf in (8_000_000, 4_000_000, 4_999_999, 5_000_000):
    tier=500 if grossf<5_000_000 else 300
    comm=rhu(Decimal(grossf)*tier/10000)
    net=grossf-comm-buyout
    print("C4 gross",grossf,"ends",datetime.fromtimestamp(ends,timezone.utc).isoformat(),"rem_days",rem_days,"rtm",rtm,"monthly",monthly,"buyout",buyout,"tier",tier,"comm",comm,"net",net)
# wrong-order contrast for 8M
g=8_000_000; comm_g=rhu(Decimal(g)*300/10000); net_g=g-comm_g-buyout
tier_net=500 if net_g<5_000_000 else 300
comm_n=rhu(Decimal(g)*tier_net/10000)
print("C4 wrong-order net",g-comm_n-buyout,"vs pinned",net_g)

# ---- C5 minor hours
cap=min(1200,900)-600
print("C5 minor cap",cap,"streaming 2h",120,"schedulable",cap-120)
