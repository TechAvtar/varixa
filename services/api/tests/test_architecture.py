"""Guards the layering rules from docs/02-ARCHITECTURE.md.

Routes -> Services -> Repositories / Providers. Violations fail here before review.
"""

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# package -> packages it must never import from
FORBIDDEN_IMPORTS: dict[str, set[str]] = {
    "api": {"providers", "repositories"},
    "services": {"api"},
    "repositories": {"api", "services", "providers"},
    "providers": {"api", "services", "repositories", "models"},
    "schemas": {"api", "services", "repositories", "providers", "models"},
    "utils": {"api", "services", "repositories", "providers", "models", "schemas"},
}


def _imported_app_packages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    packages: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
            packages.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("app."):
                    packages.add(alias.name.split(".")[1])
    return packages


def test_layer_boundaries_are_respected() -> None:
    violations: list[str] = []
    for layer, forbidden in FORBIDDEN_IMPORTS.items():
        for file in (APP_ROOT / layer).rglob("*.py"):
            bad = _imported_app_packages(file) & forbidden
            if bad:
                rel = file.relative_to(APP_ROOT.parent)
                violations.append(f"{rel} imports {sorted(bad)}")
    assert not violations, "Layering violations:\n" + "\n".join(violations)


def test_every_app_package_documents_its_responsibility() -> None:
    undocumented = [
        str(init.relative_to(APP_ROOT.parent))
        for init in APP_ROOT.rglob("__init__.py")
        if not ast.get_docstring(ast.parse(init.read_text(encoding="utf-8")))
    ]
    assert not undocumented, "Packages without a responsibility docstring:\n" + "\n".join(
        undocumented
    )
