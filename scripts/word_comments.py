#!/usr/bin/env python3
"""Index DOCX paragraphs, add fixed-author comments, and verify source fidelity."""
import argparse
import hashlib
import io
import json
import posixpath
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import Node, minidom

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
COMMENT_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
COMMENT_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'
DOC = 'word/document.xml'
RELS = 'word/_rels/document.xml.rels'
TYPES = '[Content_Types].xml'
AUTHOR = '概要设计检查助手'
XMLNS = 'http://www.w3.org/2000/xmlns/'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('DTD/entity declarations are not supported')
    return minidom.parseString(data)


def xml_bytes(doc):
    return doc.toxml(encoding='utf-8')


def elements(node, namespace, name):
    return list(node.getElementsByTagNameNS(namespace, name))


def attr(node, name):
    return node.getAttributeNS(W, name)


def node(doc, name, attrs=None, namespace=W, prefix='w'):
    result = doc.createElementNS(namespace, prefix + ':' + name if prefix else name)
    if prefix:
        result.setAttributeNS(XMLNS, 'xmlns:' + prefix, namespace)
    else:
        result.setAttributeNS(XMLNS, 'xmlns', namespace)
    for key, value in (attrs or {}).items():
        if namespace == W:
            result.setAttributeNS(W, 'w:' + key, str(value))
        else:
            result.setAttribute(key, str(value))
    return result


def paragraph_content(p):
    text = []
    drawings = 0

    def walk(parent):
        nonlocal drawings
        for child in parent.childNodes:
            if child.nodeType != Node.ELEMENT_NODE:
                continue
            if child.namespaceURI == W:
                tag = child.localName
                if tag in ('p', 'del', 'moveFrom'):
                    continue
                if tag == 't':
                    text.append(''.join(x.data for x in child.childNodes if x.nodeType == Node.TEXT_NODE))
                    continue
                if tag in ('tab', 'br', 'cr'):
                    text.append('\t' if tag == 'tab' else '\n')
                if tag in ('drawing', 'pict', 'object'):
                    drawings += 1
            walk(child)
    walk(p)
    return ''.join(text), drawings


def paragraphs(doc):
    bodies = elements(doc, W, 'body')
    if len(bodies) != 1:
        raise ValueError('Expected one Transitional Word document body')
    return elements(bodies[0], W, 'p')


def read_package(path):
    if path.suffix.lower() != '.docx':
        raise ValueError('Only .docx is supported; convert legacy .doc explicitly first')
    raw = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as package:
        if package.testzip():
            raise ValueError('Corrupt DOCX ZIP')
        infos = package.infolist()
        if len({x.filename for x in infos}) != len(infos):
            raise ValueError('Duplicate DOCX ZIP entries')
        parts = {x.filename: package.read(x) for x in infos}
        archive_comment = package.comment
    for required in (DOC, TYPES):
        if required not in parts:
            raise ValueError('Missing DOCX part: ' + required)
    doc = parse(parts[DOC])
    paragraphs(doc)
    return raw, parts, infos, archive_comment, doc


def comments_path(parts):
    if RELS not in parts:
        return 'word/comments.xml'
    rels = parse(parts[RELS])
    matches = [r for r in elements(rels, REL, 'Relationship') if r.getAttribute('Type') == COMMENT_REL]
    if len(matches) > 1:
        raise ValueError('Multiple main-document comments relationships')
    if not matches:
        if 'word/comments.xml' in parts:
            raise ValueError('Existing comments part has no relationship')
        return 'word/comments.xml'
    rel = matches[0]
    if rel.getAttribute('TargetMode') == 'External':
        raise ValueError('External comments relationship is unsupported')
    target = rel.getAttribute('Target')
    result = posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join('word', target))
    if not result.startswith('word/') or result not in parts:
        raise ValueError('Missing or unsafe comments relationship target')
    return result


