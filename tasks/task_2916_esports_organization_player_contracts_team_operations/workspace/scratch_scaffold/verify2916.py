from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
def rhu(x):  # round_half_up on Decimal/Fraction-ish
    return int(Decimal(x).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
D=Decimal
iso=lambda s: datetime.fromisoformat(s.replace('Z','+00:00'))
season_end=iso('2027-07-31T00:00:00Z'); eff=iso('2026-08-05T00:00:00Z')
rem=(season_end-eff).days; print('remaining_season_days',rem)
prov=lambda base: rhu(D(base)*rem/365)
for base in (12500000,10000000,4000000):
    print('base',base,'prov',prov(base),'final',base)
committed=sum(prov(b) for b in (12500000,10000000,4000000)); print('committed',committed,'uncommitted',50000000-committed)
print('P1 delta prov->final',12500000-prov(12500000))
print('sign-fail org budget 12400000: prov ok?',prov(12500000)<=12400000,'final ok?',12500000<=12400000)
print('ends_at', (eff+timedelta(days=360)).isoformat())

# prize
gross=10000000; levy=rhu(D(gross)*250/10000); dist=gross-levy
org_share=rhu(D(dist)*3500/10000); pool=dist-org_share
print('levy',levy,'distributable',dist,'org_share',org_share,'pool',pool)
w={'P1':4000,'P2':4500,'P3':4200}; wt=sum(w.values())
floors={k:int(D(pool)*v//wt) for k,v in w.items()}
rem_c=pool-sum(floors.values()); print('floors',floors,'remainder',rem_c,'weight_total',wt)
big=max(floors,key=lambda k:floors[k]); gs=dict(floors); gs[big]+=rem_c
print('gross_shares',gs,'sum',sum(gs.values()))
res={'P1':1500,'P2':3000,'P3':1500}; minor={'P1':0,'P2':0,'P3':1000}
wh={k:rhu(D(gs[k])*res[k]/10000) for k in gs}; es={k:rhu(D(gs[k])*minor[k]/10000) for k in gs}
net={k:gs[k]-wh[k]-es[k] for k in gs}
print('withholding',wh,'escrow',es,'net',net)
print('wh_total',sum(wh.values()),'es_total',sum(es.values()))
print('unallocated',gross-levy-org_share-sum(gs.values()))
rnd={k:rhu(D(pool)*w[k]/wt) for k in w}; print('naive round-per-row',rnd,'sum',sum(rnd.values()))

# transfer settlement at clock 2026-08-20, contract ends 2027-07-31, base 10,000,000 (P2)
import math
def settle(base,fee,mult,clock,ends='2027-07-31T00:00:00Z'):
    rd=max(0,(iso(ends)-iso(clock)).days); rtm=math.ceil(rd/30)
    monthly=rhu(D(base)/12); buy=rhu(D(monthly)*rtm*mult/10000)
    g=fee-buy; bp=500 if g<5000000 else 300
    com=rhu(D(g)*bp/10000); net=g-com
    return dict(remaining_days=rd,rtm=rtm,monthly=monthly,buyout=buy,gross=g,bp=bp,com=com,net=net)
print('settle fee10M',settle(10000000,10000000,5000,'2026-08-20T00:00:00Z'))
s=settle(10000000,10000000,5000,'2026-08-20T00:00:00Z')
com_wrong=rhu(D(s['gross'])*300/10000); print('wrong-tier(keyed on raw fee) commission',com_wrong,'net',s['gross']-com_wrong)
print('settle fee3M (negative)',settle(10000000,3000000,5000,'2026-08-20T00:00:00Z'))

# burnout
def score(p,cap,load,s,scommit):
    v=D('0.5')*min(D(1),D(p)/cap)+D('0.3')*D(load)/10+(D('0.2')*min(D(1),D(s)/scommit) if scommit else D(0))
    return rhu(v*100)
print('rolling p600 load6 s600', score(600,2700,6,600,600))
print('boundary p1080 load10 s600 ->',score(1080,2700,10,600,600),' s570 ->',score(1080,2700,10,570,600))
print('p720 load10 s600 ->',score(720,2700,10,600,600))
print('breach p2700 load10 s600 ->',score(2700,2700,10,600,600))
# season cumulative at 2026-08-25 for 1080 minutes since effective 2026-08-05
days=(iso('2026-08-25T00:00:00Z')-iso('2026-08-05T00:00:00Z')).days; weeks=max(1,math.ceil(days/7))
avg=rhu(D(1080)/weeks); print('days',days,'weeks',weeks,'avg',avg,'season score',score(avg,2700,10,600,600),'rolling now',score(0,2700,10,600,600))
# minor cap
cap_ft=min(1200,1080)-600; cap_ne=min(1200,1080); print('minor cap fulltime',cap_ft,'not enrolled',cap_ne,'stream',5*60)
print('deliverable per item fee', 1000000//2)
