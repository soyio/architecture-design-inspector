#!/usr/bin/env python3
"""Validate structure and citations only; semantic correctness requires behavioral evaluation."""
import argparse, json
from pathlib import Path
from artifact_inventory import within, read_text

KINDS={'conflict','omission','risk','drift','evidence_gap'}
STATUS={'findings','clear','insufficient_evidence','out_of_scope'}
SEVERITY={'critical','high','medium','low'}
CONFIDENCE={'confirmed','suspected','insufficient'}

def enum_valid(value, allowed):
    return isinstance(value,str) and value in allowed

def validate(report, root):
    errors=[]
    if not isinstance(report,dict): return ['report must be an object']
    for key in ['skill','status','scope','baseline','dimensions','findings','limitations','exceptions']:
        if key not in report: errors.append('missing '+key)
    if not enum_valid(report.get('status'),STATUS): errors.append('invalid status')
    skill=report.get('skill')
    prefix,maximum='D',17
    if skill != 'architecture-design-inspector': errors.append('invalid skill')
    dims={prefix+str(i).zfill(2) for i in range(1,maximum+1)}
    for key in ['scope','baseline']:
        if not isinstance(report.get(key),str) or not report.get(key,'').strip(): errors.append('nonempty text required '+key)
    for key in ['dimensions','findings','limitations','exceptions']:
        if not isinstance(report.get(key),list): errors.append('array required '+key)
    findings=report.get('findings',[])
    if not isinstance(findings,list): return errors
    seen=set()
    for idx,f in enumerate(findings):
        where='finding '+str(idx)
        if not isinstance(f,dict): errors.append(where+' must be object'); continue
        for key in ['id','dimension','kind','severity','title','claim','evidence','impact','recommendation','confidence']:
            if key not in f: errors.append(where+' missing '+key)
        fid=f.get('id')
        if not isinstance(fid,str) or not fid.strip() or fid in seen: errors.append(where+' invalid or duplicate id')
        else: seen.add(fid)
        if not enum_valid(f.get('dimension'),dims): errors.append(where+' invalid dimension')
        for key,allowed in [('kind',KINDS),('severity',SEVERITY),('confidence',CONFIDENCE)]:
            if not enum_valid(f.get(key),allowed): errors.append(where+' invalid '+key)
        for key in ['title','claim','impact','recommendation']:
            if not isinstance(f.get(key),str) or not f.get(key,'').strip(): errors.append(where+' empty '+key)
        if f.get('kind')=='evidence_gap' and f.get('confidence')!='insufficient': errors.append(where+' evidence gap must remain insufficient')
        ev=f.get('evidence',[])
        if not isinstance(ev,list) or not ev: errors.append(where+' requires source evidence'); continue
        for j,e in enumerate(ev):
            tag=where+' evidence '+str(j)
            try:
                if not isinstance(e,dict): raise ValueError('object required')
                path=within(root,e['artifact']); lines=read_text(path).splitlines(); start=e['start']; end=e['end']
                if isinstance(start,bool) or isinstance(end,bool) or not isinstance(start,int) or not isinstance(end,int): raise ValueError('integer line numbers required')
                if not 1<=start<=end<=len(lines): raise ValueError('line range invalid')
                quote=e['quote']
                if not isinstance(quote,str) or not quote.strip() or quote not in '\n'.join(lines[start-1:end]): raise ValueError('quote not in cited lines')
            except (KeyError,OSError,ValueError,TypeError,UnicodeError) as exc: errors.append(tag+': '+str(exc))
    dimensions=report.get('dimensions',[])
    if isinstance(dimensions,list):
        for d in dimensions:
            if not isinstance(d,dict) or not enum_valid(d.get('id'),dims) or not enum_valid(d.get('applicability'),{'applicable','not_applicable','unknown'}) or not enum_valid(d.get('coverage'),{'reviewed','not_reviewed'}) or not isinstance(d.get('reason'),str) or not d.get('reason','').strip(): errors.append('invalid dimension coverage entry')
    substantive=[f for f in findings if isinstance(f,dict) and f.get('kind')!='evidence_gap']
    if report.get('status')=='clear' and findings: errors.append('clear cannot contain findings')
    if report.get('status')=='findings' and not substantive: errors.append('findings status requires substantive finding')
    if report.get('status')=='insufficient_evidence' and substantive: errors.append('substantive findings require findings status')
    return errors

def main():
    a=argparse.ArgumentParser(description=__doc__); a.add_argument('report'); a.add_argument('--artifact-root',required=True)
    args=a.parse_args(); root=Path(args.artifact_root).resolve()
    report=json.loads(Path(args.report).read_text(encoding='utf-8-sig')); errors=validate(report,root)
    print(json.dumps({'valid':not errors,'errors':errors},ensure_ascii=False,indent=2))
    raise SystemExit(1 if errors else 0)
if __name__=='__main__': main()
