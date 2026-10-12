# app/ordernew.py
"""`order new`: make an order folder from the intake's job folder in Dropbox.

    ~/Dropbox/Apps/Plateworks Lab/Tecopa/TP-26-001 Smith/order.md       the intake wrote it
                                                         01_received/   the client's upload
        -> ~/Tecopa Orders/TP-26-001-smith/in/          a copy of each file
                                           order.toml   title, order_number, returning,
                                                        client, email

Spec: docs/superpowers/specs/2026-10-12-tecopa-client-intake-and-payment-design.md,
section 5.1. TECOPA_INTAKE_DIR moves the Dropbox folder, TECOPA_ORDERS_DIR the orders.

The files come from a stranger, so this module:
- reads Dropbox and never writes, moves or deletes there;
- cleans every file name, and refuses a name that would leave in/;
- refuses a file over MAX_FILE_BYTES, and copies only plain files (never a link);
- opens no file to read what is in it: it copies bytes, and the engine's own readers
  open the tracks later, as they do for any order;
- stops when a file is not on the disk (Dropbox lists it but has not downloaded it),
  and never leaves a short copy;
- reads order.md as text and trusts none of its values: a title or a name is cleaned
  before it becomes a folder name or a line of order.toml, and order.toml is written
  with escaped strings and parsed back before it is kept.

A second run copies the files that arrived since, replaces no file in in/, and leaves
order.toml as it is."""
from __future__ import annotations

import os
import re
import stat
import tomllib
import unicodedata
from datetime import date

from app import order as od
from app.order import OrderError

INTAKE_ENV = "TECOPA_INTAKE_DIR"
RECEIVED = "01_received"
MAX_FILE_BYTES = 200_000_000          # 200 MB: a track is kilobytes, a photo megabytes
MAX_ORDER_MD_BYTES = 64 * 1024
NAME_MAX_CHARS = 120                  # a file name in in/, with its extension
SLUG_MAX_CHARS = 40                   # the client's part of the order folder's name
SF_DATALESS = 0x40000000              # macOS st_flags: the file's data is in the cloud
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp", ".gif",
              ".dng")
FRONT_MATTER_KEYS = ("order_id", "created", "client", "email", "title", "returning",
                     "upload_link", "tally_submission")
_CHUNK = 1 << 20


def intake_root() -> str:
    return os.environ.get(INTAKE_ENV) or os.path.join(
        os.path.expanduser("~"), "Dropbox", "Apps", "Plateworks Lab", "Tecopa")


# ---- names ----

def clean_name(raw: str) -> str:
    """A file name that is safe in in/: letters, digits, spaces and . _ - ( ). Any other
    character (a separator, a control or escape code, a right-to-left override) is "_".
    Leading and trailing dots and spaces go, so the name is never hidden, "." or "..".
    "" when nothing is left."""
    name = unicodedata.normalize("NFC", raw)
    name = "".join(c if (c.isalnum() or c in " ._-()") else "_" for c in name)
    name = " ".join(name.split()).strip(". ")
    if len(name) > NAME_MAX_CHARS:
        stem, ext = os.path.splitext(name)
        ext = ext if len(ext) <= 10 else ""
        name = stem[:NAME_MAX_CHARS - len(ext)].rstrip(". ") + ext
    return name


def target(folder: str, name: str):
    """The path of `name` in `folder`, or None when the name is empty, "." or "..", or
    the path would be anywhere but directly in `folder`."""
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
        return None
    path = os.path.join(folder, name)
    if os.path.dirname(os.path.normpath(path)) != os.path.normpath(folder):
        return None
    return path


def shown(raw: str) -> str:
    """A name as the report prints it: as it is when it is clean, else quoted with each
    control or invisible character escaped, so no file name can write to the terminal."""
    if raw.isprintable() and raw == clean_name(raw):
        return raw
    return repr(raw)


