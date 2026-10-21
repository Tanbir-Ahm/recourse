"""
pg_harness.py -- a throwaway PostgreSQL for the database tests (not a test itself, so the suite does not run it). start() returns a Harness or None when no server (or no database package) is installed; the tests then print
SKIPPED and exit 0. The cluster is UTF-8 (psycopg hands back bytes from a SQL_ASCII one), listens on a free local port only, runs as the postgres OS user when this process is root, and is removed by stop().
"""
import glob
import os
import shutil
import socket
import subprocess
import tempfile


def _find_bin():
    for d in sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        if all(os.path.exists(os.path.join(d, n)) for n in ("initdb", "pg_ctl", "postgres", "psql")):
            return d
    w = shutil.which("initdb")
    return os.path.dirname(w) if w and shutil.which("pg_ctl") and shutil.which("postgres") and shutil.which("psql") else None


class Harness:
    def __init__(self, bin_dir):
        self.bin = bin_dir
        self.root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
        self.data = tempfile.mkdtemp(prefix="pgtest_")
        self.sock = tempfile.mkdtemp(prefix="pgsock_")
        for d in (self.data, self.sock):
            os.chmod(d, 0o700)
            if self.root:
                shutil.chown(d, "postgres", "postgres")
        self.pre = ["runuser", "-u", "postgres", "--"] if self.root else []
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.started = False

    def _run(self, *cmd):
        return subprocess.run(self.pre + list(cmd), capture_output=True, text=True, timeout=120)

    def start(self):
        r = self._run(os.path.join(self.bin, "initdb"), "-D", self.data, "-A", "trust", "-U", "postgres", "-E", "UTF8", "--locale=C.UTF-8")
        if r.returncode != 0:
            return False
        r = self._run(os.path.join(self.bin, "pg_ctl"), "-D", self.data, "-o", f"-p {self.port} -k {self.sock} -c listen_addresses=127.0.0.1 -c max_connections=200", "-l", os.path.join(self.data, "log.txt"), "-w", "start")
        self.started = r.returncode == 0
        return self.started

    def url(self, db):
        return f"postgresql://postgres@127.0.0.1:{self.port}/{db}"

    def create_db(self, name):
        r = subprocess.run([os.path.join(self.bin, "psql"), "-h", "127.0.0.1", "-p", str(self.port), "-U", "postgres", "-c", f"create database {name}"], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr

    def stop(self):
        if self.started:
            self._run(os.path.join(self.bin, "pg_ctl"), "-D", self.data, "-m", "immediate", "stop")
        shutil.rmtree(self.data, ignore_errors=True)
        shutil.rmtree(self.sock, ignore_errors=True)


def start():
    try:
        import sqlalchemy  # noqa: F401
        import alembic  # noqa: F401
        import psycopg  # noqa: F401
    except ImportError as exc:
        print(f"SKIPPED: {exc} (the database packages are in requirements.txt)")
        return None
    b = _find_bin()
    if not b:
        print("SKIPPED: no PostgreSQL server found on this machine")
        return None
    h = Harness(b)
    if not h.start():
        print("SKIPPED: the throwaway PostgreSQL server did not start")
        h.stop()
        return None
    return h
