"""Local project journal and evidence-based reports for Work trace."""
import calendar
import json
import logging
import sqlite3
import threading
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from socket import gethostname
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request
from aw_core.worktrace import write_capture_state
from .rest import host_header_check

logger = logging.getLogger(__name__)
KINDS = {"note": "工作记录", "done": "完成事项", "milestone": "里程碑", "issue": "问题", "todo": "下一步"}


def stamp(value):
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return result.timestamp()


def day_start(day):
    return datetime.combine(day, time()).astimezone().timestamp()


def period(kind, selected):
    day = date.fromisoformat(selected)
    if kind == "day":
        first, last = day, day + timedelta(days=1)
    elif kind == "week":
        first = day - timedelta(days=day.weekday())
        last = first + timedelta(days=7)
    elif kind == "month":
        first = day.replace(day=1)
        last = first + timedelta(days=calendar.monthrange(first.year, first.month)[1])
    else:
        raise ValueError("总结类型无效")
    return first, last


def union(intervals):
    out = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(end, out[-1][1]))
        else:
            out.append((start, end))
    return out


def intersection(left, right):
    left, right = union(left), union(right)
    i = j = 0
    out = []
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if end > start:
            out.append((start, end))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return out


def text_field(data, key, limit, required=False):
    value = data.get(key, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} 格式或长度无效")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{key} 不能为空")
    return value