def _clean_text(value: str) -> str:
    """One line of text: control, format and separator characters become a space."""
    value = unicodedata.normalize("NFC", value)
    value = "".join(" " if unicodedata.category(c) in ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp")
                    else c for c in value)
    return " ".join(value.split())


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:SLUG_MAX_CHARS].rstrip("-")


def toml_string(value: str) -> str:
    """A TOML basic string: a quote, a backslash and every control character escaped."""
    out = []
    for c in value:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif ord(c) < 0x20 or ord(c) == 0x7F:
            out.append(f"\\u{ord(c):04x}")
        else:
            out.append(c)
    return '"' + "".join(out) + '"'


# ---- the disk ----

def over_limit(st) -> bool:
    return st.st_size > MAX_FILE_BYTES


def not_downloaded(st) -> bool:
    """True when Dropbox lists the file and its data is not on the disk: macOS marks it
    dataless, or it has a size and no block on the disk."""
    if getattr(st, "st_flags", 0) & SF_DATALESS:
        return True
    return st.st_size > 0 and getattr(st, "st_blocks", 1) == 0


def _not_here(name, what) -> OrderError:
    return OrderError(
        f"{name} is not on this Mac yet: {what}. In Finder, right-click the folder "
        f"{RECEIVED} of the job and choose Make available offline, wait for Dropbox to "
        f"finish, then run order new again.")


def _copy(src: str, dest: str, size: int, label: str) -> bool:
    """Copy src to dest byte for byte, never following a link and never replacing a file.
    False when dest exists. Raises OrderError, and leaves nothing behind, when fewer
    bytes than `size` could be read."""
    tmp = os.path.join(os.path.dirname(dest), f".order-new-{os.getpid()}.part")
    fd_in = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd_in).st_mode):
            raise OrderError(f"{label} stopped being a plain file while it was copied")
        fd_out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        count = 0
        try:
            while True:
                try:
                    data = os.read(fd_in, _CHUNK)
                except OSError as ex:
                    raise _not_here(label, f"reading it failed ({ex.strerror or ex})") from ex
                if not data:
                    break
                count += len(data)
                view = memoryview(data)
                while view:
                    view = view[os.write(fd_out, view):]
        finally:
            os.close(fd_out)
        if count != size:
            raise _not_here(label, f"{count:,} of {size:,} bytes could be read")
        try:
            os.link(tmp, dest)
        except FileExistsError:
            return False
        except OSError:                       # a disk with no hard links
            if os.path.lexists(dest):
                return False
            os.rename(tmp, dest)
        return True
    finally:
        os.close(fd_in)
        if os.path.lexists(tmp):
            os.remove(tmp)


# ---- order.md ----

def read_order_md(path: str) -> dict:
    """The front matter of order.md, between the first two lines that are "---": each
    `key: value` line, its value stripped of one pair of quotes. Values are text and
    nothing more: the caller cleans each one it uses."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise OrderError(f"no order.md in {os.path.dirname(path)}") from None
    if not stat.S_ISREG(st.st_mode):
        raise OrderError(f"order.md in {os.path.dirname(path)} is not a plain file")
    if st.st_size > MAX_ORDER_MD_BYTES:
        raise OrderError(f"order.md is larger than {MAX_ORDER_MD_BYTES // 1024} KB, and the "
                         f"intake writes a few KB: read it by hand")
    if not_downloaded(st):
        raise _not_here("order.md", "Dropbox lists it and has not downloaded it")
    with open(path, "rb") as f:
        raw = f.read(MAX_ORDER_MD_BYTES + 1)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise OrderError("order.md is not UTF-8 text") from None
    lines = [line.rstrip("\r") for line in text.split("\n")]
    if not lines or lines[0].strip() != "---" or "---" not in [x.strip() for x in lines[1:]]:
        raise OrderError("order.md has no front matter between two --- lines")
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or not key:
            continue
        if key in fields:
            raise OrderError(f"order.md has {_clean_text(key)[:40]} twice")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return fields


# ---- the folders ----

def _one(folder: str, number: str, sep: str, what: str):
    """The entry of `folder` that is `number`, or starts with number and `sep`. Dropbox
    and the Mac's disk ignore case, so the match does too."""
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return None
    found = sorted(n for n in names if n.upper() == number or n.upper().startswith(number + sep))
    if len(found) > 1:
        raise OrderError(f"two {what} for {number} in {folder}: "
                         f"{', '.join(shown(n) for n in found)}. Keep one.")
    return found[0] if found else None


