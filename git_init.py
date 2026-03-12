#!/usr/bin/env python3
"""Git init va birinchi commit — baza xavfsiz (.gitignore da)"""
import os
import subprocess
import sys

def find_git():
    paths = [
        r"C:\Program Files\Git\cmd\git.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
        r"C:\Program Files (x86)\Git\cmd\git.exe",
    ]
    # GitHub Desktop embedded Git
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        for name in os.listdir(localappdata):
            if name.startswith("GitHubDesktop"):
                app_dir = os.path.join(localappdata, name)
                for root, dirs, files in os.walk(app_dir):
                    if "git.exe" in files:
                        p = os.path.join(root, "git.exe")
                        if "cmd" in root or "bin" in root:
                            return p
    for p in paths:
        if os.path.isfile(p):
            return p
    return None

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    git = find_git()
    if not git:
        print("Git topilmadi. GitHub Desktop yoki Git o'rnating.")
        print("Keyin: File -> Add Local Repository -> d:\\TOTLI BI")
        return 1

    steps = [
        (["init"], "git init"),
        (["add", "."], "git add ."),
        (["commit", "-m", "TOTLI BI: Backend + Flutter mobil ilova"], "git commit"),
        (["branch", "-M", "main"], "git branch -M main"),
    ]
    for args, desc in steps:
        print(desc + "...")
        r = subprocess.run([git] + args, capture_output=True, text=True)
        if r.returncode != 0 and "nothing to commit" not in (r.stderr or ""):
            print("  ", r.stderr or r.stdout)
    print("\nTayyor. Baza (totli_holva.db) Git ga kirmaydi.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
