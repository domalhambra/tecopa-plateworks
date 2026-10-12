# tests/test_ordernew.py
"""`order new`: the job folder of the intake, copied into a new order folder
(client intake spec, 2026-10-12, section 5.1). The files come from a stranger."""
import os
import tomllib

import pytest

from app import order as od
from app import ordernew as onew

GPX = b'<?xml version="1.0"?><gpx version="1.1"><trk><trkseg></trkseg></trk></gpx>'

ORDER_MD = """---
order_id: TP-26-001
created: 2026-10-12
client: Sam Smith
email: sam@example.com
title: Smith home ground
returning: no
upload_link: https://www.dropbox.com/request/abc
tally_submission: wXyZ12
---

## Notes from the client

Sheds, mostly.
"""


@pytest.fixture
def places(tmp_path, monkeypatch):
    """The Dropbox intake folder and the orders root, both in tmp_path."""
    intake, orders = tmp_path / "Dropbox" / "Tecopa", tmp_path / "orders"
    intake.mkdir(parents=True)
    monkeypatch.setenv("TECOPA_INTAKE_DIR", str(intake))
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(orders))
    return intake, orders


def _job(intake, name="TP-26-001 Smith", md=ORDER_MD, files=None):
    job = intake / name
    (job / "01_received").mkdir(parents=True)
    if md is not None:
        (job / "order.md").write_text(md) if isinstance(md, str) else (job / "order.md").write_bytes(md)
    files = {"trip.gpx": GPX, "day 2.KML": b"<kml/>", "shed.JPG": b"\xff\xd8jpeg",
             "notes.docx": b"PK"} if files is None else files
    for fname, data in files.items():
        (job / "01_received" / fname).write_bytes(data)
    return job


