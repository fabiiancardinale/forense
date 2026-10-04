"""Evaluate labeled holdout predictions, without silently dropping abstentions.
JSONL: {"id":"...", "label":"edited|original", "verdict":"..."}
"""
import argparse
import json
from pathlib import Path

def evaluate(rows):
    counts={'tp':0,'fp':0,'tn':0,'fn':0,'abstain_edited':0,'abstain_original':0}
    seen=set()
    for r in rows:
        if r['id'] in seen: raise ValueError('Duplicate sample id')
        seen.add(r['id'])
        if r['label'] not in ('edited','original'): raise ValueError('Invalid reference label')
        positive=r['label']=='edited'
        if r['verdict'] in ('inconclusive','failed','rejected'):
            counts['abstain_edited' if positive else 'abstain_original']+=1
        elif r['verdict'] in ('alteration_detected','suspicious'):
            counts['tp' if positive else 'fp']+=1
        elif r['verdict']=='no_indications':counts['fn' if positive else 'tn']+=1
        else:raise ValueError('Invalid verdict')
    total=sum(counts.values()); decided=total-counts['abstain_edited']-counts['abstain_original']
    ratio=lambda a,b:a/b if b else None
    return {**counts,'samples':total,'coverage':ratio(decided,total),
            'recall_including_abstentions':ratio(counts['tp'],counts['tp']+counts['fn']+counts['abstain_edited']),
            'false_positive_rate_all_originals':ratio(counts['fp'],counts['fp']+counts['tn']+counts['abstain_original']),
            'precision':ratio(counts['tp'],counts['tp']+counts['fp']),
            'note':'Métricas de triaje: suspicious cuenta positivo; no certifican autenticidad.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('predictions',type=Path);args=parser.parse_args()
    print(json.dumps(evaluate([json.loads(x) for x in args.predictions.read_text().splitlines() if x.strip()]),indent=2))
