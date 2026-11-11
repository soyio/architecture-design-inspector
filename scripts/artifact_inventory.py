#!/usr/bin/env python3
"""Read only explicitly selected text artifacts; do not perform architecture judgment."""
import argparse, hashlib, json
from pathlib import Path

def within(root, path):
    p=(root/path).resolve()
    if not p.is_relative_to(root):
        raise ValueError('Artifact escapes root: '+str(path))
    return p

def read_text(p):
    data=p.read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    return data.decode('utf-8-sig')

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('root'); a.add_argument('paths', nargs='+'); a.add_argument('--output')
    args=a.parse_args(); root=Path(args.root).resolve(); rows=[]
    for rel in args.paths:
        p=within(root,rel)
        if not p.is_file(): raise ValueError('Not a file: '+rel)
        try:
            text=read_text(p)
            if '\x00' in text: raise ValueError('Non-text artifact')
            row={'artifact':p.relative_to(root).as_posix(), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                 'lines':[{'number':i,'text':s} for i,s in enumerate(text.splitlines(),1)]}
        except (UnicodeError,ValueError) as e:
            row={'artifact':p.relative_to(root).as_posix(),'unreadable':str(e)}
        rows.append(row)
    out=json.dumps({'artifacts':rows},ensure_ascii=False,indent=2)
    if args.output: Path(args.output).write_text(out,encoding='utf-8')
    else: print(out)
if __name__=='__main__': main()
