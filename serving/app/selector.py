"""Atomically select an immutable, checksummed bundle from a local deployment pointer."""

import hashlib
import json
import threading
from pathlib import Path

from app.runtime import ModelRuntime


class BundleSelector:
    def __init__(self, pointer: Path, bundle_root: Path):
        self.pointer = pointer
        self.bundle_root = bundle_root.resolve()
        self.lock = threading.RLock()
        self.revision = None
        self.runtime = None

    def get(self):
        with self.lock:
            raw = self.pointer.read_bytes()
            revision = hashlib.sha256(raw).hexdigest()
            if revision != self.revision:
                selected = json.loads(raw)
                path = Path(selected['bundle_dir']).resolve()
                if not path.is_relative_to(self.bundle_root):
                    raise ValueError('Deployment bundle must stay within BUNDLE_ROOT')
                loaded = ModelRuntime(path)
                identity = loaded.manifest
                if (identity.model_name != selected['model_name']
                        or identity.model_version != str(selected['model_version'])
                        or identity.model_sha256 != selected['model_sha256']):
                    raise ValueError('Deployment identity/checksum does not match the bundle')
                # Publish only after all validation completes. Existing in-flight requests
                # retain the previous runtime and report its own model version.
                self.runtime = loaded
                self.revision = revision
            return self.runtime
