"""Lab design validation: same-node calibration preserves hidden prompt ordering."""
from itertools import permutations

def check():
    cases=0
    for strengths in permutations([-5,10,15]):
        for r in [.1,.25,.9,1.4,2.0]:
            w=-10
            normalized=[]
            for used,effect in enumerate(strengths):
                new=w+r*effect*(.5**used)
                normalized.append((new-w)/(.5**used));w=new
            assert max(range(3),key=lambda i:normalized[i]) == strengths.index(15)
            cases+=1
    return cases
if __name__=='__main__':print({'synthetic_algebra_checks':check(),'official_score_evidence':False})
