#!/usr/bin/env python3
"""Bora 제품 버전, Debian 표기 및 릴리스 입력 검증."""
import argparse
from pathlib import Path
import re
import subprocess

NUMBER = r'(?:0|[1-9][0-9]*)'
CORE = rf'{NUMBER}\.{NUMBER}\.{NUMBER}'
VERSION_RE = re.compile(rf'{CORE}(?:-(?:dev|alpha|beta|rc)\.{NUMBER})?')


def validate(raw):
    value = raw.removesuffix('\n')
    if not VERSION_RE.fullmatch(value):
        raise ValueError('version은 X.Y.Z 또는 X.Y.Z-dev.N/alpha.N/beta.N/rc.N 한 줄이어야 합니다.')
    return value


def debian(value):
    return value.replace('-', '~', 1)


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def development(value):
    # 정식 버전의 로컬 빌드도 정식 릴리스로 가장하지 않는다.
    base = value if '-' in value else value + '-dev.0'
    suffix = '.dirty' if git('status', '--porcelain', '--untracked-files=normal') else ''
    return base + '+git.' + git('rev-parse', '--short=12', 'HEAD') + suffix


def check_release(value, tag):
    if '-dev.' in value:
        raise ValueError('개발 버전은 릴리스 태그를 만들 수 없습니다.')
    if tag != 'v' + value:
        raise ValueError('태그는 version 앞에 v를 붙인 값이어야 합니다.')
    if git('rev-parse', tag + '^{commit}') != git('rev-parse', 'HEAD'):
        raise ValueError('릴리스 태그가 현재 커밋을 가리키지 않습니다.')
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('릴리스는 깨끗한 작업 트리에서만 빌드합니다.')
    if f'## [{value}]' not in Path('CHANGELOG.md').read_text():
        raise ValueError('CHANGELOG에 확정된 버전 항목이 없습니다.')
    notes = Path('docs/releases') / (value + '.md')
    text = notes.read_text()
    for marker in ('GUI-E2E: passed', 'Unit-tests: passed'):
        if marker not in text.splitlines():
            raise ValueError('릴리스 검증 기록 누락: ' + marker)
    if not any(line.startswith('Platform: ') and line[10:].strip() for line in text.splitlines()):
        raise ValueError('검증 플랫폼 기록이 없습니다.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--value', help='staged blob 또는 표기 변환용 값')
    parser.add_argument('--debian', action='store_true')
    parser.add_argument('--development', action='store_true')
    parser.add_argument('--release-tag')
    args = parser.parse_args()
    try:
        value = validate(args.value if args.value is not None else Path('version').read_text())
        if args.release_tag:
            check_release(value, args.release_tag)
        if args.development:
            value = development(value)
        print(debian(value) if args.debian else value)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'버전 검사 실패: {exc}\n')


if __name__ == '__main__':
    main()
