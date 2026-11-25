"""Minimum point certificates as a function of a sound upper bound on selectivity."""
from bisect import bisect_left, bisect_right
from itertools import accumulate


class PrecisionCurve:
    def __init__(self, weights, passed, budget):
        self.yes=sorted(weights[key] for key in passed)
        self.no=sorted(w for key,w in weights.items() if key not in passed)
        self.yp=list(accumulate(self.yes,initial=0))
        self.np=list(accumulate(self.no,initial=0))
        self.n=len(weights)
        self.m=len(passed)
        self.budget=budget
        if self.yp[-1] > budget:
            raise ValueError("Use the complemented instance for rejection")
        self.thresholds=[]
        for t in sorted(set(weights.values())|{0}):
            base=0
            for values,prefix in ((self.yes,self.yp),(self.no,self.np)):
                a=bisect_right(values,t)
                base+=prefix[-1]-prefix[a]-(len(values)-a)*t
            self.thresholds.append((t,base,max(t,(self.no[-1] if self.no else 0)-t)))

    def gains(self,t,g):
        """Count and total of all savings >= positive g."""
        i=bisect_right(self.yes,t-g)
        j=bisect_left(self.no,t+g)
        return i+len(self.no)-j, i*t-self.yp[i]+self.np[-1]-self.np[j]-(len(self.no)-j)*t

    def minimum(self,upper):
        if not self.m<=upper<=self.n:
            raise ValueError("Invalid upper count")
        best=self.n
        for t,base,w in self.thresholds:
            needed=base+upper*t-self.budget
            if needed<=0:
                return 0
            if self.gains(t,1)[1]<needed:
                continue
            lo,hi=1,w+1
            while lo+1<hi:
                mid=(lo+hi)//2
                if self.gains(t,mid)[1]>=needed:
                    lo=mid
                else:
                    hi=mid
            count,total=self.gains(t,lo+1)
            best=min(best,count+(needed-total+lo-1)//lo)
        return best

    def largest_cap(self,k):
        """Largest sound count cap compatible with a k-answer certificate, or None."""
        best=-1
        for t,base,w in self.thresholds:
            count,top=self.gains(t,1)
            if count>k:
                lo,hi=1,w+1
                while lo+1<hi:
                    mid=(lo+hi)//2
                    if self.gains(t,mid)[0]>=k:
                        lo=mid
                    else:
                        hi=mid
                count,top=self.gains(t,lo+1)
                top+=(k-count)*lo
            if t==0:
                if base-top<=self.budget:
                    return self.n
            else:
                best=max(best,(self.budget-base+top)//t)
        return min(best,self.n) if best>=self.m else None