class Journal:
    def __init__(self, root, api):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "worktrace.sqlite3"
        self.api = api
        self.lock = threading.RLock()
        self.stop = threading.Event()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                  description TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, project_id TEXT,
                  kind TEXT NOT NULL, content TEXT NOT NULL, occurred REAL NOT NULL, minutes REAL NOT NULL,
                  created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS switches(at REAL PRIMARY KEY, project_id TEXT, paused INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, kind TEXT NOT NULL, start TEXT NOT NULL,
                  end TEXT NOT NULL, project_id TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                  updated REAL NOT NULL, edited INTEGER NOT NULL DEFAULT 0,
                  UNIQUE(kind,start,end,project_id));
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS notes_time ON notes(occurred);
            """)
            now = datetime.now().astimezone()
            db.execute("INSERT OR IGNORE INTO settings VALUES('first_day',?)", (now.date().isoformat(),))
            db.execute("INSERT OR IGNORE INTO settings VALUES('auto_reports','true')")
            if not db.execute("SELECT 1 FROM switches LIMIT 1").fetchone():
                db.execute("INSERT INTO switches VALUES(?,NULL,0)", (now.timestamp(),))
        self.sync_capture()

    def connect(self):
        from contextlib import contextmanager

        @contextmanager
        def connection():
            db = sqlite3.connect(self.path, timeout=20)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()
        return connection()

    def project_check(self, db, project_id, active=False):
        if project_id:
            row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if row is None or (active and row["archived"]):
                raise ValueError("项目不存在或已归档")
        return project_id or None

    def state(self):
        with self.connect() as db:
            row = dict(db.execute("SELECT * FROM switches ORDER BY at DESC LIMIT 1").fetchone())
            row["paused"] = bool(row["paused"])
            row["auto_reports"] = db.execute("SELECT value FROM settings WHERE key='auto_reports'").fetchone()[0] == 'true'
            row["storage"] = str(self.root.parent)
            row["reports_dir"] = str(self.root.parent / "总结")
            return row

    def sync_capture(self):
        state = self.state()
        write_capture_state({"paused": state["paused"], "generation": str(state["at"])})

    def set_state(self, data):
        with self.lock:
            old = self.state()
            project_id = data.get("project_id", old["project_id"])
            paused = data.get("paused", old["paused"])
            if type(paused) is not bool or ("auto_reports" in data and type(data["auto_reports"]) is not bool):
                raise ValueError("开关值必须为布尔值")
            with self.connect() as db:
                self.project_check(db, project_id, active=True)
                if project_id != old["project_id"] or paused != old["paused"]:
                    db.execute("INSERT INTO switches VALUES(?,?,?)", (datetime.now().timestamp(), project_id, int(paused)))
                if "auto_reports" in data:
                    db.execute("UPDATE settings SET value=? WHERE key='auto_reports'", (json.dumps(data["auto_reports"]),))
            self.sync_capture()
            return self.state()

    def projects(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM projects ORDER BY archived,created DESC")]

    def save_project(self, data, project_id=None):
        name = text_field(data, "name", 100, True)
        description = text_field(data, "description", 4000)
        archived = data.get("archived", False)
        if type(archived) is not bool:
            raise ValueError("归档开关无效")
        with self.lock, self.connect() as db:
            if project_id:
                self.project_check(db, project_id)
                if archived and self.state()["project_id"] == project_id:
                    raise ValueError("请先切换到其他项目，再归档当前项目")
                db.execute("UPDATE projects SET name=?,description=?,archived=? WHERE id=?", (name, description, int(archived), project_id))
            else:
                project_id = str(uuid4())
                db.execute("INSERT INTO projects VALUES(?,?,?,?,?)", (project_id, name, description, int(archived), datetime.now().timestamp()))
        return {"id": project_id}

    def save_note(self, data, note_id=None):
        content = text_field(data, "content", 20000, True)
        kind = data.get("kind", "note")
        if kind not in KINDS:
            raise ValueError("记录类型无效")
        occurred = stamp(data.get("occurred", datetime.now(timezone.utc)))
        if occurred > datetime.now().timestamp() + 60:
            raise ValueError("工作发生时间不能在未来，待办请记录在当前时间")
        minutes = float(data.get("minutes", 0))
        if not 0 <= minutes <= 1440:
            raise ValueError("人工补录时长须在 0 到 1440 分钟之间")
        with self.connect() as db:
            project = self.project_check(db, data.get("project_id"))
            if note_id:
                result = db.execute("UPDATE notes SET project_id=?,kind=?,content=?,occurred=?,minutes=? WHERE id=?", (project, kind, content, occurred, minutes, note_id))
                if not result.rowcount:
                    raise ValueError("记录不存在")
            else:
                note_id = str(uuid4())
                db.execute("INSERT INTO notes VALUES(?,?,?,?,?,?,?)", (note_id, project, kind, content, occurred, minutes, datetime.now().timestamp()))
        return {"id": note_id}

    def notes(self, start, end, project=None):
        with self.connect() as db:
            sql = "SELECT * FROM notes WHERE occurred>=? AND occurred<?"
            args = [start, end]
            if project:
                sql += " AND project_id=?"
                args.append(project)
            return [dict(r) for r in db.execute(sql + " ORDER BY occurred DESC", args)]

    def activity(self, start, end, project=None):
        # Read only this device. Imported buckets from other computers must not double-count time.
        buckets = self.api.db.buckets()
        selected = {key: val for key, val in buckets.items() if val.get("hostname") == gethostname()}
        windows, active = [], []
        for key, bucket in selected.items():
            if bucket.get("type") not in ("currentwindow", "afkstatus"):
                continue
            events = self.api.get_events(key, start=datetime.fromtimestamp(start, timezone.utc), end=datetime.fromtimestamp(end, timezone.utc))
            for event in events:
                a = stamp(event["timestamp"])
                duration = event["duration"]
                duration = duration.total_seconds() if isinstance(duration, timedelta) else float(duration)
                b = min(a + duration, end)
                a = max(a, start)
                if b <= a:
                    continue
                if bucket["type"] == "currentwindow":
                    windows.append((a, b, event["data"].get("app", "未知应用"), event["data"].get("title", "")))
                elif event["data"].get("status") == "not-afk":
                    active.append((a, b))
        with self.connect() as db:
            switches = [dict(row) for row in db.execute("SELECT * FROM switches WHERE at<? ORDER BY at", (end,))]
        assigned = []
        for i, row in enumerate(switches):
            finish = switches[i + 1]["at"] if i + 1 < len(switches) else end
            if not row["paused"] and (not project or row["project_id"] == project):
                assigned.append((max(start, row["at"]), min(end, finish)))
        allowed = intersection(active, assigned)
        by_app, timeline, all_spans = defaultdict(list), [], []
        for a, b, app, title in windows:
            spans = intersection([(a, b)], allowed)
            by_app[app].extend(spans)
            all_spans.extend(spans)
            for left, right in spans:
                timeline.append({"start": left, "end": right, "app": app, "title": title})
        apps = [{"app": app, "seconds": round(sum(b-a for a, b in union(spans)))} for app, spans in by_app.items()]
        return {"seconds": round(sum(b-a for a, b in union(all_spans))),
                "apps": sorted(apps, key=lambda x: -x["seconds"]),
                "timeline": sorted(timeline, key=lambda x: -x["start"]),
                "has_afk": any(b.get("type") == "afkstatus" for b in selected.values())}

    def overview(self, first, last, project=None):
        start, end = day_start(date.fromisoformat(first)), day_start(date.fromisoformat(last))
        if end <= start:
            raise ValueError("结束日期必须晚于开始日期")
        end = min(end, datetime.now().timestamp())
        notes = self.notes(start, end, project)
        return {"notes": notes, "activity": self.activity(start, end, project),
                "manual_minutes": sum(n["minutes"] for n in notes)}

    def reports(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM reports ORDER BY updated DESC")]

    def export_report(self, report):
        folder = self.root.parent / "总结"
        folder.mkdir(exist_ok=True)
        # Identity, never user text, owns the filename. Re-saving edits updates the same file.
        name = f'{report["kind"]}-{report["start"]}-{report["id"][:8]}.md'
        path = folder / name
        temporary = path.with_suffix(".tmp")
        temporary.write_text(report["body"], encoding="utf-8")
        temporary.replace(path)
        return str(path)

    def save_report(self, report_id, body):
        if not isinstance(body, str) or not body.strip() or len(body) > 500000:
            raise ValueError("总结内容为空或过长")
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                raise ValueError("总结不存在")
            report = dict(row)
            report.update(body=body, edited=1, updated=datetime.now().timestamp())
            path = self.export_report(report)
            db.execute("UPDATE reports SET body=?,edited=1,updated=? WHERE id=?", (body, report["updated"], report_id))
            return {**report, "path": path}

    def generate(self, data):
        kind = data.get("kind", "day")
        project = data.get("project_id") or ""
        if kind == "project":
            first, last = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
            if not project:
                raise ValueError("项目总结需要选择项目")
        else:
            first, last = period(kind, data.get("date", date.today().isoformat()))
        if first > date.today() or last <= first:
            raise ValueError("总结日期范围无效")
        with self.lock:
            with self.connect() as db:
                self.project_check(db, project)
                existing = db.execute("SELECT * FROM reports WHERE kind=? AND start=? AND end=? AND project_id=?", (kind, str(first), str(last), project)).fetchone()
                if existing and not data.get("regenerate", False):
                    report = dict(existing)
                    return {**report, "path": self.export_report(report)}
            overview = self.overview(str(first), str(last), project)
            projects = {p["id"]: p["name"] for p in self.projects()}
            label = {"day": "每日总结", "week": "每周总结", "month": "每月总结", "project": "项目总结"}[kind]
            title = f'{projects.get(project, "工作")} · {label} · {first}'
            lines = [f"# {title}", "", f"范围：{first} 至 {last - timedelta(days=1)}", "",
                     f'电脑活跃时间：{overview["activity"]["seconds"] / 60:.1f} 分钟',
                     f'人工补录时间：{overview["manual_minutes"]:.1f} 分钟（单列，不与电脑时间相加）',
                     "", "## 应用投入", ""]
            for app in overview["activity"]["apps"]:
                lines.append(f'- {app["app"]}：{app["seconds"] / 60:.1f} 分钟')
            if not overview["activity"]["apps"]:
                lines.append("暂无可确认的电脑活跃记录。")
            for key, caption in KINDS.items():
                lines += ["", f"## {caption}", ""]
                notes = [n for n in overview["notes"] if n["kind"] == key]
                for note in reversed(notes):
                    when = datetime.fromtimestamp(note["occurred"]).strftime("%m-%d %H:%M")
                    lines.append(f'- {when} [{projects.get(note["project_id"], "未关联项目")}] {note["content"]}')
                if not notes:
                    lines.append("暂无记录，可在工作台补充。")
            lines += ["", "---", "来源：本机活动记录与人工补充。应用时长用于描述投入，不代表完成成果。", ""]
            report = {"id": existing["id"] if existing else str(uuid4()), "kind": kind, "start": str(first), "end": str(last), "project_id": project, "title": title, "body": "\n".join(lines), "updated": datetime.now().timestamp(), "edited": 0}
            path = self.export_report(report)
            with self.connect() as db:
                db.execute("INSERT OR REPLACE INTO reports VALUES(:id,:kind,:start,:end,:project_id,:title,:body,:updated,:edited)", report)
            return {**report, "path": path}

    def catch_up(self, today=None):
        today = today or date.today()
        if not self.state()["auto_reports"]:
            return
        with self.connect() as db:
            first = date.fromisoformat(db.execute("SELECT value FROM settings WHERE key='first_day'").fetchone()[0])
            last = db.execute("SELECT value FROM settings WHERE key='last_auto_day'").fetchone()
        cursor = max(first, date.fromisoformat(last[0]) + timedelta(days=1)) if last else first
        while cursor < today and not self.stop.is_set():
            self.generate({"kind": "day", "date": str(cursor)})
            if cursor.weekday() == 6:
                self.generate({"kind": "week", "date": str(cursor)})
            if (cursor + timedelta(days=1)).month != cursor.month:
                self.generate({"kind": "month", "date": str(cursor)})
            with self.connect() as db:
                db.execute("INSERT OR REPLACE INTO settings VALUES('last_auto_day',?)", (str(cursor),))
            cursor += timedelta(days=1)

    def start_scheduler(self):
        def run():
            while not self.stop.wait(30):
                try:
                    self.catch_up()
                except Exception:
                    logger.exception("Work trace 自动总结失败，将于下次检查重试")
        threading.Thread(target=run, name="worktrace-reports", daemon=True).start()


def blueprint(journal):
    bp = Blueprint("worktrace", __name__, url_prefix="/api/0/worktrace")

    @bp.before_request
    @host_header_check
    def guard():
        if request.method not in ("GET", "OPTIONS") and not request.is_json:
            return jsonify(message="请使用 JSON 请求"), 415

    @bp.errorhandler(ValueError)
    @bp.errorhandler(TypeError)
    @bp.errorhandler(KeyError)
    def invalid(error):
        return jsonify(message=str(error)), 400

    def payload():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("请求必须为对象")
        return data

    @bp.route("/state", methods=["GET", "PATCH"])
    def state():
        return jsonify(journal.state() if request.method == "GET" else journal.set_state(payload()))

    @bp.route("/projects", methods=["GET", "POST"])
    def projects():
        return jsonify(journal.projects() if request.method == "GET" else journal.save_project(payload()))

    @bp.route("/projects/<project_id>", methods=["PUT"])
    def project(project_id):
        return jsonify(journal.save_project(payload(), project_id))

    @bp.route("/overview")
    def overview():
        first = request.args.get("start", date.today().isoformat())
        last = request.args.get("end", (date.today() + timedelta(days=1)).isoformat())
        return jsonify(journal.overview(first, last, request.args.get("project_id")))

    @bp.route("/notes", methods=["POST"])
    def notes():
        return jsonify(journal.save_note(payload()))

    @bp.route("/notes/<note_id>", methods=["PUT", "DELETE"])
    def note(note_id):
        if request.method == "PUT":
            return jsonify(journal.save_note(payload(), note_id))
        with journal.connect() as db:
            db.execute("DELETE FROM notes WHERE id=?", (note_id,))
        return jsonify(ok=True)

    @bp.route("/reports", methods=["GET", "POST"])
    def reports():
        return jsonify(journal.reports() if request.method == "GET" else journal.generate(payload()))

    @bp.route("/reports/<report_id>", methods=["PUT"])
    def report(report_id):
        return jsonify(journal.save_report(report_id, payload().get("body")))

    return bp
