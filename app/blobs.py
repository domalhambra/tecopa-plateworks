# app/blobs.py
"""Object storage for render outputs behind a tiny interface.

Final renders are large PNGs; v1 wrote them next to the region. LocalBlobs keeps
that (filesystem), but routing outputs through a put/path/exists interface means a
networked object store (S3/GCS) drops in later without touching the render or job
code -- the worker just gets a different Blobs implementation."""
from __future__ import annotations
import os

class LocalBlobs:
    def __init__(self, root: str = "blobs"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _p(self, key: str) -> str:
        # keys may be nested ("sessionid/final.png"); keep them under root
        path = os.path.normpath(os.path.join(self.root, key))
        if not path.startswith(os.path.normpath(self.root)):
            raise ValueError("blob key escapes store root")
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._p(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def path(self, key: str) -> str:
        return self._p(key)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._p(key))