def check_editable(parts):
    if any(name.lower().startswith('_xmlsignatures/') for name in parts):
        raise ValueError('Digitally signed documents require an approved unsigned copy')
    if 'word/settings.xml' in parts:
        for protection in elements(parse(parts['word/settings.xml']), W, 'documentProtection'):
            if attr(protection, 'enforcement').lower() in ('1', 'true', 'on'):
                raise ValueError('Editing-protected document requires an approved editable copy')


def load_plan(path, raw, doc):
    plan = json.loads(path.read_text('utf-8-sig'))
    if not isinstance(plan, dict) or plan.get('source_sha256') != sha(raw):
        raise ValueError('Source SHA-256 does not match the annotation plan')
    rows = plan.get('annotations')
    if not isinstance(rows, list):
        raise ValueError('annotations must be an array')
    ps = paragraphs(doc)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each annotation must be an object')
        p = row.get('paragraph')
        if type(p) is not int or not 1 <= p <= len(ps):
            raise ValueError('Invalid paragraph number: ' + str(p))
        if not isinstance(row.get('finding_id'), str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', row['finding_id']):
            raise ValueError('Invalid finding_id')
        if not isinstance(row.get('text'), str) or not row['text'].strip():
            raise ValueError('Empty comment text')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in row['text']):
            raise ValueError('Comment text contains invalid XML control characters')
        quote = row.get('quote')
        text, drawings = paragraph_content(ps[p - 1])
        if not isinstance(quote, str) or (quote and quote not in text) or (not quote and (text or not drawings)):
            raise ValueError('Quote does not match paragraph ' + str(p))
    return rows


def comment_text(row):
    return '[' + row['finding_id'] + '] ' + row['text'].replace('\r\n', '\n').replace('\r', '\n')


def existing_ids(doc, comments):
    ids = []
    for c in elements(comments, W, 'comment'):
        value = attr(c, 'id')
        if not re.fullmatch(r'\d+', value) or value in ids:
            raise ValueError('Invalid or duplicate existing comment ID')
        ids.append(value)
    anchors = set()
    for tag in ('commentRangeStart', 'commentRangeEnd', 'commentReference'):
        anchors.update(attr(e, 'id') for e in elements(doc, W, tag))
    if not anchors.issubset(ids):
        raise ValueError('Existing comment anchors have missing comment bodies')
    return ids


def new_comments_doc():
    doc = minidom.Document()
    doc.appendChild(node(doc, 'comments'))
    return doc


def add_comment(doc, comments, p, cid, row, date):
    # Keep all source runs intact; wrap the paragraph contents, after pPr.
    start = node(doc, 'commentRangeStart', {'id': cid})
    props = [x for x in p.childNodes if x.nodeType == Node.ELEMENT_NODE and x.namespaceURI == W and x.localName == 'pPr']
    first = props[-1].nextSibling if props else p.firstChild
    p.insertBefore(start, first)
    p.appendChild(node(doc, 'commentRangeEnd', {'id': cid}))
    run = node(doc, 'r')
    props = node(doc, 'rPr')
    props.appendChild(node(doc, 'rStyle', {'val': 'CommentReference'}))
    run.appendChild(props)
    run.appendChild(node(doc, 'commentReference', {'id': cid}))
    p.appendChild(run)
    comment = node(comments, 'comment', {'id': cid, 'author': AUTHOR, 'initials': '概要', 'date': date})
    for line in comment_text(row).split('\n'):
        cp = node(comments, 'p')
        cr = node(comments, 'r')
        ct = node(comments, 't')
        ct.setAttributeNS('http://www.w3.org/XML/1998/namespace', 'xml:space', 'preserve')
        ct.appendChild(comments.createTextNode(line))
        cr.appendChild(ct)
        cp.appendChild(cr)
        comment.appendChild(cp)
    comments.documentElement.appendChild(comment)


