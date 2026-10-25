import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sort_claim_audit.audit import audit, extract_claims, extract_evidence, SORTED_PHRASES, UNSORTED_PHRASES
from sort_claim_audit.__main__ import main

FIXTURES = Path(__file__).parent / 'fixtures'


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def project(self, claim='results are sorted', source='pass'):
        self.write('README.md', claim)
        self.write('main.py', source)
        return audit(self.root)

    def cli(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                code = main(list(args))
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_sorted_fixture(self):
        r = audit(FIXTURES / 'good/sorted')
        self.assertEqual([], r['findings'])
        self.assertEqual('sorted', r['verified_claims'][0]['family'])

    def test_unsorted_fixture(self):
        r = audit(FIXTURES / 'good/unsorted')
        self.assertEqual([], r['findings'])
        self.assertEqual('unsorted', r['verified_claims'][0]['family'])

    def test_bad_sorted_fixture(self):
        f = audit(FIXTURES / 'bad/sorted')['findings']
        self.assertEqual(1, len(f))
        self.assertEqual('documented-sorted-claim-false', f[0]['rule'])
        self.assertEqual('HIGH', f[0]['severity'])

    def test_bad_unsorted_fixture(self):
        f = audit(FIXTURES / 'bad/unsorted')['findings']
        self.assertEqual(1, len(f))
        self.assertEqual('documented-unsorted-claim-false', f[0]['rule'])
        self.assertEqual('HIGH', f[0]['severity'])
        self.assertEqual([{'path': 'main.py', 'line': 3, 'kind': 'sort'}], f[0]['evidence'])

    def test_testonly_fixture(self):
        f = audit(FIXTURES / 'testonly')['findings']
        self.assertEqual(1, len(f))
        self.assertEqual('documented-sorted-claim-false-test-only', f[0]['rule'])
        self.assertEqual('MEDIUM', f[0]['severity'])
        self.assertEqual(1, len(f[0]['evidence']))

    def test_unsorted_testonly(self):
        self.project('unsorted')
        self.write('tests/test_work.py', 'sorted(items)\nitems.sort()')
        f = audit(self.root)['findings'][0]
        self.assertEqual('documented-unsorted-claim-false-test-only', f['rule'])
        self.assertEqual('MEDIUM', f['severity'])
        self.assertEqual(2, len(f['evidence']))

    def test_both_families_no_source(self):
        self.write('README.md', 'sorted output. unsorted.')
        f = audit(self.root)['findings']
        self.assertEqual(2, len(f))
        self.assertTrue(all(x['severity'] == 'HIGH' for x in f))
        self.assertTrue(all(x['evidence'] == [{'kind': 'no-source'}] for x in f))

    def test_both_families_testonly(self):
        self.project('sorted output. unsorted.')
        self.write('fixtures/work.py', 'sorted(items)')
        self.assertEqual(2, len(audit(self.root)['findings']))

    def test_both_independent_with_production(self):
        r = self.project('sorted output. unsorted.', 'sorted(items)')
        self.assertEqual('unsorted', r['findings'][0]['family'])
        self.assertEqual('sorted', r['verified_claims'][0]['family'])

    def test_no_claim_with_evidence(self):
        self.assertEqual([], self.project('Hello', 'sorted(items)')['findings'])

    def test_empty_tree(self):
        self.assertEqual([], audit(self.root)['findings'])

    def test_ignore_evidence(self):
        self.project(source='sorted(items)')
        r = audit(self.root, ['main.py'])
        self.assertEqual([{'kind': 'no-source'}], r['findings'][0]['evidence'])

    def test_ignore_glob(self):
        self.project()
        self.write('vendor/worker.py', 'sorted(items)')
        self.assertEqual([], audit(self.root)['findings'])
        self.assertEqual(1, len(audit(self.root, ['vendor/*'])['findings']))

    def test_ignore_directory(self):
        self.project()
        self.write('vendor/worker.py', 'sorted(items)')
        self.assertEqual(1, len(audit(self.root, ['vendor'])['findings']))

    def test_ignore_docs(self):
        self.write('README.md', 'sorted output')
        self.assertEqual([], audit(self.root, ['README.md'])['claims'])

    def test_only_root_readme(self):
        self.write('sub/README.md', 'sorted output')
        self.assertEqual([], audit(self.root)['claims'])

    def test_nested_docs(self):
        self.write('docs/nested/guide.md', 'sorted output')
        self.assertEqual('docs/nested/guide.md', audit(self.root)['claims'][0]['path'])

    def test_other_markdown_ignored(self):
        self.write('guide.md', 'sorted output')
        self.assertEqual([], audit(self.root)['claims'])

    def test_symlink_file_skipped(self):
        self.project()
        target = self.write('outside.txt', 'sorted(items)')
        (self.root / 'linked.py').symlink_to(target)
        self.assertEqual([], audit(self.root)['production_evidence'])

    def test_symlink_directory_skipped(self):
        self.project()
        with tempfile.TemporaryDirectory() as outside:
            Path(outside, 'worker.py').write_text('sorted(items)')
            (self.root / 'linked').symlink_to(outside, target_is_directory=True)
            self.assertEqual([], audit(self.root)['production_evidence'])

    def test_env_never_opened(self):
        self.project()
        env = self.write('.env', 'PRIVATE_MARKER_9472')
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(env, path)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            code, output, error = self.cli(str(self.root), '--json')
        self.assertEqual(2, code)
        self.assertNotIn('PRIVATE_MARKER_9472', output + error)

    def test_invalid_source_reported(self):
        r = self.project(source='def !!!')
        self.assertEqual(1, len(r['errors']))
        self.assertEqual([], r['production_evidence'])

    def test_invalid_utf8_reported(self):
        self.project()
        (self.root / 'main.py').write_bytes(b'\xff')
        self.assertEqual(1, len(audit(self.root)['errors']))

    def test_dedup_same_line_same_kind(self):
        self.assertEqual(1, len(extract_evidence('sorted(a); sorted(b)', 'x.py')))

    def test_same_line_different_kind(self):
        self.assertEqual(2, len(extract_evidence('sorted(a); a.sort()', 'x.py')))

    def test_all_evidence_in_finding(self):
        r = self.project('unsorted', 'sorted(a)\na.sort()\nsorted(b)')
        self.assertEqual(3, len(r['findings'][0]['evidence']))

    def test_family_collapsed(self):
        self.assertEqual(1, len(self.project('sorted output. results are sorted.')['findings']))

    def test_claim_line_number(self):
        self.assertEqual(4, extract_claims('Intro.\n\n\nresults are sorted.')[0]['line'])

    def test_inline_code(self):
        self.assertEqual('sorted', extract_claims('`results are sorted`')[0]['family'])

    def test_fence_backticks(self):
        self.assertEqual([], extract_claims('```text\nresults are sorted\n```'))

    def test_fence_tildes(self):
        self.assertEqual([], extract_claims('~~~text\nresults are sorted\n~~~'))

    def test_fence_longer(self):
        self.assertEqual([], extract_claims('````\n```\nresults are sorted\n````'))

    def test_after_fence(self):
        self.assertEqual(4, extract_claims('```\nignored\n```\nresults are sorted')[0]['line'])

    def test_negated_unsorted(self):
        self.assertEqual(['unsorted'], [c['family'] for c in extract_claims('results are not sorted')])

    def test_sentence_negation_scope(self):
        self.assertEqual(['sorted'], [c['family'] for c in extract_claims('Never reverse. Results are sorted.')])

    def test_json_shape(self):
        code, output, _ = self.cli(str(FIXTURES / 'good/sorted'), '--json')
        self.assertEqual(0, code)
        r = json.loads(output)
        self.assertIn('findings', r)
        self.assertIn('verified_claims', r)

    def test_medium_default_exit(self):
        self.assertEqual(2, self.cli(str(FIXTURES / 'testonly'))[0])

    def test_medium_high_exit(self):
        code, out, _ = self.cli(str(FIXTURES / 'testonly'), '--fail-on', 'HIGH', '--json')
        self.assertEqual(0, code)
        self.assertEqual('MEDIUM', json.loads(out)['findings'][0]['severity'])

    def test_high_exit(self):
        self.assertEqual(2, self.cli(str(FIXTURES / 'bad/sorted'), '--fail-on', 'HIGH')[0])

    def test_usage_exit(self):
        self.assertEqual(1, self.cli('--unknown')[0])

    def test_invalid_threshold(self):
        self.assertEqual(1, self.cli('--fail-on', 'LOW')[0])

    def test_missing_directory(self):
        self.assertEqual(1, self.cli(str(self.root / 'missing'))[0])

    def test_version(self):
        code, output, _ = self.cli('--version')
        self.assertEqual((0, '0.1.0\n'), (code, output))

    def test_help(self):
        code, output, _ = self.cli('--help')
        self.assertEqual(0, code)
        self.assertIn('--ignore', output)

    def test_verbose(self):
        code, output, _ = self.cli(str(FIXTURES / 'good/sorted'), '--verbose')
        self.assertEqual(0, code)
        self.assertIn('verified_claims', output)

    def test_repeatable_ignore(self):
        self.project()
        self.write('a.py', 'sorted(items)')
        self.write('b.py', 'items.sort()')
        self.assertEqual(2, self.cli(str(self.root), '--ignore', 'a.py', '--ignore', 'b.py')[0])

    def test_self_audit_no_claims(self):
        r = audit(Path(__file__).resolve().parents[1])
        self.assertEqual([], r['claims'])
        self.assertEqual([], r['findings'])


def phrase_case(phrase, family):
    def test(self):
        self.assertEqual([family], [c['family'] for c in extract_claims(phrase.upper())])
    return test


for family, phrases in [('sorted', SORTED_PHRASES), ('unsorted', UNSORTED_PHRASES)]:
    for index, phrase in enumerate(phrases):
        setattr(AuditTests, 'test_phrase_' + family + '_' + str(index), phrase_case(phrase, family))

for index, phrase in enumerate(['the sorted flag enables sorting', 'sorted', 'sort', 'sort key',
                                'sort by name', 'sorted-output', 'outputs sorted', 'results sorted',
                                'sort results', 'resorted output', 'unsortedness']):
    def test(self, phrase=phrase):
        self.assertEqual([], extract_claims(phrase))
    setattr(AuditTests, 'test_nonclaim_' + str(index), test)

for index, negation in enumerate(['no', 'not', 'never', 'without', "doesn't", "don't", "isn't"]):
    def test(self, negation=negation):
        self.assertEqual([], extract_claims(negation + ' promises that results are sorted'))
    setattr(AuditTests, 'test_negation_' + str(index), test)

for index, source in enumerate(['sorted(x)', 'sorted(x, key=str)', 'sorted(x, reverse=True)',
                                'x.sort()', 'x.sort(key=str)', 'self.items.sort()',
                                'def unused(x):\n    sorted(x)']):
    def test(self, source=source):
        self.assertEqual(1, len(extract_evidence(source, 'main.py')))
    setattr(AuditTests, 'test_evidence_' + str(index), test)

for index, source in enumerate(['reversed(x)', 'sorted = x', 'x.sorted', 'call(sort=True)',
                                'key = itemgetter(0)', 'heapq.nsmallest(2, x)',
                                'heapq.nlargest(2, x)', 'bisect.bisect(x, y)',
                                'frame.sort_values()', 'thing.sorted(x)', 'np.sort(x)',
                                'numpy.sort(x)', 'import numpy as n; n.sort(x)']):
    def test(self, source=source):
        self.assertEqual([], extract_evidence(source, 'main.py'))
    setattr(AuditTests, 'test_nonevidence_' + str(index), test)

for index, path in enumerate(['tests/work.py', 'fixtures/work.py', 'test_work.py',
                              'work_test.py', 'nested/tests/work.py']):
    def test(self, path=path):
        self.project()
        self.write(path, 'sorted(items)')
        r = audit(self.root)
        self.assertEqual([], r['production_evidence'])
        self.assertEqual(1, len(r['test_only_evidence']))
    setattr(AuditTests, 'test_testclassification_' + str(index), test)

for index, path in enumerate(['docs/work.py', 'examples/work.py', 'nested/examples/work.py']):
    def test(self, path=path):
        self.project()
        self.write(path, 'sorted(items)')
        r = audit(self.root)
        self.assertEqual([], r['production_evidence'])
        self.assertEqual([], r['test_only_evidence'])
    setattr(AuditTests, 'test_excluded_' + str(index), test)

if __name__ == '__main__':
    unittest.main()
