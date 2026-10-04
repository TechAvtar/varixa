"""Fetch the open-source AI-detector models once (setup tool, never run by the service).

    python scripts/fetch_detector_models.py            # image + text models into the model dir
    python scripts/fetch_detector_models.py --only text
    python scripts/fetch_detector_models.py --dir /opt/models

The API loads models offline from ``VERIXA_AI_DETECTOR_MODEL_DIR`` (default ``<data dir>/models``)
and never downloads anything itself. Each model is pinned to a commit so the version shown in
reports is reproducible; a ``verixa-model.json`` next to the weights records the revision, the
source and a SHA-256 of the weights file. The download goes through the outbound policy with
the host passed explicitly (``huggingface.co``; its CDN redirects are handled by the client).

Requires the ``ml`` extra: ``pip install -e ".[ml]"``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.providers.ai.local import META_FILE, model_slug
from app.utils.urlpolicy import assert_outbound_allowed

ALLOWED_HOSTS = ["huggingface.co"]
HUB = "https://huggingface.co"

# repo id -> (pinned commit, files to fetch). Only root-level weights/config: the repos also
# hold training checkpoints (optimizers etc.) that are many times larger and never used.
MODELS: dict[str, tuple[str, list[str]]] = {
    "haywoodsloan/ai-image-detector-deploy": (
        "4ae1822603cb1ec980c217cfde1ef1b8e0477a16",
        ["config.json", "model.safetensors", "preprocessor_config.json"],
    ),
    "openai-community/roberta-base-openai-detector": (
        "6cba99c003b711c7fe94f8a3aa2be35a792cb6fa",
        [
            "config.json",
            "model.safetensors",
            "merges.txt",
            "vocab.json",
            "tokenizer.json",
            "tokenizer_config.json",
        ],
    ),
}
ROLE = {
    "image": "haywoodsloan/ai-image-detector-deploy",
    "text": "openai-community/roberta-base-openai-detector",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(repo_id: str, target_root: Path) -> Path:
    from huggingface_hub import hf_hub_download  # imported late: needs the ml extra

    assert_outbound_allowed(f"{HUB}/{repo_id}", allowed_hosts=ALLOWED_HOSTS)
    revision, files = MODELS[repo_id]
    target = target_root / model_slug(repo_id)
    target.mkdir(parents=True, exist_ok=True)
    for name in files:
        hf_hub_download(repo_id=repo_id, filename=name, revision=revision, local_dir=target)
    weights = target / "model.safetensors"
    meta = {
        "repo_id": repo_id,
        "revision": revision,
        "source": f"{HUB}/{repo_id}/tree/{revision}",
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "weights_sha256": sha256_file(weights),
    }
    (target / META_FILE).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=sorted(ROLE), help="fetch just one modality")
    parser.add_argument("--dir", type=Path, help="model directory (default: from settings)")
    args = parser.parse_args()
    root = args.dir or Settings().detector_model_dir
    roles = [args.only] if args.only else sorted(ROLE)
    for role in roles:
        repo_id = ROLE[role]
        print(f"fetching {role} model {repo_id} ...", flush=True)
        target = fetch(repo_id, root)
        print(f"  -> {target}")
    print("done. Set VERIXA_AI_DETECTOR_PROVIDER=local and restart the API.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