def _tree(root):
    """Every path under root with its size and mtime: the test that nothing changed."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames + filenames:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime_ns)
    return out


def test_the_job_folder_becomes_an_order_folder(places):
    intake, orders = places
    _job(intake)
    (intake / "TP-26-002 Jones").mkdir()                     # another order, left alone
    before = _tree(intake)
    report = onew.new("TP-26-001")
    dest = orders / "TP-26-001-smith"
    assert sorted(os.listdir(dest / "in")) == ["day 2.KML", "notes.docx", "shed.JPG", "trip.gpx"]
    assert (dest / "in" / "trip.gpx").read_bytes() == GPX
    o = od.load(dest)
    assert (o.title, o.order_number, o.returning, o.client, o.email) == (
        "Smith home ground", "TP-26-001", False, "Sam Smith", "sam@example.com")
    assert o.size == (11.0, 17.0) and o.sizes == ()           # order new writes no size
    toml = tomllib.loads((dest / "order.toml").read_text())
    assert set(toml) == {"title", "order_number", "returning", "client", "email"}
    # it reports what it copied, by kind
    assert "Tracks (2): day 2.KML, trip.gpx" in report
    assert "Photos (1): shed.JPG" in report
    assert "Not a type I know (1): notes.docx" in report
    assert "order.toml: written, a first poster." in report
    assert f'tecopa order preview "{dest}"' in report
    # and it never writes to Dropbox: no file moved, added or touched
    assert _tree(intake) == before


def test_a_returning_client_is_a_next_year_order(places):
    intake, orders = places
    _job(intake, md=ORDER_MD.replace("returning: no", "returning: yes"))
    report = onew.new("TP-26-001")
    assert od.load(orders / "TP-26-001-smith").returning is True
    assert "order.toml: written, a next-year order." in report


def test_a_second_run_adds_the_new_files_and_replaces_nothing(places):
    intake, orders = places
    job = _job(intake)
    onew.new("TP-26-001")
    dest = orders / "TP-26-001-smith"
    toml = dest / "order.toml"
    toml.write_text(toml.read_text() + 'size = "two"\norientation = "landscape"\n')   # Dom's choice
    by_dom = toml.read_text()
    (job / "01_received" / "late.gpx").write_bytes(GPX)
    (job / "01_received" / "trip.gpx").write_bytes(GPX + b"<!-- changed -->")
    report = onew.new("TP-26-001")
    assert toml.read_text() == by_dom                          # order.toml is left alone
    assert (dest / "in" / "late.gpx").read_bytes() == GPX
    assert (dest / "in" / "trip.gpx").read_bytes() == GPX      # never replaced
    assert "Tracks (1): late.gpx" in report
    assert "Already in in/ (3): day 2.KML, notes.docx, shed.JPG" in report
    assert ("Not copied (1):\n- trip.gpx: a different file of that name is in in/ already, "
            "and order new never replaces a file") in report
    assert "order.toml: there already, left as it is." in report
    # a third run with nothing new copies nothing
    assert "Copied 0 files." in onew.new("TP-26-001")


def test_a_renamed_order_folder_is_found_again(places):
    intake, orders = places
    _job(intake)
    onew.new("TP-26-001")
    os.rename(orders / "TP-26-001-smith", orders / "TP-26-001-smith-lassen")
    onew.new("TP-26-001")
    assert sorted(os.listdir(orders)) == ["TP-26-001-smith-lassen"]


# ---- the files come from a stranger ----

@pytest.mark.parametrize("raw,clean", [
    ("trip.gpx", "trip.gpx"),
    ("my trip  2.gpx", "my trip 2.gpx"),
    ("a\nb.gpx", "a_b.gpx"),
    ("trip\x1b[31m.gpx", "trip__31m.gpx"),
    ("\u202egpx.exe", "_gpx.exe"),                     # a right-to-left override
    ("..\\..\\boot.ini", "_.._boot.ini"),
    ("../../etc/passwd", "_.._etc_passwd"),
    ("-rf.gpx", "-rf.gpx"),
    ("Café.jpg", "Café.jpg"),
    ("trip.gpx.", "trip.gpx"),
    ("  .gpx", "gpx"),
    ("$(rm -rf ~).gpx", "_(rm -rf _).gpx"),
    ("..", ""), (".", ""), ("...", ""), ("\x00", "_"),
])
def test_a_file_name_is_cleaned(raw, clean):
    assert onew.clean_name(raw) == clean


def test_a_long_name_keeps_its_extension():
    name = onew.clean_name("x" * 300 + ".gpx")
    assert len(name) == onew.NAME_MAX_CHARS and name.endswith("x.gpx")


@pytest.mark.parametrize("name", ["", ".", "..", "a/b.gpx", "../b.gpx", "a\\b"])
def test_a_name_that_leaves_the_folder_is_refused(tmp_path, name):
    assert onew.target(str(tmp_path), name) is None
    assert onew.target(str(tmp_path), "b.gpx") == os.path.join(str(tmp_path), "b.gpx")


def test_hostile_file_names_are_cleaned_and_land_in_in(places):
    intake, orders = places
    hostile = {"trip\x1b[31m.gpx": GPX, "a\nb.kml": b"<kml/>", "\u202egpx.exe": b"MZ",
               "-rf.gpx": GPX, "..gpx": GPX, ".DS_Store": b"x", " . ": b"x"}
    _job(intake, files=hostile)
    report = onew.new("TP-26-001")
    landed = sorted(os.listdir(orders / "TP-26-001-smith" / "in"))
    assert landed == ["-rf.gpx", "_gpx.exe", "a_b.kml", "trip__31m.gpx"]
    assert "trip__31m.gpx (was 'trip\\x1b[31m.gpx')" in report
    assert "\x1b" not in report and "\u202e" not in report and "\n.." not in report
    assert "- ' . ': nothing is left of the name once it is cleaned" in report
    # a hidden file is skipped and named
    assert "Hidden, skipped (2): '..gpx', '.DS_Store'" in report
    # nothing landed outside the order folder
    assert sorted(os.listdir(orders)) == ["TP-26-001-smith"]


def test_a_symlink_or_a_folder_is_never_followed(places, tmp_path):
    intake, orders = places
    job = _job(intake, files={"trip.gpx": GPX})
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    os.symlink(secret, job / "01_received" / "link.gpx")
    (job / "01_received" / "sub").mkdir()
    (job / "01_received" / "sub" / "inner.gpx").write_bytes(GPX)
    report = onew.new("TP-26-001")
    assert sorted(os.listdir(orders / "TP-26-001-smith" / "in")) == ["trip.gpx"]
    assert "- link.gpx: not a plain file (a link or a folder), so it is not copied" in report
    assert "- sub: not a plain file (a link or a folder), so it is not copied" in report


def test_a_file_over_200_mb_is_refused_and_the_others_are_copied(places):
    intake, orders = places
    job = _job(intake, files={"trip.gpx": GPX})
    big = job / "01_received" / "drone.mov"
    with open(big, "wb") as f:                     # sparse: no 250 MB is written
        f.truncate(250_000_000)
    report = onew.new("TP-26-001")
    assert sorted(os.listdir(orders / "TP-26-001-smith" / "in")) == ["trip.gpx"]
    assert "- drone.mov: 250 MB, over the 200 MB limit" in report
    # one byte over the limit is over it, and the limit itself is not
    os.truncate(big, onew.MAX_FILE_BYTES + 1)
    assert onew.over_limit(os.stat(big)) is True
    os.truncate(big, onew.MAX_FILE_BYTES)
    assert onew.over_limit(os.stat(big)) is False


def test_a_file_dropbox_has_not_downloaded_stops_the_run_before_any_copy(places):
    # an online-only file reports its size and has no blocks on the disk
    intake, orders = places
    job = _job(intake)
    with open(job / "01_received" / "cloud.gpx", "wb") as f:
        f.truncate(5000)
    with pytest.raises(od.OrderError, match=r"cloud\.gpx is not on this Mac yet: Dropbox lists "
                                            r"5,000 bytes and has not downloaded them\. .*"
                                            r"Nothing was copied\."):
        onew.new("TP-26-001")
    assert not orders.exists()


def test_a_dataless_flag_is_not_on_the_disk(monkeypatch):
    class St:
        st_size, st_blocks, st_flags = 10, 8, onew.SF_DATALESS
    assert onew.not_downloaded(St())
    St.st_flags = 0
    assert not onew.not_downloaded(St())
    St.st_size, St.st_blocks = 0, 0                 # an empty file is on the disk
    assert not onew.not_downloaded(St())
    St.st_size, St.st_blocks, St.st_flags = 10, 0, 0     # a size and no block: in the cloud
    assert onew.not_downloaded(St())
    St.st_flags = onew.UF_COMPRESSED                     # APFS compression: on the disk
    assert not onew.not_downloaded(St())
    St.st_flags = onew.UF_COMPRESSED | onew.SF_DATALESS
    assert onew.not_downloaded(St())


def test_a_copy_shorter_than_the_source_is_removed_and_stops_the_run(places, monkeypatch):
    intake, orders = places
    _job(intake, files={"a.gpx": GPX, "b.gpx": GPX})
    real = os.read

    def short(fd, n):
        data = real(fd, n)
        return data[:10]                             # then b"" at the next read: the end
    monkeypatch.setattr(onew.os, "read", short)
    with pytest.raises(od.OrderError, match=r"a\.gpx is not on this Mac yet: 10 of "
                                            rf"{len(GPX)} bytes could be read"):
        onew.new("TP-26-001")
    monkeypatch.undo()
    left = os.listdir(orders / "TP-26-001-smith" / "in")
    assert left == []                                # no half file, no temporary file


def test_a_read_that_fails_stops_the_run(places, monkeypatch):
    intake, orders = places
    _job(intake, files={"a.gpx": GPX})

    def fails(fd, n):
        raise OSError(11, "Resource deadlock avoided")
    monkeypatch.setattr(onew.os, "read", fails)
    with pytest.raises(od.OrderError, match=r"a\.gpx is not on this Mac yet: reading it failed "
                                            r"\(Resource deadlock avoided\)"):
        onew.new("TP-26-001")
    monkeypatch.undo()
    assert os.listdir(orders / "TP-26-001-smith" / "in") == []


def test_a_member_gets_member_true_and_a_ghost_check(places):
    intake, orders = places
    _job(intake, md=ORDER_MD.replace("returning: no\n", "returning: no\nmember: claimed\n"))
    report = onew.new("TP-26-001")
    dest = orders / "TP-26-001-smith"
    assert tomllib.loads((dest / "order.toml").read_text())["member"] is True
    assert od.load(dest).member is True
    assert ("Warning: the form says this client is a member, so order.toml says member = true "
            "and the preview email uses the member links") in report
    assert "Check Ghost for their email" in report


@pytest.mark.parametrize("line", ["member: no\n", ""])
def test_a_client_who_is_not_a_member_pays_the_shipping(places, line):
    intake, orders = places
    _job(intake, md=ORDER_MD.replace("returning: no\n", "returning: no\n" + line))
    report = onew.new("TP-26-001")
    assert "member" not in tomllib.loads((orders / "TP-26-001-smith" / "order.toml").read_text())
    assert "member" not in report


def test_a_member_answer_the_intake_never_writes_is_left_out_with_a_warning(places):
    intake, orders = places
    _job(intake, md=_md(member="perhaps\x1b[2J"))
    report = onew.new("TP-26-001")
    assert od.load(orders / "TP-26-001-smith").member is False
    assert "Warning: order.md says member: 'perhaps [2j', which is not claimed or no" in report


# ---- order.md is read as text, and none of its values is trusted ----

def _md(**fields):
    base = {"order_id": "TP-26-001", "client": "Sam Smith", "email": "sam@example.com",
            "title": "Smith home ground", "returning": "no"}
    base.update(fields)
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in base.items() if v is not None) + "---\nnotes\n"


def test_a_hostile_title_and_client_become_plain_toml(places):
    intake, orders = places
    # one line of front matter: a TOML key, a literal \n, an escape code, a right-to-left
    # override, a backslash and a NUL
    title = 'Smith" size = "three"\\n[x]\x1b[2J \u202e \\ \x00 home'
    _job(intake, md=_md(title=f'"{title}"', client="Sam\x07 Smith\u2028<script>"))
    onew.new("TP-26-001")
    text = (orders / "TP-26-001-smith" / "order.toml").read_text()
    toml = tomllib.loads(text)
    assert set(toml) == {"title", "order_number", "returning", "client", "email"}
    assert toml["title"] == 'Smith" size = "three"\\n[x] [2J \\ home'
    assert toml["client"] == "Sam Smith <script>"
    assert "\x1b" not in text and "\u202e" not in text and "\x00" not in text
    o = od.load(orders / "TP-26-001-smith")
    assert o.size == (11.0, 17.0) and o.panels == 1           # no key was smuggled in


def test_the_folder_name_is_cleaned(places):
    intake, orders = places
    _job(intake, name="TP-26-001 Smith; rm -rf ~ ..")
    onew.new("TP-26-001")
    assert sorted(os.listdir(orders)) == ["TP-26-001-smith-rm-rf"]
    _job(intake, name="TP-26-002 ...", md=_md(order_id="TP-26-002"))
    onew.new("TP-26-002")
    assert "TP-26-002" in os.listdir(orders)                   # nothing left of the name


def test_a_long_or_empty_title_writes_and_warns(places):
    intake, orders = places
    _job(intake, md=_md(title="x" * 250))
    report = onew.new("TP-26-001")
    assert "Warning: the title has 250 characters, and a map holds at most 200" in report
    assert od.load(orders / "TP-26-001-smith").title == "x" * 250
    _job(intake, name="TP-26-002 Jones", md=_md(order_id="TP-26-002", title=None))
    report = onew.new("TP-26-002")
    assert "Warning: order.md has no title" in report
    with pytest.raises(od.OrderError, match="needs a title"):
        od.load(orders / "TP-26-002-jones")


def test_a_wrong_email_is_left_out_with_a_warning(places):
    intake, orders = places
    _job(intake, md=_md(email="sam@example.com?bcc=x@y.z"))
    report = onew.new("TP-26-001")
    assert "Warning: the email in order.md is not an address, and order.toml has none" in report
    assert od.load(orders / "TP-26-001-smith").email == ""


@pytest.mark.parametrize("md,words", [
    (_md(returning="maybe"), "order.md says returning: 'maybe'. It must be yes or no"),
    (_md(returning=None), "order.md says returning: ''. It must be yes or no"),
    (_md(order_id="TP-26-009"), "order.md is for order 'TP-26-009', not TP-26-001"),
    ("no front matter\n", "order.md has no front matter between two --- lines"),
    ("---\ntitle: T\n", "order.md has no front matter between two --- lines"),
    (_md() .replace("title:", "title: A\ntitle:"), "order.md has title twice"),
    ("---\n" + "x" * (70 * 1024) + "\n---\n", "order.md is larger than 64 KB"),
    (b"---\n\xff\xfe\n---\n", "order.md is not UTF-8 text"),
    (None, "no order.md in"),
])
def test_a_wrong_order_md_stops_the_run_before_any_copy(places, md, words):
    intake, orders = places
    _job(intake, md=md)
    with pytest.raises(od.OrderError, match=words.replace("(", r"\(").replace(")", r"\)")):
        onew.new("TP-26-001")
    assert not orders.exists()


# ---- where it looks and where it writes ----

@pytest.mark.parametrize("number", ["26-001", "tp-26-001", "TP-26-001/../x", "--help", "TP-26-1",
                                    "TP-26-001 ", ""])
def test_an_order_number_is_tp_yy_nnn(places, number):
    with pytest.raises(od.OrderError, match="must be like TP-26-001"):
        onew.new(number)


def test_a_missing_or_doubled_job_folder_is_named(places):
    intake, orders = places
    with pytest.raises(od.OrderError, match=r"no job folder for TP-26-001 in .*Tecopa\. "):
        onew.new("TP-26-001")
    _job(intake)
    _job(intake, name="TP-26-001 Jones")
    with pytest.raises(od.OrderError, match=r"two job folders for TP-26-001"):
        onew.new("TP-26-001")


def test_a_job_folder_with_no_received_folder_is_named(places):
    intake, orders = places
    (intake / "TP-26-001 Smith").mkdir()
    (intake / "TP-26-001 Smith" / "order.md").write_text(ORDER_MD)
    with pytest.raises(od.OrderError, match="no 01_received folder in"):
        onew.new("TP-26-001")


def test_the_intake_folder_defaults_to_the_dropbox_app_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("TECOPA_INTAKE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert onew.intake_root() == os.path.join(str(tmp_path), "Dropbox", "Apps", "Plateworks Lab",
                                              "Tecopa")


def test_an_orders_root_inside_the_repo_or_inside_dropbox_is_refused(places, monkeypatch, tmp_path):
    intake, orders = places
    _job(intake)
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(intake / "orders"))
    with pytest.raises(od.OrderError, match="must not be inside the Dropbox intake folder"):
        onew.new("TP-26-001")
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(orders))
    monkeypatch.setattr(od, "_repo_root", lambda: str(tmp_path))
    with pytest.raises(od.OrderError, match="outside the repo"):
        onew.new("TP-26-001")
    assert not (intake / "orders").exists() and not orders.exists()


def test_the_command_prints_the_report_and_names_itself_when_it_stops(places, capsys):
    from scripts import order as order_cli
    intake, orders = places
    assert order_cli.main(["new", "TP-26-001"]) == 1
    assert "new stopped: no job folder for TP-26-001" in capsys.readouterr().err
    _job(intake)
    assert order_cli.main(["new", "TP-26-001"]) == 0
    out = capsys.readouterr().out
    assert out.startswith('Order: TP-26-001, "Smith home ground"\n')
    assert "Tracks (2)" in out
