"""Aggregate actual sequential operation times, with setups as explicit one-time costs."""
import csv,json,sys
from collections import Counter,defaultdict
from statistics import median
from pathlib import Path

HERE=Path(__file__).resolve().parent


def read(name):
    with (HERE/name).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))


def write(name,rows):
    with (HERE/name).open('w',encoding='utf-8',newline='') as f:
        dst=csv.DictWriter(f,fieldnames=list(rows[0]));dst.writeheader();dst.writerows(rows)


def main():
    test=read('test.csv')
    setup=read('setup.csv')
    select=json.loads((HERE/'selection.json').read_text())
    cohorts={'primary':{r['schema'] for r in test if r['schema']!='codebase_community'},
             'codebase':{'codebase_community'},'whole':{r['schema'] for r in test}}
    cohorts.update({r['schema']:{r['schema']} for r in test if r['schema']!='codebase_community'})
    out=[]; paired=[]; oracle=[]
    for cohort,schemas in cohorts.items():
        for layout in ('released','cover'):
            cost=sum((int(r['discovery_ns'])+int(r['index_build_ns'])+int(r['analyze_ns'])) for r in setup if
                     r['schema'] in schemas and r['stage']=='test' and r['layout']==layout)
            for budget in (100,512):
                q=select[f'{layout}:{budget}']
                methods={'native_cap':'cap','native_count':'count','challenger':q['challenger'],
                         'deploy':q['deployment'],'fixed_cert':q['fixed_cert'],
                         'matched_direct':q['challenger'].replace('cert/','direct/'),'pilot_native':q['fixed_native']}
                group=[r for r in test if r['schema'] in schemas and r['layout']==layout and int(r['budget'])==budget]
                # Descriptive hindsight control. Every alternative uses the same original query.
                per_case=defaultdict(lambda:defaultdict(list))
                for r in group:
                    per_case[r['schema'],r['id']][r['policy']].append(int(r['ns'])/1e6)
                domains={key:{policy:median(obs) for policy,obs in estimates.items()}
                         for key,estimates in per_case.items()}
                oracle.append(dict(cohort=cohort,layout=layout,budget=budget,cases=len(domains),
                     sum_per_case_median_cap_ms=sum(x['cap'] for x in domains.values()),
                     perfect_choice_cap_vs_challenger_ms=sum(min(x['cap'],x[q['challenger']]) for x in domains.values()),
                     perfect_choice_all_tested_ms=sum(min(x.values()) for x in domains.values())))
                times={}
                for label,method in methods.items():
                    subset=[r for r in group if r['policy']==method]
                    rounds=defaultdict(int); parser=defaultdict(int); routes=Counter()
                    for r in subset:
                        rep=int(r['round'])
                        rounds[rep]+=int(r['ns'])
                        parser[rep]+=int(r['rewrite_ns'])
                        if not rep: routes[r['route']]+=1
                    assert len(rounds)==5
                    warm=median(rounds.values())
                    out.append(dict(cohort=cohort,layout=layout,budget=budget,policy=label,configuration=method,
                                    cases=len(subset)//5,median_ms=warm/1e6,min_ms=min(rounds.values())/1e6,
                                    max_ms=max(rounds.values())/1e6,median_rewrite_ms=median(parser.values())/1e6,
                                    setup_ms=cost/1e6,first_stream_ms=(warm+cost)/1e6,routes=json.dumps(routes,sort_keys=True)))
                    times[label]=rounds
                for control in ('native_cap','native_count','matched_direct','fixed_cert'):
                    delta=[(times['challenger'][i]-times[control][i])/1e6 for i in range(5)]
                    paired.append(dict(cohort=cohort,layout=layout,budget=budget,comparison='challenger-minus-'+control,
                                       median_ms=median(delta),min_ms=min(delta),max_ms=max(delta),
                                       challenger_wins=sum(x<0 for x in delta)))
    write('summary.csv',out);write('paired.csv',paired);write('oracle.csv',oracle)
    print('primary comparison')
    for r in out:
        if r['cohort']!='primary' or r['policy'] not in ('native_cap','native_count','deploy','challenger','matched_direct'):continue
        print(r['layout'],r['budget'],r['policy'],r['configuration'],r['cases'],round(r['median_ms'],3),round(r['first_stream_ms'],2),r['routes'])
    trial=read('pilot.csv')
    print('pilot decision evaluation total ms',sum(int(r['ns']) for r in trial)/1e6)
    print('pilot covering setup ms',sum(int(r['discovery_ns'])+int(r['index_build_ns'])+int(r['analyze_ns']) for r in setup if r['stage']=='pilot')/1e6)

if __name__=='__main__':main()