def _real_dir(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def _inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def _kind(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in od.TRACK_EXTS:
        return "Tracks"
    if ext in PHOTO_EXTS:
        return "Photos"
    return "Not a type I know"


def _order_toml(number, fields, today) -> tuple:
    """(text, warnings, title, returning): the order.toml of a new order, from
    order.md's values."""
    warnings = []
    title = _clean_text(fields.get("title", ""))
    if not title:
        warnings.append("order.md has no title: write one in order.toml before the preview.")
    else:
        from app.spec import TITLE_MAX_CHARS
        if len(title) > TITLE_MAX_CHARS:
            warnings.append(f"the title has {len(title)} characters, and a map holds at most "
                            f"{TITLE_MAX_CHARS}: shorten it in order.toml before the preview.")
    returning = fields.get("returning", "").strip().lower()
    if returning not in ("yes", "no"):
        raise OrderError(f"order.md says returning: {fields.get('returning', '')[:40]!r}. It must "
                         f"be yes or no, and it decides the prices. Ask the client, then write "
                         f"the order folder by hand.")
    client = _clean_text(fields.get("client", ""))[:od.CLIENT_MAX_CHARS].strip()
    email = fields.get("email", "").strip()
    if email and not (len(email) <= 254 and od.EMAIL.fullmatch(email)):
        warnings.append("the email in order.md is not an address, and order.toml has none: "
                        "the preview email's To line will be empty.")
        email = ""
    lines = [f"# Written by `order new {number}` from order.md on {today}. order new never",
             "# changes this file again. When the client has paid, add the lines of the size",
             "# from the preview's report: size, orientation, and gap for a set.",
             f"title = {toml_string(title)}",
             f"order_number = {toml_string(number)}",
             f"returning = {'true' if returning == 'yes' else 'false'}"]
    if client:
        lines.append(f"client = {toml_string(client)}")
    if email:
        lines.append(f"email = {toml_string(email)}")
    text = "\n".join(lines) + "\n"
    # the file must say exactly this and nothing more
    expected = {"title": title, "order_number": number, "returning": returning == "yes"}
    expected.update({k: v for k, v in (("client", client), ("email", email)) if v})
    if tomllib.loads(text) != expected:
        raise OrderError("order.toml would not read back as written. Nothing was copied.")
    return text, warnings, title, returning == "yes"


def new(number: str, today=None) -> str:
    """Copy the job folder of `number` into its order folder, and return the report."""
    if not isinstance(number, str) or not od.ORDER_NUMBER.fullmatch(number):
        raise OrderError(f"the order number must be like TP-26-001, not {str(number)[:40]!r}")
    intake = intake_root()
    orders = od.orders_root()
    if _inside(orders, intake):
        raise OrderError(f"the orders folder {orders} must not be inside the Dropbox intake "
                         f"folder {intake}: order new never writes to Dropbox.")
    od.refuse_inside_repo(orders)
    job_name = _one(intake, number, " ", "job folders")
    if job_name is None:
        raise OrderError(f"no job folder for {number} in {intake}. Has Dropbox finished "
                         f"syncing? {INTAKE_ENV} names another folder.")
    job = os.path.join(intake, job_name)
    received = os.path.join(job, RECEIVED)
    if not _real_dir(job) or not _real_dir(received):
        raise OrderError(f"no {RECEIVED} folder in {job}")
    fields = read_order_md(os.path.join(job, "order.md"))
    said = fields.get("order_id", "")
    if said != number:
        raise OrderError(f"order.md is for order {said[:40]!r}, not {number}. Nothing was copied.")
    toml_text, warnings, title, returning = _order_toml(
        number, fields, (today or date.today()).isoformat())

    existing = _one(orders, number, "-", "order folders")
    dest = os.path.join(orders, existing or (
        f"{number}-{_slug(job_name[len(number):])}".rstrip("-")))
    in_dir = os.path.join(dest, "in")
    if os.path.lexists(in_dir) and not _real_dir(in_dir):
        raise OrderError(f"{in_dir} is not a folder")

    # look at every file before copying one: a file not on the disk stops the run here
    plan, hidden, already, refused = [], [], [], []
    for raw in sorted(os.listdir(received)):
        if raw.startswith("."):
            hidden.append(shown(raw))
            continue
        src = os.path.join(received, raw)
        st = os.lstat(src)
        if not stat.S_ISREG(st.st_mode):
            refused.append(f"{shown(raw)}: not a plain file (a link or a folder), so it is not copied")
            continue
        name = clean_name(raw)
        path = target(in_dir, name)
        if path is None:
            refused.append(f"{shown(raw)}: nothing is left of the name once it is cleaned"
                           if not name else f"{shown(raw)}: the name leaves the order folder")
            continue
        if os.path.lexists(path):
            if os.lstat(path).st_size == st.st_size:
                already.append(name)
            else:
                refused.append(f"{shown(raw)}: a different file of that name is in in/ already, "
                               f"and order new never replaces a file")
            continue
        if over_limit(st):
            refused.append(f"{shown(raw)}: {st.st_size / 1e6:,.0f} MB, over the "
                           f"{MAX_FILE_BYTES / 1e6:,.0f} MB limit")
            continue
        if not_downloaded(st):
            raise OrderError(str(_not_here(shown(raw), f"Dropbox lists {st.st_size:,} bytes and "
                                                        f"has not downloaded them"))
                             + " Nothing was copied.")
        if any(p[1] == path for p in plan):
            refused.append(f"{shown(raw)}: another file has the same name once both are cleaned")
            continue
        plan.append((src, path, st.st_size, raw, name))

    os.makedirs(in_dir, exist_ok=True)
    copied = []
    for src, path, size, raw, name in plan:
        try:
            done = _copy(src, path, size, shown(raw))
        except OrderError as ex:
            raise OrderError(f"{ex} The files copied before it stay in in/.") from None
        if done:
            copied.append((name, raw))
        else:
            refused.append(f"{shown(raw)}: a file of that name arrived in in/ during the copy")

    toml_path = os.path.join(dest, "order.toml")
    try:
        fd = os.open(toml_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        toml_said = "order.toml: there already, left as it is."
        notes = []
    else:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(toml_text)
        notes = warnings          # what order.md said matters only to a new order.toml
        toml_said = ("order.toml: written, " + ("a next-year order." if returning
                                                else "a first poster."))

    lines = [f'Order: {number}, "{title}"', f"From: {received}", f"To: {dest}"]
    if copied:
        lines.append(f"Copied {len(copied)} file{'s' if len(copied) != 1 else ''}:")
        for kind in ("Tracks", "Photos", "Not a type I know"):
            these = sorted((n, r) for n, r in copied if _kind(n) == kind)
            if these:
                lines.append(f"- {kind} ({len(these)}): " + ", ".join(
                    n if n == r else f"{n} (was {shown(r)})" for n, r in these))
    else:
        lines.append("Copied 0 files.")
    if already:
        lines.append(f"Already in in/ ({len(already)}): {', '.join(sorted(already))}")
    if hidden:
        lines.append(f"Hidden, skipped ({len(hidden)}): {', '.join(hidden)}")
    if refused:
        lines.append(f"Not copied ({len(refused)}):")
        lines += [f"- {r}" for r in refused]
    if not od.Order(dest, "", "", (0, 0), "", "").track_files():
        notes.append("in/ holds no track file yet: the preview needs one.")
    lines += [f"Warning: {w}" for w in notes]
    lines += [toml_said, f'Next: tecopa order preview "{dest}"']
    return "\n".join(lines) + "\n"
