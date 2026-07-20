# app/plates.py
"""Install and verify terrain plates (the .trailplate.zip packs scripts/pack_region.py
emits) -- `python -m app.plates install <path-or-url>` is the v1 distribution door.

A plate is UNTRUSTED input: it may arrive over the network, and a zip can lie in two
ways -- about its PATHS (zip-slip: '../', absolute names, a member that isn't a plate
asset at all) and about its BYTES (a tampered DEM under a healthy-looking sidecar). So
install validates the namelist BEFORE a single byte is extracted, extracts into a temp
dir under the target root (same filesystem, so the final placement is an atomic
rename), then re-hashes EVERY asset against the zip's own sources.json and refuses on
any mismatch -- the same hashes the poster manifest's region_pack block verifies
against later, so an installed plate is checkably the one the poster was painted on.

Stdlib-only by design (docs/scope invariant: the installer must run on a machine that
never installed the render stack). verify_poster is the exception -- it reads a PNG
manifest, which needs Pillow -- so it imports app.provenance lazily; `install` never
touches it."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile

# The full plate surface: everything region_prep.py / build_labels.py ever emit, plus
# the pack's own sources.json and PLATE.txt. A member outside this set is refused --
# an installer that writes attacker-named files is a shell-away from being a dropper.
ALLOWED_MEMBERS = frozenset({"region.json", "dem.tif", "hydro.json", "labels.json",
                             "landcover.tif", "overview.png", "sources.json",
                             "PLATE.txt"})
_ID_RE = re.compile(r"[a-z0-9_]+\Z")          # region ids as region_prep mints them
# the self-name pack_region mints: <id>-<first 12 hex of the zip's own sha256>.
# A source whose basename carries this shape has COMMITTED to its bytes.
_SELF_NAME_RE = re.compile(r"-([0-9a-f]{12})\.trailplate\.zip\Z")
MAX_PLATE_BYTES = 2 << 30                     # 2 GiB: GitHub's release-asset ceiling
URL_TIMEOUT_S = 60


class PlateError(RuntimeError):
    """A plate that can't be installed safely. The message names the member/asset and
    the fix; the __main__ shim maps it to exit 1."""


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(src: str, tmp_dir: str) -> str:
    """A local zip path for `src`. A URL downloads (stdlib, sane timeout) into the
    temp dir with a running byte cap -- Content-Length is attacker-controlled, so the
    cap counts what actually arrives."""
    if not src.startswith(("http://", "https://")):
        if not os.path.exists(src):
            raise PlateError(f"{src} does not exist — pass a .trailplate.zip path or URL")
        if os.path.getsize(src) > MAX_PLATE_BYTES:
            raise PlateError(f"{src} exceeds the 2 GiB plate cap — not a plate")
        return src
    dst = os.path.join(tmp_dir, "plate.zip")
    total = 0
    with urllib.request.urlopen(src, timeout=URL_TIMEOUT_S) as r, open(dst, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            total += len(chunk)
            if total > MAX_PLATE_BYTES:
                raise PlateError(f"{src} exceeds the 2 GiB plate cap — refusing to "
                                 f"download further")
            f.write(chunk)
    return dst


def _validate_namelist(names: list[str]) -> str:
    """The plate id, after proving every member is exactly <id>/<allowlisted-name>:
    one top-level directory, no absolute paths, no '..', no backslashes, no directory
    entries, no duplicates. This runs BEFORE extraction, so a crafted name never
    reaches the filesystem at all (zip-slip has nothing to slip into)."""
    if not names:
        raise PlateError("the zip is empty — not a plate")
    seen, tops = set(), set()
    for n in names:
        parts = n.split("/")
        if ("\\" in n or n.startswith("/") or n.endswith("/") or len(parts) != 2
                or not all(parts) or ".." in parts):
            raise PlateError(f"zip member {n!r} is not a plain <id>/<file> path — "
                             f"refusing to install")
        if parts[1] not in ALLOWED_MEMBERS:
            raise PlateError(f"zip member {parts[1]!r} is not a plate asset — "
                             f"refusing to install")
        if n in seen:
            raise PlateError(f"zip member {n!r} appears twice — refusing to install")
        seen.add(n)
        tops.add(parts[0])
    if len(tops) != 1:
        raise PlateError("the zip holds more than one region directory — a plate "
                         "carries exactly one")
    rid = tops.pop()
    if not _ID_RE.fullmatch(rid):
        raise PlateError(f"plate directory {rid!r} is not a valid region id "
                         f"([a-z0-9_]+) — refusing to install")
    if f"{rid}/sources.json" not in seen:
        raise PlateError("the plate carries no sources.json — nothing to verify the "
                         "assets against, refusing to install")
    return rid


def _extract(zf: zipfile.ZipFile, names: list[str], dst_dir: str) -> None:
    """Stream every (already-validated) member out, counting REAL bytes -- a zip
    header's declared file_size is as untrusted as its name, so the bomb cap counts
    what actually inflates."""
    total = 0
    for n in names:
        out = os.path.join(dst_dir, n)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with zf.open(n) as src, open(out, "wb") as f:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                total += len(chunk)
                if total > MAX_PLATE_BYTES:
                    raise PlateError("the plate inflates past the 2 GiB cap — "
                                     "refusing to install")
                f.write(chunk)


def install_plate(src: str, root: str = "regions", replace: bool = False) -> str:
    """Install a .trailplate.zip (path or URL) under `root`, returning the region id.
    Every asset is re-hashed against the plate's own sources.json before anything
    reaches root/<id>; the final placement is an atomic rename, so a failed install
    never leaves a half-region the registry could discover."""
    os.makedirs(root, exist_ok=True)
    # temp dir INSIDE the target root: same filesystem, so os.replace is atomic; the
    # leading dot keeps regions.discover() from ever seeing a half-extracted plate.
    tmp = tempfile.mkdtemp(prefix=".plate-", dir=root)
    try:
        zip_path = _fetch(src, tmp)
        # OUTER identity first: a plate named <id>-<hash12>.trailplate.zip commits to
        # its own zip sha256 (pack_region self-names it; plates/index.json records the
        # full digest), and that name rides the requested URL/path -- so an in-transit
        # substitution, however internally consistent its OWN sources.json, is refused
        # here instead of surfacing later as a confusing per-poster reprint mismatch.
        base = os.path.basename(
            urllib.parse.urlsplit(src).path
            if src.startswith(("http://", "https://")) else src)
        m = _SELF_NAME_RE.search(base)
        if m:
            zip_sha = _sha256_file(zip_path)
            if not zip_sha.startswith(m.group(1)):
                raise PlateError(f"{base} names zip sha256 prefix {m.group(1)} but "
                                 f"these bytes hash to {zip_sha[:12]}… — the download "
                                 f"was substituted or corrupted; re-fetch the plate "
                                 f"from its publisher")
        try:
            zf = zipfile.ZipFile(zip_path)
        except zipfile.BadZipFile:
            raise PlateError(f"{src} is not a zip file — expected a .trailplate.zip")
        with zf:
            names = zf.namelist()
            rid = _validate_namelist(names)
            _extract(zf, names, tmp)
        plate_dir = os.path.join(tmp, rid)
        with open(os.path.join(plate_dir, "sources.json")) as f:
            listed = json.load(f).get("assets", {})
        # both directions: every listed asset present AND byte-true, every extracted
        # file accounted for. One lie -> the whole plate is refused.
        extracted = {n for n in os.listdir(plate_dir)
                     if n not in ("sources.json", "PLATE.txt")}
        if extracted != set(listed):
            raise PlateError("the plate's files don't match its own sources.json — "
                             "plate is corrupt or was tampered with — refusing to install")
        checks = []
        for name in sorted(listed):
            disk = _sha256_file(os.path.join(plate_dir, name))
            if disk != listed[name].get("sha256"):
                raise PlateError(f"{name} does not match the sha256 the plate's "
                                 f"sources.json records — plate is corrupt or was "
                                 f"tampered with — refusing to install")
            checks.append(f"  {name}  sha256 {disk[:12]}… ok")
        target = os.path.join(root, rid)
        backup = None
        if os.path.exists(target):
            if not replace:
                raise PlateError(f"{target} already exists — pass --replace to swap "
                                 f"in this plate")
            # park the old plate INSIDE the dot-tmp dir: regions.discover() registers
            # any root/<name>/region.json, so a sibling like <rid>.replaced-<pid>
            # would surface as a phantom region on the next discover. Nested under
            # tmp it is invisible, restorable if the swap fails, and swept by the
            # finally only after the new plate is in place.
            backup = os.path.join(tmp, f"{rid}.replaced")
            os.replace(target, backup)
        try:
            os.replace(plate_dir, target)
        except BaseException:
            if backup is not None:                # the swap died: put the old
                os.replace(backup, target)        # region back, whole
            raise
        print(f"plate {rid} verified:")
        print("\n".join(checks))
        print(f"{rid} installed — /readyz will confirm bounds")
        return rid
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify_poster(png_path: str, root: str = "regions") -> int:
    """Check a poster PNG's region_pack block against the plate installed under
    `root`. Prints a per-asset verdict; returns the exit code (0 verified or
    honestly unverifiable, 1 mismatch / region missing). Pillow-needing imports stay
    inside this function so `install` remains stdlib-only."""
    from app import provenance
    with open(png_path, "rb") as f:
        manifest = provenance.extract(f.read())
    if manifest is None:
        print(f"{png_path} carries no Tecopa Printworks manifest — only PNG finals exported "
              f"with reprint data embedded can name their plate")
        return 1
    rp = manifest.get("region_pack")
    if not isinstance(rp, dict) or not rp.get("assets"):
        print("unverifiable (pre-pack poster)")   # soft: the file predates the block
        return 0
    spec_d = manifest.get("spec") or {}
    rid = spec_d.get("region_id") or manifest.get("region_id")
    # the manifest is UNTRUSTED and rid is about to become a filesystem path: gate it
    # on the minted-id charset (same door as install's namelist check and the
    # resurrection note) so a crafted "../"/absolute id can't steer reads -- and the
    # hash-prefix verdict lines -- outside --root.
    if not (isinstance(rid, str) and _ID_RE.fullmatch(rid)):
        print(f"manifest names region id {rid!r}, which is not a valid region id "
              f"([a-z0-9_]+) — the file's manifest is malformed; nothing to verify "
              f"against")
        return 1
    region_dir = os.path.join(root, rid)
    if not os.path.exists(os.path.join(region_dir, "region.json")):
        print(f"region {rid!r} not installed — install its plate "
              f"(python -m app.plates install <plate>) and verify again")
        return 1
    # hash with the FILE's labels/biome toggles, so both sides cover the same asset
    # set (a labels-off poster's identity never includes labels.json -- see
    # provenance.region_pack_block).
    server = provenance.region_pack_block(region_dir,
                                          labels=bool(spec_d.get("labels")),
                                          biome=bool(spec_d.get("biome")))
    if server is None:
        print(f"{region_dir} has no sources.json — a hand-built plate can't be "
              f"verified; reinstall from a .trailplate.zip")
        return 1
    file_assets, server_assets = dict(rp["assets"]), server["assets"]
    ok = True
    for name in sorted(set(file_assets) | set(server_assets)):
        fh, sh = file_assets.get(name), server_assets.get(name)
        if fh == sh:
            print(f"  {name}  sha256 {str(fh)[:12]}… ok")
        else:
            ok = False
            print(f"  {name}  poster {str(fh)[:12] if fh else 'absent'} != "
                  f"installed {str(sh)[:12] if sh else 'absent'}")
    if ok and rp.get("pack_version") == server["pack_version"]:
        print(f"verified — {rid} plate {server['pack_version']} is the one this "
              f"poster was painted on")
        return 0
    print(f"mismatch — this poster was painted on plate {rp.get('pack_version')}; "
          f"{root} has {server['pack_version']} — install the original plate to "
          f"reprint exactly")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.plates",
                                 description="Install and verify Tecopa Printworks terrain "
                                             "plates (.trailplate.zip)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_i = sub.add_parser("install", help="install a plate from a path or URL")
    p_i.add_argument("src")
    p_i.add_argument("--root", default="regions")
    p_i.add_argument("--replace", action="store_true")
    p_v = sub.add_parser("verify", help="check a poster PNG against the installed plate")
    p_v.add_argument("poster")
    p_v.add_argument("--root", default="regions")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "install":
            install_plate(a.src, root=a.root, replace=a.replace)
            return 0
        return verify_poster(a.poster, root=a.root)
    except PlateError as e:
        print(str(e), file=sys.stderr)
        return 1
    except OSError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
