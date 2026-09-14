"""Source launcher for Work trace. Run with the project's virtual environment."""
import argparse
import ctypes
import os
from pathlib import Path
import sys
import faulthandler


def setup_startup_log(folder):
    folder.mkdir(parents=True, exist_ok=True)
    log = open(folder / "startup.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log
    faulthandler.enable(log)
    return log


def desktop():
    if sys.platform == "win32":
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buffer) != 0:
            raise OSError("无法获取 Windows 桌面路径")
        return Path(buffer.value)
    return Path.home() / "Desktop"


def main():
    parser = argparse.ArgumentParser(description="Work trace 工作留痕")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-autostart", action="store_true")
    parser.add_argument("--testing", action="store_true")
    args = parser.parse_args()
    root = (args.data_dir or desktop() / "Work trace记录").resolve()
    os.environ["WORKTRACE_HOME"] = str(root)
    os.environ["WORKTRACE_LAUNCHER"] = str(Path(__file__).resolve())
    os.environ["WORKTRACE_NO_AUTOSTART"] = "1" if args.no_autostart or args.testing else "0"
    # Each launch is an isolated Work trace instance; no inherited AW profile.
    os.environ.pop("AW_PROFILE", None)
    if args.testing:
        os.environ["AW_PROFILE"] = "testing"
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    effective = root / "profiles" / "testing" if args.testing else root
    configs = {
        "aw-server": '[server]\nhost = "127.0.0.1"\nport = 5610\nstorage = "peewee"\ncors_origins = ""\n[server-testing]\nhost = "127.0.0.1"\nport = 5666\nstorage = "peewee"\ncors_origins = ""\n',
        "aw-client": '[server]\nhostname = "127.0.0.1"\nport = 5610\n[client]\ncommit_interval = 2\n[server-testing]\nhostname = "127.0.0.1"\nport = 5666\n[client-testing]\ncommit_interval = 2\n',
    }
    for module, contents in configs.items():
        if args.testing:
            contents = contents.replace("5610", "5666")
        folder = effective / "config" / module
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{module}.toml"
        if not path.exists():
            path.write_text(contents, encoding="utf-8")
    from aw_qt.main import main as start
    start(args=["--testing"] if args.testing else [], prog_name="Work trace")


if __name__ == "__main__":
    startup_log = setup_startup_log(Path(__file__).resolve().parent / "logs")
    try:
        main()
    except Exception as error:
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, str(error), "Work trace 启动失败", 0x10)
        raise
