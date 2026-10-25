"""Command line entry point."""
import argparse
import json
import sys

from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(prog='sort-claim-audit', description='Offline audit of documented sort-order claims against Python source.')
    parser.add_argument('path', nargs='?', default='.', help='project tree (default: current directory)')
    parser.add_argument('--json', action='store_true', help='emit a JSON report')
    parser.add_argument('--verbose', action='store_true', help='include claims and evidence in text output')
    parser.add_argument('--ignore', action='append', default=[], metavar='GLOB', help='ignore relative paths (repeatable)')
    parser.add_argument('--fail-on', choices=['MEDIUM', 'HIGH'], default='MEDIUM', help='minimum failing severity (default: MEDIUM)')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        report = audit(args.path, args.ignore)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    failing = any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in report['findings'])
    report['status'] = 'FAIL' if failing else 'PASS'
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(report['status'])
        for finding in report['findings']:
            print(finding['severity'] + ' ' + finding['rule'])
            for claim in finding['claims']:
                print('  {path}:{line}: {phrase}'.format(**claim))
            for evidence in finding['evidence']:
                print('  ' + json.dumps(evidence))
        if args.verbose:
            print(json.dumps(report, indent=2))
        for error in report['errors']:
            print('Warning: {path}: {error}'.format(**error), file=sys.stderr)
    return 2 if failing else 0


if __name__ == '__main__':
    sys.exit(main())
