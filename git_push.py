#!/usr/bin/env python3
"""Git remote qo'shish va push"""
import os
import subprocess
import sys

def find_git():
    paths = [
        r"C:\Program Files\Git\cmd\git.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"),
    ]
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        for root, dirs, files in os.walk(localappdata):
            if "git.exe" in files and ("cmd" in root or "bin" in root):
                p = os.path.join(root, "git.exe")
                if "GitHubDesktop" in p or "Git" in p:
                    return p
            if root.count(os.sep) > 10:
                break
    for p in paths:
        if os.path.isfile(p):
            return p
    return None

def run(git, args):
    r = subprocess.run([git] + args, capture_output=True, text=True, cwd=os.path.dirname(os.path.abspath(__file__)))
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def main():
    git = find_git()
    if not git:
        print("Git topilmadi")
        return 1

    repo = "https://github.com/elyaclassic/totli-business-system.git"
    code, out = run(git, ["remote", "-v"])
    if "origin" not in out:
        print("git remote add origin...")
        run(git, ["remote", "add", "origin", repo])
    else:
        print("Remote mavjud:", out.split()[1] if out else "")

    # Push (agar rad etilsa — lokal versiya asosiy, force push)
    print("git push -u origin main...")
    code, out = run(git, ["push", "-u", "origin", "main"])
    if code != 0 and "rejected" in out:
        print("Remote da eski versiya. Lokal o'zgarishlar yuborilmoqda (force push)...")
        code, out = run(git, ["push", "-u", "origin", "main", "--force"])
    if code != 0:
        print(out)
        return 1
    print("Muvaffaqiyatli!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
