import hashlib
import json
import copy
from pathlib import Path


METADATA_ROOT = ".packwright"
SPEC_PATH = f"{METADATA_ROOT}/spec.json"
LOCK_PATH = f"{METADATA_ROOT}/lock.json"
RECEIPT_PATH = f"{METADATA_ROOT}/checker-receipt.json"
METADATA_ARTIFACTS = (SPEC_PATH, LOCK_PATH, RECEIPT_PATH)


def embed_pack_metadata(pack, resolved, checker_receipt):
    """Return a pack with a portable canonical snapshot and build receipts."""
    enriched = dict(pack)
    manifest = json.loads(enriched["manifest.json"])
    manifest["source_mechanism"] = SPEC_PATH
    manifest["packwright"] = {
        "schema": "packwright-pack-metadata/v1",
        "spec": SPEC_PATH,
        "lock": LOCK_PATH,
        "checker_receipt": RECEIPT_PATH,
    }
    snapshot, source_files = _portable_snapshot(resolved)
    artifacts = set(manifest.get("artifacts", []))
    artifacts.update(METADATA_ARTIFACTS)
    artifacts.update(source_files)
    manifest["artifacts"] = sorted(artifacts)
    enriched.update(source_files)
    enriched[SPEC_PATH] = _json_text(snapshot)
    enriched[RECEIPT_PATH] = _json_text(checker_receipt)
    manifest_text = _json_text(manifest)
    enriched["manifest.json"] = manifest_text
    locked = {
        path: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for path, content in sorted(enriched.items())
        if path != LOCK_PATH
    }
    enriched[LOCK_PATH] = _json_text({
        "schema": "packwright-lock/v1",
        "artifacts": locked,
    })
    return enriched


def load_embedded_spec(root):
    """Load the resolved snapshot with target-root-relative validation context."""
    root = Path(root)
    path = root / SPEC_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source"] = {"path": str(path), "base_dir": str(root / METADATA_ROOT / "source")}
    return data


def _json_text(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _portable_snapshot(resolved):
    snapshot = copy.deepcopy(resolved)
    base = Path(resolved.get("source", {}).get("base_dir", "."))
    files = {}

    def visit(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key == "source":
                    continue
                if key == "path" or key.endswith("_path"):
                    if isinstance(item, str) and not Path(item).is_absolute():
                        candidate = base / item
                        if candidate.is_file():
                            # Keep spec paths stable because adapters also use them
                            # as destination names, while storing their source bytes
                            # under a private metadata root.
                            files[f"{METADATA_ROOT}/source/{item}"] = candidate.read_text(encoding="utf-8")
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(snapshot)
    snapshot["source"] = {"path": SPEC_PATH, "base_dir": "."}
    return snapshot, files
