"""Films the app against `pr_wizard.api --fake`: one frame folder per scene in WORK/frames.

Usage: record.py WORK   (WORK holds `PR Wizard.app` with its demo bundle id and `capture.dylib`)
"""
import atexit, os, shutil, socket, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.abspath(sys.argv[1])
OUT, SOCK = f"{WORK}/frames", f"{tempfile.gettempdir()}/prw-demo.sock"  # a socket path caps at 104 bytes


def start(empty=False):
    api = subprocess.Popen([sys.executable, "-m", "pr_wizard.api", "--fake", "--socket", SOCK, "--fake-speed", "8"]
                           + ["--fake-empty"] * empty, cwd=ROOT, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    app = subprocess.Popen([f"{WORK}/PR Wizard.app/Contents/MacOS/PRWizard", "-socket", SOCK],
                           env=dict(os.environ, DYLD_INSERT_LIBRARIES=f"{WORK}/capture.dylib", PRW_DEMO=OUT),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    atexit.register(stop, api, app)
    time.sleep(4)
    cmd("size 1180 640")
    time.sleep(2)
    return api, app


def stop(*procs):
    for p in procs:
        p.terminate()
    time.sleep(1)


def cmd(*lines):
    with open(f"{OUT}/cmd.tmp", "w") as f:
        f.write("\n".join(lines) + "\n")
    os.rename(f"{OUT}/cmd.tmp", f"{OUT}/cmd")
    while not os.path.exists(f"{OUT}/ack"):
        time.sleep(0.02)
    os.remove(f"{OUT}/ack")


def api(method, path):
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(SOCK)
        s.sendall(f"{method} /v1/{path} HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        status = s.recv(65536).split(b"\r\n", 1)[0].decode()
    assert " 2" in status, f"{method} {path}: {status}"


def scene(name, secs, *before, then=lambda: None):
    cmd(f"rec {name}", *before)
    then()
    time.sleep(secs)
    cmd("stop")
    time.sleep(0.5)
    n = len(os.listdir(f"{OUT}/{name}"))
    assert n >= secs * 10, f"{name}: {n} frames in {secs} s. A locked screen or a sleeping display yields none"


shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT)
procs = start()
scene("queue", 4)
scene("inspect", 6, "select 1")
cmd("select 3")
api("DELETE", "prs/iprally/iprally/17201/config")  # the fixture override keeps opus alone
scene("live", 11, then=lambda: api("POST", "prs/iprally/iprally/17201/review"))
cmd("select 6")
scene("fix", 10, then=lambda: api("POST", "prs/iprally/gitops/412/fix"))
cmd("select 1")
scene("project", 5, "sidebar 2")
cmd("sidebar 0", "settings", "target settings")
for pane in ("lanes", "reviewers", "fixer"):
    cmd(f"default settingsPane {pane}", "default settingsScope" + " iprally/iprally" * (pane == "fixer"))
    time.sleep(1.5)
    scene(f"settings-{pane}", 4)
cmd("close-settings", "target queue")
stop(*procs)

procs = start(empty=True)
scene("history", 5)
stop(*procs)
