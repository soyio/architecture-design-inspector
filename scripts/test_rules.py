"""Deterministic DOCX comment/fidelity regressions; not model behavior scores."""
import copy
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = pathlib.Path(__file__).resolve().parent / 'word_comments.py'
spec = importlib.util.spec_from_file_location('word_comments', SCRIPT)
wc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wc)


class WordCommentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.source = self.root / 'source.docx'
        self.output = self.root / 'reviewed.docx'
        self.plan = self.root / 'plan.json'
        doc = f'''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="{wc.W}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14"><w:body>
<w:p>
 <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
 <w:r><w:rPr><w:b/></w:rPr><w:t>响应目标两秒。</w:t></w:r><w:r><w:t>同步链路五秒。</w:t></w:r>
</w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>响应目标两秒。</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:drawing/></w:r></w:p>
<w:p><w:commentRangeStart w:id="7"/><w:r><w:t>已有批注和修订。</w:t></w:r><w:commentRangeEnd w:id="7"/><w:r><w:commentReference w:id="7"/></w:r><w:ins w:id="10" w:author="原作者"><w:r><w:t>新增文字。</w:t></w:r></w:ins></w:p>
<w:sectPr/></w:body></w:document>'''
        self.parts = {
            wc.DOC: doc.encode(),
            wc.TYPES: f'<Types xmlns="{wc.CT}"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/comments.xml" ContentType="{wc.COMMENT_CT}"/></Types>'.encode(),
            wc.RELS: f'<Relationships xmlns="{wc.REL}"><Relationship Id="rId1" Type="{wc.COMMENT_REL}" Target="comments.xml"/><Relationship Id="rId2" Type="image" Target="media/image.png"/></Relationships>'.encode(),
            'word/comments.xml': f'<w:comments xmlns:w="{wc.W}"><w:comment w:id="7" w:author="原审查者"><w:p><w:r><w:t>原批注。</w:t></w:r></w:p></w:comment></w:comments>'.encode(),
            'word/header1.xml': b'<preserve-header/>',
            'word/media/image.png': b'preserve-image-bytes',
            'word/commentsExtended.xml': b'<preserve-modern-comments/>',
            'customXml/item1.xml': b'<preserve-custom-xml/>',
        }
        self.write_package(self.source, self.parts)
        self.rows = [
            {'finding_id': 'F01', 'paragraph': 1, 'quote': '同步链路五秒', 'text': '预算冲突。\n建议澄清目标。'},
            {'finding_id': 'F02', 'paragraph': 2, 'quote': '响应目标两秒', 'text': '表格中的重复文字定位。'},
            {'finding_id': 'F03', 'paragraph': 3, 'quote': '', 'text': '图中节点需确认。'},
        ]
        self.save_plan()

    def tearDown(self):
        self.tmp.cleanup()

    def write_package(self, path, parts):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, data in parts.items():
                z.writestr(name, data)

    def save_plan(self, **overrides):
        plan = dict(source_sha256=wc.sha(self.source.read_bytes()), annotations=self.rows)
        plan.update(overrides)
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')

    def apply(self):
        return wc.apply(self.source, self.plan, self.output)

    def tamper(self, part, update):
        with zipfile.ZipFile(self.output) as z:
            data = {n: z.read(n) for n in z.namelist()}
        data[part] = update(data[part])
        self.write_package(self.output, data)

    def test_existing_comments_body_images_and_revisions_preserved(self):
        original = self.source.read_bytes()
        result = self.apply()
        self.assertTrue(result['valid'])
        self.assertEqual(result['added_comments'], 3)
        self.assertEqual(self.source.read_bytes(), original)
        with zipfile.ZipFile(self.output) as z:
            for name in ('word/media/image.png', 'word/header1.xml', 'customXml/item1.xml', 'word/commentsExtended.xml'):
                self.assertEqual(z.read(name), self.parts[name])
            comments = wc.parse(z.read('word/comments.xml'))
            bodies = wc.elements(comments, wc.W, 'comment')
            self.assertEqual([wc.attr(c, 'author') for c in bodies], ['原审查者'] + [wc.AUTHOR] * 3)
            self.assertEqual([wc.attr(c, 'id') for c in bodies], ['7', '8', '9', '10'])

    def test_new_comments_part_and_relationship_created(self):
        self.parts.pop('word/comments.xml')
        self.parts[wc.DOC] = self.parts[wc.DOC].replace(b'<w:commentRangeStart w:id="7"/>', b'').replace(b'<w:commentRangeEnd w:id="7"/>', b'').replace(b'<w:r><w:commentReference w:id="7"/></w:r>', b'')
        self.parts[wc.RELS] = f'<Relationships xmlns="{wc.REL}"/>'.encode()
        self.parts[wc.TYPES] = f'<Types xmlns="{wc.CT}"/>'.encode()
        self.write_package(self.source, self.parts)
        self.save_plan()
        self.assertTrue(self.apply()['valid'])

    def test_duplicate_text_targets_table_paragraph(self):
        self.rows = [self.rows[1]]
        self.save_plan()
        self.apply()
        with zipfile.ZipFile(self.output) as z:
            ps = wc.paragraphs(wc.parse(z.read(wc.DOC)))
        self.assertEqual(len(wc.elements(ps[0], wc.W, 'commentRangeStart')), 0)
        self.assertEqual(len(wc.elements(ps[1], wc.W, 'commentRangeStart')), 1)

    def test_multiple_comments_at_same_paragraph(self):
        self.rows.append(dict(self.rows[0], text='同段另一条批注。'))
        self.save_plan()
        self.assertEqual(self.apply()['added_comments'], 4)

    def test_zero_findings_outputs_exact_copy(self):
        self.rows = []
        self.save_plan()
        self.assertEqual(self.apply()['added_comments'], 0)
        self.assertEqual(self.source.read_bytes(), self.output.read_bytes())

    def test_source_hash_change_rejected_without_output(self):
        self.save_plan(source_sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.apply()
        self.assertFalse(self.output.exists())

    def test_wrong_quote_rejects_entire_batch(self):
        self.rows[-1]['quote'] = '不存在的原文'
        self.save_plan()
        with self.assertRaisesRegex(ValueError, 'Quote'):
            self.apply()
        self.assertFalse(self.output.exists())

    def test_invalid_paragraphs_rejected(self):
        for number in (True, 0, 999):
            self.rows[0]['paragraph'] = number
            self.save_plan()
            with self.assertRaisesRegex(ValueError, 'paragraph'):
                self.apply()

    def test_empty_quote_not_allowed_for_text(self):
        self.rows[0]['quote'] = ''
        self.save_plan()
        with self.assertRaisesRegex(ValueError, 'Quote'):
            self.apply()

    def test_original_and_existing_output_cannot_be_overwritten(self):
        with self.assertRaisesRegex(ValueError, 'overwrite'):
            wc.apply(self.source, self.plan, self.source)
        self.output.write_bytes(b'existing deliverable')
        with self.assertRaisesRegex(ValueError, 'new path'):
            self.apply()
        self.assertEqual(self.output.read_bytes(), b'existing deliverable')

    def test_tampered_author_detected(self):
        self.apply()
        self.tamper('word/comments.xml', lambda b: b.replace(wc.AUTHOR.encode(), b'Other Author', 1))
        with self.assertRaisesRegex(ValueError, 'author/content'):
            wc.verify(self.source, self.plan, self.output)

    def test_tampered_text_and_unrelated_parts_detected(self):
        for part, update in ((wc.DOC, lambda b: b.replace('两秒'.encode(), '九秒'.encode(), 1)), ('word/media/image.png', lambda b: b + b'!')):
            if self.output.exists():
                self.output.unlink()
            self.apply()
            self.tamper(part, update)
            with self.assertRaises(ValueError):
                wc.verify(self.source, self.plan, self.output)

    def test_protected_signed_legacy_and_strict_inputs_rejected(self):
        for name, data in (('_xmlsignatures/sig1.xml', b'<signature/>'), ('word/settings.xml', f'<w:settings xmlns:w="{wc.W}"><w:documentProtection w:enforcement="1"/></w:settings>'.encode())):
            parts = dict(self.parts, **{name: data})
            self.write_package(self.source, parts)
            self.save_plan()
            with self.assertRaises(ValueError):
                self.apply()
        legacy = self.root / 'source.doc'
        legacy.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, '.docx'):
            wc.read_package(legacy)
        strict = dict(self.parts)
        strict[wc.DOC] = strict[wc.DOC].replace(wc.W.encode(), b'http://purl.oclc.org/ooxml/wordprocessingml/main')
        self.write_package(self.source, strict)
        with self.assertRaisesRegex(ValueError, 'Transitional'):
            wc.read_package(self.source)

    def test_index_and_apply_cli(self):
        index = self.root / 'index.json'
        command = [sys.executable, '-X', 'utf8', str(SCRIPT)]
        result = subprocess.run(command + ['index', str(self.source), '--output', str(index)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(index.read_text('utf-8'))['paragraphs']
        self.assertTrue(rows[1]['in_table'])
        self.assertEqual(rows[2]['drawings'], 1)
        result = subprocess.run(command + ['apply', str(self.source), str(self.plan), '--output', str(self.output)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
