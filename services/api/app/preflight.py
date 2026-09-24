"""Deployment preflight: refuse to start a misconfigured production instance.

python -m app.preflight    # exit 0 when the configuration is deployable, 1 with the reasons

Runs before migrations in the container images (see infra/compose.yml). It only inspects
settings; connectivity is reported by ``GET /health`` once the API is up.
"""

import sys

from app.config import Settings, get_settings


def problems(settings: Settings | None = None) -> list[str]:
    return (settings or get_settings()).production_problems()


def main(argv: list[str] | None = None) -> int:
    del argv  # no options yet
    try:
        settings = get_settings()
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        print(f"configuration invalid: {exc}", file=sys.stderr)
        return 1
    found = problems(settings)
    if found:
        print("configuration is not deployable:", file=sys.stderr)
        for item in found:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"configuration ok ({settings.environment})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
