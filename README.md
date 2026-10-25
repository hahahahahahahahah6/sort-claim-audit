# sort-claim-audit

Offline audit of documented sort-order claims against Python source.

A standard-library-only CLI for checking documentation contracts with static
AST evidence. It runs no project code, makes no network requests, and never
opens `.env` contents. Symlinked files and directories are skipped.

## Usage

```sh
python3 -m pip install .
sort-claim-audit path/to/project
python3 -m sort_claim_audit path/to/project --json
sort-claim-audit path/to/project --ignore 'vendor/*' --ignore 'generated.py'
sort-claim-audit path/to/project --fail-on HIGH --verbose
sort-claim-audit --version
```

The path defaults to the current directory. `--json` emits a single JSON object
with `findings`, `verified_claims`, claims, production and test-only evidence,
scan errors, and threshold-based status. Findings include rule, severity,
claims with document locations, and evidence with source locations.
`--verbose` adds the full report to text output. Repeatable `--ignore` globs
match relative POSIX paths; matching directories are pruned. Default failure
threshold is MEDIUM; HIGH leaves MEDIUM findings visible while exiting 0.
Exit codes: 0 PASS, 2 FAIL, 1 usage or invalid-root error.

## Claims

Only root README.md and docs/**/*.md supply claims. Fenced code is excluded;
inline code counts as prose. Matching is case-insensitive with word boundaries,
using exactly these phrases (no optional words or extra hyphen variants):

```text
SORTED:
sorted output
outputs are sorted
results are sorted
sorted results
sorts results
sorts output
sorted by
in sorted order
sorted alphabetically
sorted numerically
in ascending order
in descending order

UNSORTED:
unsorted
not sorted
in insertion order
preserves input order
preserves insertion order
in original order
keeps input order
```

Negation is asymmetric: a sentence containing no, not, never, without,
doesn't, don't, or isn't suppresses the SORTED family. The insertion-preserving phrases still
count in that sentence because those phrases can themselves express negation.
Bare `sorted` or `sort` nouns are not claims; naming a flag or a sort key does
not establish a contract. Each family collapses to one audit decision, with
all its matching claims retained. Contradictory families are checked independently.

## Rules

```text
| Rule | Severity | Trigger |
| --- | --- | --- |
| documented-sorted-claim-false | HIGH | SORTED family, no production sorting and no test sorting |
| documented-sorted-claim-false-test-only | MEDIUM | SORTED family, sorting confined to tests/fixtures |
| documented-unsorted-claim-false | HIGH | UNSORTED family and production sorting |
| documented-unsorted-claim-false-test-only | MEDIUM | UNSORTED family, sorting confined to tests/fixtures |

```

With no production Python source, either family produces its own HIGH finding
with `no-source` evidence. Otherwise SORTED with production sorting is verified;
The insertion-preserving family with no sorting anywhere is verified. No claims means PASS regardless
of source evidence. All relevant evidence appears in a finding; evidence is
deduplicated by file, line, and kind.

## Evidence table

| AST call | Evidence kind |
| --- | --- |
| Bare builtin-shaped `sorted(items)`, including key/reverse arguments | sorted |
| Attribute call `items.sort()`, on receivers, including key arguments; excludes numpy module calls | sort |

Production excludes tests/ and fixtures/ directories, test_*.py and *_test.py
files, docs/ and examples/ directories, and symlinks. Test/fixture evidence is
collected separately; docs and examples never supply evidence. Build outputs,
virtual environments and .git are skipped. Read/parse failures are reported in
`errors`; an unreadable or syntactically invalid source cannot supply evidence.

## Differentiation

- determinism-claim-audit checks run-to-run stability, never ordering.
- schema-claim-audit checks field names, never record order.
- streaming-claim-audit checks how much is read at once, never output order.
- config-claim-audit checks documented default values, never ordering.
- bandit/ruff check code issues, never documentation promises.
- The `sort` command and `sorted` documentation provide sorting primitives,
  never documentation-versus-code truth.

## Honest limitations

Exact phrases only: paraphrases and output-specific context are not inferred.
This is a whole-tree presence check, not data-flow analysis. Dead code counts.
Sorting whose result is discarded still counts: the tool checks that sorting
happens, not that its result reaches an output. Shadowed builtin names and
unrelated receiver methods can count because the AST table is syntactic.

`reversed()` alone is reversal, not sorting. Variables, parameters, and
attributes merely named `sort` or `sorted` do not count. Neither `key=` nor
`itemgetter` alone counts. `sort=True` passed to another API does not count.
`heapq.nsmallest`, `heapq.nlargest`, and `bisect` are outside the evidence table:
heap order is not a full-output ordering guarantee. Third-party numpy/pandas
sorting semantics (such as `np.sort` and `DataFrame.sort_values`) are out of
scope. Conventional `np`/`numpy` module names and explicit numpy import aliases
are excluded. Other methods spelled `.sort()` match the generic syntactic rule;
receiver types and third-party object aliases are not inferred.

Markdown handling covers backtick and tilde fences and ordinary punctuation
sentence boundaries, not a full Markdown parser. Files are decoded as UTF-8.
The scanner follows no symlinks and reads only documentation and Python source
within the supplied tree. It never imports audited modules.

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
python3 -m venv /tmp/sort-claim-audit-check
/tmp/sort-claim-audit-check/bin/python3 -m pip install dist/*.whl
/tmp/sort-claim-audit-check/bin/sort-claim-audit tests/fixtures/good/sorted --json
PYTHONPATH=src python3 -m sort_claim_audit . --json
```

The build produces wheel and sdist. MANIFEST.in includes the test fixtures in
the sdist. If an isolated build fails offline, use
`python3 -m build --no-isolation`. Runtime dependencies: none. Python 3.9+.
Licensed under MIT.
