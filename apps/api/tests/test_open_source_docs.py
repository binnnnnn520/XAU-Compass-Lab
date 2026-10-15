from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


REPO_ROOT = Path(__file__).resolve().parents[3]


def _documentation_paths() -> list[Path]:
    paths = list(REPO_ROOT.glob("*.md"))
    for directory in ("docs", "infra"):
        paths.extend((REPO_ROOT / directory).rglob("*.md"))
    paths.extend(
        REPO_ROOT / relative_path
        for relative_path in ("apps/api/README.md", "apps/web/README.md")
    )
    return sorted(set(paths))


def test_documentation_names_use_neutral_project_terms() -> None:
    prohibited_name = re.compile(
        r"(?:^|[_.-])(?:agents?|ai|llm|codex|claude)(?:$|[_.-])",
        re.IGNORECASE,
    )

    for document in _documentation_paths():
        assert not prohibited_name.search(document.stem), document.relative_to(REPO_ROOT)


def test_documentation_describes_current_project_without_private_plan_history() -> None:
    private_history = re.compile(
        r"(?<![/\w-])phase\s*[1-5](?:\.\d+)?(?![/\w-])"
        r"|\b(?:predecessor|paused|unaccepted|paid[- ]product|production upgrade)\b"
        r"|\bformal (?:14[- ]day|evidence|acceptance)\b"
        r"|原仓库|原生产|收费产品|上线验收|暂停|未验收|14天灰度",
        re.IGNORECASE,
    )

    for document in _documentation_paths():
        content = document.read_text(encoding="utf-8")
        match = private_history.search(content)
        assert match is None, f"{document.relative_to(REPO_ROOT)}: {match.group()}"


def test_documentation_relative_links_resolve_inside_repository() -> None:
    for document in _documentation_paths():
        content = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            parsed_target = urlsplit(target)
            if parsed_target.scheme or not parsed_target.path:
                continue
            destination = (document.parent / unquote(parsed_target.path)).resolve()
            assert destination.is_relative_to(REPO_ROOT)
            assert destination.exists(), f"{document.relative_to(REPO_ROOT)} -> {target}"


def test_readmes_link_to_capabilities_testing_and_each_other() -> None:
    for name, translation in (("README.md", "README.en.md"), ("README.en.md", "README.md")):
        content = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert f"({translation})" in content
        assert "(docs/capabilities.md)" in content
        assert "(docs/testing.md)" in content
