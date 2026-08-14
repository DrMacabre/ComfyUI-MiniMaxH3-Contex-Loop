#!/usr/bin/env python3
"""Keep browser-cached .mjs helpers aligned with the package release."""

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
VERSION_MATCH = re.search(r'^version\s*=\s*"([^"]+)"', PROJECT, re.MULTILINE)
assert VERSION_MATCH, "pyproject.toml does not declare the project version"
VERSION = VERSION_MATCH.group(1)
IMPORT = re.compile(
    r'''["'](\./[^"']+\.mjs)(?:\?v=([^"']+))?["']''')


def main():
    imports = []
    for path in sorted((ROOT / "web").iterdir()):
        if path.suffix not in (".js", ".mjs"):
            continue
        source = path.read_text(encoding="utf-8")
        for relative, cache_version in IMPORT.findall(source):
            target = (path.parent / relative).resolve()
            assert target.is_file(), "%s imports missing %s" % (
                path.name, relative)
            assert cache_version == VERSION, (
                "%s imports %s with cache token %r; expected package version %s"
                % (path.name, relative, cache_version, VERSION))
            imports.append((path.name, relative))

    assert imports, "No production .mjs imports were checked."
    print("H3 web cache bust: %d .mjs imports use v=%s" % (
        len(imports), VERSION))


if __name__ == "__main__":
    main()
