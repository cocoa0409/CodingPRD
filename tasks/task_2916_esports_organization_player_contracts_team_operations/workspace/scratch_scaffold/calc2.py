from decimal import Decimal, ROUND_HALF_UP
import math
def rhu(x): return int(Decimal(str(x)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
def score(p,cap,load,s,scommit):
    a=Decimal(50)*min(Decimal(1),Decimal(p)/Decimal(cap))
    b=Decimal(30)*Decimal(load)/Decimal(10)
    c=Decimal(20)*(min(Decimal(1),Decimal(s)/Decimal(scommit)) if scommit>0 else Decimal(0))
    return rhu(a+b+c), str(a+b+c)
cap=2700; scommit=15*60
print("rolling after A", score(900,cap,8,0,scommit))
print("rolling after B", score(1800,cap,8,0,scommit))
print("rolling after C", score(2700,cap,8,0,scommit))
print("breach case (s=900)", score(2700,cap,8,900,scommit))
print("exactly 70", score(2700,cap,5,225,scommit))
# season variant at clock 2026-08-24, effective 2026-08-10
from datetime import datetime,timezone
eff=datetime(2026,8,10,tzinfo=timezone.utc); clk=datetime(2026,8,24,tzinfo=timezone.utc)
days=(clk-eff).days; weeks=max(1,math.ceil(days/7)); avg=rhu(Decimal(2700)/weeks)
print("days",days,"weeks",weeks,"avg",avg)
print("season score", score(avg,cap,8,900,scommit))
print("rolling at 08-24 (p=0)", score(0,cap,8,900,scommit))
# minor cap
print("minor cap", min(1200,900)-600)
