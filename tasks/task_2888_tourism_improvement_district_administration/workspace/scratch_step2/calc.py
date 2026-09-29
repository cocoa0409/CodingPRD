from decimal import Decimal, ROUND_HALF_UP
def rhu(x, places=0):
    q = Decimal(1) if places==0 else Decimal(1).scaleb(-places)
    return Decimal(x).quantize(q, rounding=ROUND_HALF_UP)

ZONE={'ZONE_CORE':Decimal('0.0200'),'ZONE_PERIMETER':Decimal('0.0125')}
CLS={'FULL_SERVICE':Decimal('1.00'),'LIMITED_SERVICE':Decimal('0.85'),'BOUTIQUE':Decimal('0.90'),'SHORT_TERM_RENTAL':Decimal('1.15')}
FLOOR=150; CAP=2500000; PER_NIGHT_RATE=300
FLAT={'FULL_SERVICE':500000,'LIMITED_SERVICE':300000,'BOUTIQUE':350000,'SHORT_TERM_RENTAL':150000}

def amount(method, zone, cls, nights, revenue, adj=0):
    if method=='PCT_OF_ROOM_REVENUE':
        rev=int(rhu(Decimal(revenue)*ZONE[zone]*CLS[cls]))
        fl=nights*FLOOR
        gross=max(rev,fl)
    elif method=='PER_OCCUPIED_ROOM_NIGHT':
        gross=int(rhu(Decimal(nights*PER_NIGHT_RATE)*CLS[cls]))
    else:
        gross=int(rhu(Decimal(FLAT[cls])*ZONE[zone]/Decimal('0.0200')))
    capped=min(gross,CAP)
    return max(capped-adj,0), gross

# Rule1/Rule2(a) divergence case
prov=amount('PCT_OF_ROOM_REVENUE','ZONE_CORE','LIMITED_SERVICE',3100,48500000)
fin =amount('PCT_OF_ROOM_REVENUE','ZONE_CORE','FULL_SERVICE',3100,48500000)
print('prov',prov,'final',fin)

# floor-dominant
print('floor', amount('PCT_OF_ROOM_REVENUE','ZONE_PERIMETER','LIMITED_SERVICE',900,1000000))
# cap
print('cap', amount('PCT_OF_ROOM_REVENUE','ZONE_CORE','FULL_SERVICE',5000,200000000))
# rounding half up
print('round', amount('PCT_OF_ROOM_REVENUE','ZONE_PERIMETER','BOUTIQUE',100,33333333))
# delinquency case statements
print('delq stmt', amount('PCT_OF_ROOM_REVENUE','ZONE_PERIMETER','FULL_SERVICE',1000,30000000))
# per occupied room night
print('pornight', amount('PER_OCCUPIED_ROOM_NIGHT','ZONE_CORE','BOUTIQUE',1200,0))
# tiered
print('tiered', amount('TIERED_BY_CLASSIFICATION','ZONE_PERIMETER','FULL_SERVICE',0,0))

# petition
print('w', rhu(Decimal(60000000)/Decimal(100000000),4), rhu(Decimal(1)/Decimal(4),4))
print('w2', rhu(Decimal(70000000)/Decimal(100000000),4))
# program performance
def perf(committed, nights, BENCH=2500):
    if nights==0:
        gcprn=None; tier='TIER_UNPRODUCTIVE'; pct=Decimal('0.00')
    else:
        gcprn=int(rhu(Decimal(committed)/Decimal(nights)))
        if gcprn<=1500: tier,pct='TIER_EFFICIENT',Decimal('0.40')
        elif gcprn<=3000: tier,pct='TIER_STANDARD',Decimal('0.25')
        elif gcprn<=6000: tier,pct='TIER_MARGINAL',Decimal('0.10')
        else: tier,pct='TIER_UNPRODUCTIVE',Decimal('0.00')
    share=int(rhu(Decimal(committed)*pct))
    net=committed-share
    ncprn=None if nights==0 else int(rhu(Decimal(net)/Decimal(nights)))
    idx=Decimal('0.0000') if nights==0 else rhu(Decimal(BENCH)/Decimal(ncprn),4)
    flag='NOT_MEASURED'
    if nights==0: flag='UNDERPERFORMING'
    elif idx>=1: flag='MEETS_BENCHMARK'
    elif idx>=Decimal('0.75'): flag='BELOW_BENCHMARK'
    else: flag='UNDERPERFORMING'
    return gcprn,tier,share,net,ncprn,idx,flag
print('perf 6000000/2400', perf(6000000,2400))
print('perf 6000000/0', perf(6000000,0))
print('perf 6000000/1200', perf(6000000,1200))
print('perf 4800000/3200', perf(4800000,3200))
# delinquency interest rounding
def dq(out, days):
    pen=int(rhu(Decimal(out)*Decimal('0.10')))
    intr=int(rhu(Decimal(out)*Decimal('0.0005')*days))
    return pen,intr
print('dq 375000/5', dq(375000,5))
print('dq sum vs agg', dq(375000,5)[1]*2, dq(750000,5)[1])
print('dq 824500/5', dq(824500,5))
print('dq 970000/5', dq(970000,5))
# funding ratio
print('fr', rhu(Decimal(970000)/Decimal(1000000),4), rhu(Decimal(870000)/Decimal(1000000),4))