def wire(parts, path):
    if RELS in parts:
        rels = parse(parts[RELS])
    else:
        rels = minidom.Document()
        root = rels.createElementNS(REL, 'Relationships')
        root.setAttribute('xmlns', REL)
        rels.appendChild(root)
    relationships = elements(rels, REL, 'Relationship')
    if not any(r.getAttribute('Type') == COMMENT_REL for r in relationships):
        used = {r.getAttribute('Id') for r in relationships}
        i = 1
        while 'rId' + str(i) in used:
            i += 1
        rels.documentElement.appendChild(node(rels, 'Relationship', {'Id': 'rId' + str(i), 'Type': COMMENT_REL, 'Target': posixpath.relpath(path, 'word')}, REL, ''))
        parts[RELS] = xml_bytes(rels)
    types = parse(parts[TYPES])
    overrides = [o for o in elements(types, CT, 'Override') if o.getAttribute('PartName') == '/' + path]
    if overrides:
        if len(overrides) != 1 or overrides[0].getAttribute('ContentType') != COMMENT_CT:
            raise ValueError('Invalid comments content type')
    else:
        types.documentElement.appendChild(node(types, 'Override', {'PartName': '/' + path, 'ContentType': COMMENT_CT}, CT, ''))
        parts[TYPES] = xml_bytes(types)


def verify(source, plan_path, output):
    raw, before, _, _, original = read_package(source)
    rows = load_plan(plan_path, raw, original)
    reviewed_raw, after, _, _, reviewed = read_package(output)
    if not rows:
        if reviewed_raw != raw:
            raise ValueError('Zero-comment output must be a byte-for-byte source copy')
        return {'valid': True, 'added_comments': 0, 'source_sha256': sha(raw)}
    path = comments_path(before)
    if comments_path(after) != path or path not in after:
        raise ValueError('Missing or changed comments part')
    allowed = {DOC, RELS, TYPES, path}
    if set(before) - set(after) or set(after) - set(before) - allowed:
        raise ValueError('Unexpected package parts added or removed')
    for name in before:
        if name not in allowed and before[name] != after[name]:
            raise ValueError('Unrelated source part changed: ' + name)
    old = parse(before[path]) if path in before else new_comments_doc()
    new = parse(after[path])
    if new.documentElement.namespaceURI != W or new.documentElement.localName != 'comments':
        raise ValueError('Invalid comments root element')
    old_ids = existing_ids(original, old)
    existing_ids(reviewed, new)
    new_bodies = {attr(c, 'id'): c for c in elements(new, W, 'comment')}
    for old_body in elements(old, W, 'comment'):
        if attr(old_body, 'id') not in new_bodies or old_body.toxml() != new_bodies[attr(old_body, 'id')].toxml():
            raise ValueError('Existing comment changed')
    added = [c for c in elements(new, W, 'comment') if attr(c, 'id') not in old_ids]
    if len(added) != len(rows):
        raise ValueError('New comment count does not match plan')
    ps = paragraphs(reviewed)
    for body, row in zip(added, rows):
        cid = attr(body, 'id')
        content = '\n'.join(paragraph_content(p)[0] for p in elements(body, W, 'p'))
        if attr(body, 'author') != AUTHOR or content != comment_text(row):
            raise ValueError('New comment author/content mismatch')
        target = ps[row['paragraph'] - 1]
        markers = {}
        for tag in ('commentRangeStart', 'commentRangeEnd', 'commentReference'):
            found = [e for e in elements(reviewed, W, tag) if attr(e, 'id') == cid]
            if len(found) != 1:
                raise ValueError('Missing or duplicate comment anchor: ' + cid)
            parent = found[0].parentNode
            if tag == 'commentReference':
                parent = parent.parentNode
            if parent is not target:
                raise ValueError('Comment is anchored to the wrong paragraph')
            markers[tag] = found[0].parentNode if tag == 'commentReference' else found[0]
        siblings = list(target.childNodes)
        if not siblings.index(markers['commentRangeStart']) < siblings.index(markers['commentRangeEnd']) < siblings.index(markers['commentReference']):
            raise ValueError('Comment anchor order is invalid')
        # Strip only this addition, then compare the full document DOM below.
        for tag in ('commentRangeStart', 'commentRangeEnd'):
            e = next(e for e in elements(reviewed, W, tag) if attr(e, 'id') == cid)
            e.parentNode.removeChild(e)
        ref = next(e for e in elements(reviewed, W, 'commentReference') if attr(e, 'id') == cid)
        run = ref.parentNode
        run.parentNode.removeChild(run)
    if original.toxml() != reviewed.toxml():
        raise ValueError('Document text, formatting, figures, revisions, or existing anchors changed')
    expected_wiring = dict(before)
    wire(expected_wiring, path)
    for name in (RELS, TYPES):
        if name not in after or parse(expected_wiring[name]).toxml() != parse(after[name]).toxml():
            raise ValueError('Unexpected relationship/content-type changes: ' + name)
    return {'valid': True, 'author': AUTHOR, 'added_comments': len(rows), 'source_sha256': sha(raw), 'source_content_preserved': True}


