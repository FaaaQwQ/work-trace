"""Work trace integration checks using isolated storage and synthetic activity."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from socket import gethostname
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from aw_core.models import Event
from aw_core.worktrace import capture_state
from aw_server.server import AWFlask
from aw_server.worktrace import Journal, day_start, period


@pytest.fixture(params=["memory", "peewee"])
def app(tmp_path, monkeypatch, request):
    from aw_datastore import get_storage_methods
    monkeypatch.setenv("WORKTRACE_HOME", str(tmp_path))
    monkeypatch.delenv("AW_PROFILE", raising=False)
    return AWFlask("127.0.0.1", testing=False, storage_method=get_storage_methods()[request.param])


def test_notes_projects_reports_roundtrip(app):
    client = app.test_client()
    base = "/api/0/worktrace"
    project = client.post(base + "/projects", json={"name": "产品交付"}).json["id"]
    assert client.patch(base + "/state", json={"project_id": project}).json["project_id"] == project
    assert client.patch(base + "/state", json={"paused": True}).json["paused"]
    assert capture_state()["paused"]
    assert client.patch(base + "/state", json={"paused": False}).status_code == 200
    note = {"project_id": project, "kind": "done", "content": "完成交付清单", "minutes": 25}
    nid = client.post(base + "/notes", json=note).json["id"]
    assert client.put(base + "/notes/" + nid, json={**note, "content": "完成评审"}).status_code == 200
    overview = client.get(base + "/overview").json
    assert overview["notes"][0]["content"] == "完成评审"
    assert overview["manual_minutes"] == 25
    report = client.post(base + "/reports", json={"kind": "day"}).json
    assert "完成评审" in report["body"]
    assert Path(report["path"]).is_file()
    edited = client.put(base + "/reports/" + report["id"], json={"body": "# 人工润色的总结"}).json
    assert edited["edited"] == 1
    again = client.post(base + "/reports", json={"kind": "day"}).json
    assert again["body"] == "# 人工润色的总结"
    assert Path(again["path"]).read_text(encoding="utf-8") == again["body"]
    reopened = Journal(app.journal.root, app.api)
    assert reopened.reports()[0]["body"] == again["body"]
    assert client.delete(base + "/notes/" + nid, json={}).status_code == 200
    assert client.get(base + "/overview").json["notes"] == []


def test_activity_clips_afk_pause_project_and_deduplicates(app):
    journal = app.journal
    start = day_start(date(2024, 3, 1))
    project = journal.save_project({"name": "跨月项目"})["id"]
    with journal.connect() as db:
        db.execute("DELETE FROM switches")
        db.executemany("INSERT INTO switches VALUES(?,?,?)", [
            (start, project, 0), (start + 300, project, 1),
            (start + 400, project, 0), (start + 500, None, 0),
        ])
    for bid, kind, data, duration in [
        ("window", "currentwindow", {"app": "editor", "title": "文档"}, 900),
        ("window-duplicate", "currentwindow", {"app": "editor", "title": "文档"}, 900),
        ("afk", "afkstatus", {"status": "not-afk"}, 600),
    ]:
        app.api.create_bucket(bid, kind, hostname=gethostname(), client="test")
        app.api.create_events(bid, [Event(timestamp=datetime.fromtimestamp(start, timezone.utc), duration=duration, data=data)])
    # An imported computer must not inflate this device's total.
    app.api.create_bucket("other", "currentwindow", hostname="other-device", client="test")
    app.api.create_events("other", [Event(timestamp=datetime.fromtimestamp(start, timezone.utc), duration=9999, data={"app": "other"})])
    result = journal.activity(start, start + 1000)
    assert result["seconds"] == 500
    assert result["apps"] == [{"app": "editor", "seconds": 500}]
    assert journal.activity(start, start + 1000, project)["seconds"] == 400
    assert journal.activity(start + 450, start + 1000, project)["seconds"] == 50


def test_calendar_and_catchup_idempotence(app):
    journal = app.journal
    assert period("week", "2024-12-31") == (date(2024, 12, 30), date(2025, 1, 6))
    assert period("month", "2024-02-15") == (date(2024, 2, 1), date(2024, 3, 1))
    with journal.connect() as db:
        db.execute("UPDATE settings SET value='2024-03-30' WHERE key='first_day'")
    journal.catch_up(date(2024, 4, 1))
    reports = journal.reports()
    assert sorted(r["kind"] for r in reports) == ["day", "day", "month", "week"]
    journal.save_report(reports[0]["id"], "保留我的编辑")
    journal.catch_up(date(2024, 4, 1))
    assert len(journal.reports()) == 4
    assert any(r["body"] == "保留我的编辑" for r in journal.reports())
    journal.set_state({"auto_reports": False})
    journal.catch_up(date(2024, 4, 3))
    assert len(journal.reports()) == 4


@pytest.mark.parametrize("path,method,data", [
    ("/notes", "post", {"content": ""}),
    ("/notes", "post", {"content": "abc", "minutes": -1}),
    ("/notes", "post", {"content": "abc", "occurred": "2024-01-01T00:00:00"}),
    ("/notes", "post", {"content": "abc", "project_id": "missing"}),
    ("/state", "patch", {"paused": "false"}),
    ("/reports", "post", {"kind": "project"}),
    ("/reports", "post", {"kind": "bad"}),
])
def test_invalid_input(app, path, method, data):
    assert getattr(app.test_client(), method)("/api/0/worktrace" + path, json=data).status_code == 400


def test_host_and_content_type_guards(app):
    client = app.test_client()
    assert client.get("/api/0/worktrace/state", headers={"Host": "evil.example"}).status_code == 400
    assert client.post("/api/0/worktrace/notes", data="content=abc").status_code == 415


def test_archive_current_project_and_cross_month_report(app):
    journal = app.journal
    project = journal.save_project({"name": "长期项目"})["id"]
    journal.set_state({"project_id": project})
    with pytest.raises(ValueError):
        journal.save_project({"name": "长期项目", "archived": True}, project)
    for occurred in ("2024-01-31T10:00:00+08:00", "2024-02-02T10:00:00+08:00"):
        journal.save_note({"content": "跨月里程碑", "kind": "milestone", "project_id": project, "occurred": occurred})
    report = journal.generate({"kind": "project", "start": "2024-01-01", "end": "2024-03-01", "project_id": project})
    assert report["body"].count("跨月里程碑") == 2


def test_afk_resume_cannot_backdate_into_pause(app):
    from aw_watcher_afk.afk import AFKWatcher
    journal = app.journal
    journal.set_state({"paused": True})
    watcher = SimpleNamespace(settings=SimpleNamespace(timeout=180, poll_time=5), client=Mock(), bucketname="afk")
    previous = datetime.now(timezone.utc) - timedelta(minutes=10)
    AFKWatcher.ping(watcher, False, previous)
    watcher.client.heartbeat.assert_not_called()
    journal.set_state({"paused": False})
    AFKWatcher.ping(watcher, False, previous)
    event = watcher.client.heartbeat.call_args.args[1]
    assert event.timestamp.timestamp() >= journal.state()["at"] - .001
    assert event.data["worktrace_session"]


def test_worktrace_dirs_keep_testing_separate(tmp_path, monkeypatch):
    from aw_core.dirs import get_data_dir
    monkeypatch.setenv("WORKTRACE_HOME", str(tmp_path))
    monkeypatch.setenv("AW_PROFILE", "testing")
    assert Path(get_data_dir()) == tmp_path / "profiles" / "testing" / "data"


@pytest.mark.parametrize("testing,port", [(False, 5610), (True, 5666)])
def test_source_launcher_keeps_ports_and_startup_command_consistent(tmp_path, monkeypatch, testing, port):
    import importlib.util
    import os
    import sys
    import aw_qt.main
    from aw_qt.config import AwQtSettings
    from aw_qt.autostart import _command

    launcher = Path(__file__).resolve().parents[2] / "worktrace.py"
    spec = importlib.util.spec_from_file_location("worktrace_source_launcher", launcher)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = tmp_path / "含空格的 工作目录"
    monkeypatch.setenv("WORKTRACE_HOME", str(data))
    monkeypatch.setenv("WORKTRACE_LAUNCHER", str(launcher))
    monkeypatch.setenv("WORKTRACE_NO_AUTOSTART", "1")
    monkeypatch.setenv("PATH", os.environ["PATH"])
    monkeypatch.setenv("AW_PROFILE", "")
    monkeypatch.setattr(aw_qt.main, "main", Mock())
    monkeypatch.setattr(sys, "argv", [str(launcher), "--data-dir", str(data), "--no-autostart"] + (["--testing"] if testing else []))
    module.main()
    profile = "testing" if testing else "default"
    assert AwQtSettings(profile).port == port
    command = _command()
    assert str(launcher) in command
    assert command[command.index("--data-dir") + 1] == str(data)
    assert ("--testing" in command) == testing
