"""Recover interrupted dpkg work while respecting the frontend package lock."""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time


def recover(lock_file=Path("/var/lib/dpkg/lock-frontend")):
    environment = os.environ | {"DEBIAN_FRONTEND": "noninteractive", "DPKG_FRONTEND_LOCKED": "1"}
    damaged = []
    with lock_file.open("a") as lock:
        deadline = time.monotonic() + 120
        while True:
            try:
                fcntl.lockf(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another package manager holds the dpkg lock. Wait for it, then rerun setup.")
                time.sleep(1)
        # An empty read-only audit can still leave an interrupted updates
        # journal. A write-mode configure is a cheap no-op when already clean.
        print("Checking unfinished package configuration…", file=sys.stderr)
        result = subprocess.run(["dpkg", "--configure", "-a"], env=environment, timeout=900)
        # Half-installed packages can be skipped even when configure exits 0.
        # A bare apt --fix-broken install may not select their reinstallation.
        query = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Abbrev} ${binary:Package}\n"],
                               capture_output=True, text=True, check=True, timeout=30)
        damaged = [line[4:].strip() for line in query.stdout.splitlines()
                   if len(line) > 4 and line[2] == "R"]
    # dpkg can report missing dependencies after an interrupted unpack. Release
    # the frontend lock before asking apt to finish dependency installation.
    if result.returncode or damaged:
        reinstall = ["--reinstall", *damaged] if damaged else []
        subprocess.run(["apt-get", "-o", "DPkg::Lock::Timeout=120", "--fix-broken", "install", "-y", *reinstall],
                       env=os.environ | {"DEBIAN_FRONTEND": "noninteractive"}, check=True, timeout=1200)


if __name__ == "__main__":
    try:
        recover()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        sys.exit(f"Package recovery failed: {exc}")