def apply(source, plan_path, output):
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError('Output must be a new path and cannot overwrite the source')
    raw, parts, infos, archive_comment, doc = read_package(source)
    rows = load_plan(plan_path, raw, doc)
    check_editable(parts)
    if not rows:
        result = raw
    else:
        path = comments_path(parts)
        comments = parse(parts[path]) if path in parts else new_comments_doc()
        ids = existing_ids(doc, comments)
        next_id = max((int(x) for x in ids), default=-1) + 1
        ps = paragraphs(doc)
        date = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        for i, row in enumerate(rows):
            add_comment(doc, comments, ps[row['paragraph'] - 1], str(next_id + i), row, date)
        parts[DOC] = xml_bytes(doc)
        parts[path] = xml_bytes(comments)
        wire(parts, path)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as package:
            package.comment = archive_comment
            old_names = {x.filename for x in infos}
            for info in infos:
                package.writestr(info, parts[info.filename])
            for name in parts.keys() - old_names:
                package.writestr(name, parts[name])
        result = stream.getvalue()
    # Exclusive creation prevents accidental overwrites; failed verification removes only this new file.
    with output.open('xb') as destination:
        destination.write(result)
    try:
        report = verify(source, plan_path, output)
        if source.read_bytes() != raw:
            raise ValueError('Source changed while comments were being applied')
    except Exception:
        output.unlink()
        raise
    return dict(report, output=str(output.resolve()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    index = sub.add_parser('index')
    index.add_argument('source', type=Path)
    index.add_argument('--output', type=Path, required=True)
    add = sub.add_parser('apply')
    add.add_argument('source', type=Path)
    add.add_argument('plan', type=Path)
    add.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('verify')
    check.add_argument('source', type=Path)
    check.add_argument('plan', type=Path)
    check.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'index':
            raw, _, _, _, doc = read_package(args.source)
            if args.output.resolve() == args.source.resolve() or args.output.exists():
                raise ValueError('Index output must be a new path')
            rows = []
            for i, p in enumerate(paragraphs(doc), 1):
                text, drawings = paragraph_content(p)
                rows.append({'paragraph': i, 'text': text, 'drawings': drawings, 'in_table': any(a.localName == 'tc' and a.namespaceURI == W for a in ancestors(p))})
            report = {'source': str(args.source.resolve()), 'source_sha256': sha(raw), 'paragraphs': rows}
            with args.output.open('x', encoding='utf-8') as destination:
                json.dump(report, destination, ensure_ascii=False, indent=2)
            report = {'output': str(args.output.resolve()), 'paragraphs': len(rows), 'source_sha256': sha(raw)}
        elif args.action == 'apply':
            report = apply(args.source, args.plan, args.output)
        else:
            report = verify(args.source, args.plan, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as exc:
        # XML parsing errors also produce a concise nonzero result for CLI callers.
        print(json.dumps({'valid': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)


def ancestors(p):
    parent = p.parentNode
    while parent is not None:
        yield parent
        parent = parent.parentNode


if __name__ == '__main__':
    main()
