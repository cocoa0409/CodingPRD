from decimal import Decimal as D, ROUND_HALF_UP
from datetime import date
def rh(x, q='1'):
    return D(x).quantize(D(q), rounding=ROUND_HALF_UP)
ZONE_RATE={'ZONE_CORE':D('0.0200'),'ZONE_PERIMETER':D('0.0125')}
CM={'FULL_SERVICE':D('1.00'),'LIMITED_SERVICE':D('0.85'),'BOUTIQUE':D('0.90'),'SHORT_TERM_RENTAL':D('1.15')}
ZF={'ZONE_CORE':D('1.0000'),'ZONE_PERIMETER':D('0.6250')}
FF={'FULL_SERVICE':500000,'LIMITED_SERVICE':300000,'BOUTIQUE':350000,'SHORT_TERM_RENTAL':150000}
def assess(method,zone,cls,rev,nights,adj=0):
    if method=='PCT_OF_ROOM_REVENUE':
        comp=int(rh(D(rev)*ZONE_RATE[zone]*CM[cls]))
        floor=nights*150
        gross=max(comp,floor)
    elif method=='PER_OCCUPIED_ROOM_NIGHT':
        gross=int(rh(D(nights)*300*CM[cls]))
    else:
        gross=int(rh(D(FF[cls])*ZF[zone]))
    capped=min(gross,2500000)
    return max(capped-adj,0), gross, capped
print('D1 prov(BOUTIQUE live)',assess('PCT_OF_ROOM_REVENUE','ZONE_CORE','BOUTIQUE',41225000,2000))
print('D1 final(FULL snapshot)',assess('PCT_OF_ROOM_REVENUE','ZONE_CORE','FULL_SERVICE',41225000,2000))
print('D3 b3 normal',assess('PCT_OF_ROOM_REVENUE','ZONE_PERIMETER','BOUTIQUE',30000000,900))
print('D3 b4 floor',assess('PCT_OF_ROOM_REVENUE','ZONE_PERIMETER','SHORT_TERM_RENTAL',1000000,3000))
print('D3 b1 cap',assess('PCT_OF_ROOM_REVENUE','ZONE_CORE','FULL_SERVICE',200000000,1000))
print('D3 b1 floor-above-cap',assess('PCT_OF_ROOM_REVENUE','ZONE_CORE','FULL_SERVICE',1000000,18000))
print('b2 340k?',assess('PCT_OF_ROOM_REVENUE','ZONE_CORE','LIMITED_SERVICE',20000000,600))
print('D20 375k',assess('PCT_OF_ROOM_REVENUE','ZONE_CORE','FULL_SERVICE',18750000,500))
# petition
tot=D(100000000)
for label,signed,cnt,n in [('b1 only',D(60000000),1,4),('b1+b4',D(65000000),2,4)]:
    print('D2/D10',label,'weighted',rh(signed/tot,'0.0001'),'headcount',rh(D(cnt)/D(n),'0.0001'))
# program performance
def perf(committed,nights):
    if nights==0:
        g=None;tier='TIER_UNPRODUCTIVE'
    else:
        g=int(rh(D(committed)/D(nights)));tier=('TIER_EFFICIENT' if g<=1500 else 'TIER_STANDARD' if g<=3000 else 'TIER_MARGINAL' if g<=6000 else 'TIER_UNPRODUCTIVE')
    share={'TIER_EFFICIENT':D('0.40'),'TIER_STANDARD':D('0.25'),'TIER_MARGINAL':D('0.10'),'TIER_UNPRODUCTIVE':D('0.00')}[tier]
    dmo=int(rh(D(committed)*share)); net=committed-dmo
    if nights==0: return g,tier,dmo,net,None,D('0.0000'),'UNDERPERFORMING'
    ncprn=int(rh(D(net)/D(nights))); idx=rh(D(2500)/D(ncprn),'0.0001')
    flag='MEETS_BENCHMARK' if idx>=1 else ('BELOW_BENCHMARK' if idx>=D('0.75') else 'UNDERPERFORMING')
    return g,tier,dmo,net,ncprn,idx,flag
print('D4 60000/24',perf(60000,24))
print('D4 wrong-retier',perf(60000,24)[0], 'net-retier would be', perf(60000,24)[4])
print('D12 60000/0',perf(60000,0))
# delinquency
def dq(out,days):
    return int(rh(D(out)*D('0.10'))), int(rh(D(out)*D('0.0005')*days))
print('D7 P1 824500/78',dq(824500,78))
print('D7 P2 824500/1',dq(824500,1))
print('D20 375000/5',dq(375000,5),'sum',2*dq(375000,5)[1],'agg',int(rh(D(750000)*D('0.0005')*5)))
# days late
print('days Nov25->Feb11',(date(2027,2,11)-date(2026,11,25)).days)
print('days Feb25->Feb26',(date(2027,2,26)-date(2027,2,25)).days)
print('days Nov25->Nov30',(date(2026,11,30)-date(2026,11,25)).days)
print('180 before 2027-08-01',date(2027,8,1).toordinal()-180, date.fromordinal(date(2027,8,1).toordinal()-180))
# funding ratio
for fc,tb in [(1164500,1000000),(764500,1000000)]:
    print('ratio',fc,tb,rh(D(fc)/D(tb),'0.0001'))
# caps on 1,000,000
for pct in ['0.15','0.10','0.60','0.50','0.25']:
    print('cap',pct,int(rh(D(1000000)*D(pct))))
