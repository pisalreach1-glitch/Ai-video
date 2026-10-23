"""Setup automatic background launch on Windows logon."""
import os
import sys
import subprocess
from pathlib import Path

def setup_startup_shortcut():
    startup_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    shortcut_path = startup_dir / "Telegram Video Bot.lnk"

    # Workspace directory
    workspace_dir = Path(__file__).resolve().parent.parent
    vbs_path = workspace_dir / "start_bot_background.vbs"

    if shortcut_path.exists():
        shortcut_path.unlink()

    import tempfile
    ps_file = Path(tempfile.gettempdir()) / "create_bot_shortcut.ps1"
    ps_file.write_text(f"""$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath = '{vbs_path}'
$s.WorkingDirectory = '{workspace_dir}'
$s.WindowStyle = 0
$s.Description = 'Start Telegram Video Bot in Background'
$s.Save()
""", encoding="utf-8")

    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_file)], check=True)
    if ps_file.exists():
        ps_file.unlink()
    print(f"Startup shortcut created/updated successfully at: {shortcut_path}")
    print(f"Target: wscript.exe \"{vbs_path}\"")
    print(f"Working directory: {workspace_dir}")

if __name__ == "__main__":
    setup_startup_shortcut()
