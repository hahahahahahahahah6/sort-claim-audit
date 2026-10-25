"""Offline documentation ordering audit using Markdown text and Python ASTs."""
import ast
import fnmatch
import re
from pathlib import Path

SORTED_PHRASES = (
    'sorted output', 'outputs are sorted', 'results are sorted', 'sorted results',
    'sorts results', 'sorts output', 'sorted by', 'in sorted order',
    'sorted alphabetically', 'sorted numerically', 'in ascending order',
    'in descending order',
)
UNSORTED_PHRASES = (
    'unsorted', 'not sorted', 'in insertion order', 'preserves input order',
    'preserves insertion order', 'in original order', 'keeps input order',
)
NEGATION = re.compile(r"\b(?:no|not|never|without|doesn't|don't|isn't)\b", re.I)
PATTERNS = {
    family: re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(p) for p in phrases) + r')(?!\w)', re.I)
    for family, phrases in [('sorted', SORTED_PHRASES), ('unsorted', UNSORTED_PHRASES)]
}


def extract_claims(text, path='README.md'):
    """Return phrase occurrences outside fenced blocks, retaining line numbers."""
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not line[marker.end():].strip():
                fence = None
            lines.append('')
        elif marker:
            fence = marker[1]
            lines.append('')
        else:
            lines.append(line)
    prose = '\n'.join(lines)
    claims = []
    for sentence in re.finditer(r'[^.!?]+(?:[.!?]|$)', prose):
        segment = sentence[0]
        for family, pattern in PATTERNS.items():
            if family == 'sorted' and NEGATION.search(segment):
                continue
            for match in pattern.finditer(segment):
                offset = sentence.start() + match.start()
                claims.append({'family': family, 'path': path,
                               'line': prose.count('\n', 0, offset) + 1,
                               'phrase': match[0]})
    return claims


def extract_evidence(text, path):
    tree = ast.parse(text, filename=path)
    items = {}
    numpy_modules = {'np', 'numpy'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'numpy':
                    numpy_modules.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        kind = None
        if isinstance(func, ast.Name) and func.id == 'sorted':
            kind = 'sorted'
        elif isinstance(func, ast.Attribute) and func.attr == 'sort':
            # Known numpy module calls are explicitly outside the evidence table.
            if not (isinstance(func.value, ast.Name) and func.value.id in numpy_modules):
                kind = 'sort'
        if kind:
            items[(node.lineno, kind)] = {'path': path, 'line': node.lineno, 'kind': kind}
    return list(items.values())


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('audit path must be a directory')
    claims, production, test_only, errors = [], [], [], []
    source_count = 0
    def ignored(relative):
        return any(fnmatch.fnmatchcase(relative, pattern) for pattern in ignore)
    def walk(directory):
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            relative = entry.relative_to(root).as_posix()
            if entry.is_symlink() or ignored(relative):
                continue
            if entry.is_dir():
                if entry.name not in {'.git', '.venv', 'venv', '__pycache__', 'build', 'dist'}:
                    yield from walk(entry)
            elif entry.is_file():
                yield entry, relative
    for path, relative in walk(root):
        parts = Path(relative).parts
        is_doc = relative == 'README.md' or (parts[0] == 'docs' and path.suffix == '.md')
        if is_doc:
            try:
                claims.extend(extract_claims(path.read_text(encoding='utf-8'), relative))
            except (OSError, UnicodeError) as exc:
                errors.append({'path': relative, 'error': str(exc)})
        if path.suffix != '.py' or any(p in {'docs', 'examples'} for p in parts[:-1]):
            continue
        testing = any(p in {'tests', 'fixtures'} for p in parts[:-1]) or path.name.startswith('test_') or path.name.endswith('_test.py')
        if not testing:
            source_count += 1
        try:
            evidence = extract_evidence(path.read_text(encoding='utf-8'), relative)
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append({'path': relative, 'error': str(exc)})
            continue
        (test_only if testing else production).extend(evidence)
    findings, verified = [], []
    for family in ('sorted', 'unsorted'):
        family_claims = [c for c in claims if c['family'] == family]
        if not family_claims:
            continue
        severity, evidence, suffix = None, [], ''
        if not source_count:
            severity, evidence = 'HIGH', [{'kind': 'no-source'}]
        elif family == 'sorted' and not production:
            severity = 'MEDIUM' if test_only else 'HIGH'
            evidence = test_only
            suffix = '-test-only' if test_only else ''
        elif family == 'unsorted' and production:
            severity, evidence = 'HIGH', production
        elif family == 'unsorted' and test_only:
            severity, evidence, suffix = 'MEDIUM', test_only, '-test-only'
        if severity:
            findings.append({'rule': 'documented-' + family + '-claim-false' + suffix,
                             'severity': severity, 'family': family,
                             'claims': family_claims, 'evidence': evidence})
        else:
            verified.append({'family': family, 'claims': family_claims,
                             'evidence': production if family == 'sorted' else []})
    return {'findings': findings, 'verified_claims': verified, 'claims': claims,
            'production_evidence': production, 'test_only_evidence': test_only,
            'errors': errors}
