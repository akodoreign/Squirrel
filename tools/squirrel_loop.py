"""The squirrels, for ever (user 2026-11-24: "i need them to just keep going and recycling fixing till they all reach the
end of all quests, main one first. help the llm out").

Each of the two windows works on its own, one road at a time, until every traveler's road and side quests are done:
  - finished roads' side quests take priority in either window, including retries of stalled side-quest runs.
    A road is never in both windows at once.
  - story phase: a run from the road's latest save state (markerchase --resume); a road whose game says it is
    walked (RokuganChase "WALKED <pid> yes") moves on to its side quests;
  - side phase: markerchase sidequests from the end of that road; only observed completion flags count as verified.
    Broken or missing quests remain pending, not passed.
  - conversations phase: replay the road, exercise untried dialogue choices and ordinary interactions, and keep notes.
    Replays continue; observed choices are not a claim that every conversation has been discovered.
  - queued minigame replays share the follow-up queue fairly, with observed results kept separately from quest progress.
  - a road that ends three runs running at the same goal is parked ("needs Claude") so it stops eating window time;
    its save states and logs are kept. STATUS.md says where everyone is after each run.
(user 2026-11-24: "squirrels must be hybernating") no window waits for the other, and no squirrel waits on Claude
(markerchase files the question in ASK/ and the squirrel goes on). The local model drives both windows when stuck.
Read only, like the squirrels: it never changes the game.

    python -E tools/squirrel_loop.py [--minutes 60]
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
from squirrel_config import OUTPUT_ROOT, TRAVELER_ROOT, validate_traveler

ROOT = str(TRAVELER_ROOT)
OUT = str(OUTPUT_ROOT)
RUNS = os.path.join(OUT, "player-runs")
STATE = os.path.join(OUT, "loop_state.json")
STATUS = os.path.join(OUT, "STATUS.md")
PY = sys.executable
sys.path.insert(0, HERE)
import markerchase as mc                                                          # noqa: E402 (PATHS, path_quests)

LOCK = threading.Lock()


def log_of(job):
    p = os.path.join(RUNS, job, "log.txt")
    return open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else ""


def run(mode, i, engine, minutes, tag):
    args = [PY, "-E", "-u", os.path.join(HERE, "markerchase.py"), mode, "--only", str(i),
            "--minutes", str(minutes), "--windows", "1", "--engine", engine, "--resume"]
    with open(os.path.join(OUT, "orchestrator_%s.txt" % tag), "a", encoding="utf-8") as out:
        out.write("\n=== %s %s road %d (%s)\n" % (time.strftime("%H:%M"), mode, i, mc.PATHS[i]))
        out.flush()
        return subprocess.call(args, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)


def write_state(st):
    json.dump(st, open(STATE, "w"), indent=1)
    with open(STATUS, "w", encoding="utf-8") as f:
        f.write("# Squirrels (%s)\n\n| road | phase | runs | last goal | same goal | broken quests | unverified side quests | now |\n"
                "|---|---|---|---|---|---|---|---|\n" % time.strftime("%Y-%m-%d %H:%M"))
        for i, s in sorted(st.items(), key=lambda kv: int(kv[0])):
            pending = ", ".join(str(q) for q in s["pending"]) if "pending" in s else "not yet reconciled"
            active = ("%s (%s)" % (s["active_mode"], s["busy"])
                      if s.get("active_mode") and s.get("busy") else s.get("busy") or "-")
            f.write("| %s | %s | %d | %s | %d | %s | %s | %s |\n" % (s["name"], s["phase"], s["cycles"], s["last_goal"],
                                                              s["same"], ", ".join(s["broken"]) or "-",
                                                              pending or "-",
                                                              active))
        queued = mc.queued_minigames()
        if queued:
            f.write("\nQueued minigames (baseline results still unobserved): " + "; ".join(queued) + ".\n")
        f.write("\nMinigame results are assisted; full difficulty, input and reward coverage is not implied.\n")


def judge(i, s):
    """Advance only on observed evidence; retain blocked work for another run."""
    s["cycles"] += 1
    if s["phase"] == "story":
        text = log_of("story_%d_%s" % (i, s["name"]))
        walked = re.findall(r"\[RT\] CHASE WALKED \S+ (yes|no)", text)
        if walked and walked[-1] == "yes":
            s["phase"], s["same"] = "side", 0
            return
    elif s["phase"] == "side":
        text = log_of("side_%d_%s" % (i, s["name"]))
        expected = set(mc.path_quests(mc.PIDS[i]))
        verified = {int(q) for q in re.findall(
            r"\[RT\] CHASE QUESTDONE (\d+) \(completion flag set\)", text)}
        s["broken"] = sorted(set(re.findall(r"\[RT\] CHASE QUESTBROKEN (\d+)", text))
                             - {str(q) for q in verified})
        s["pending"] = sorted(expected - verified)
        if expected <= verified:
            s["phase"], s["same"] = "conversations", 0
            return
    else:
        # Conversation coverage is open-ended: a quiet run is not proof of exhaustive coverage.
        return
    goals = re.findall(r"\[RT\] CHASE GOAL (.+)", text)
    g = goals[-1] if goals else ""
    s["same"] = s["same"] + 1 if g and g == s["last_goal"] else 0
    s["last_goal"] = g
    if s["same"] >= 3:
        s["phase"] = "parked (%s): needs Claude" % s["phase"]


def pick(st, window):
    """The next road for this window (the fewest runs first), or None."""
    free = [(s["cycles"], int(i)) for i, s in st.items() if not s.get("busy")]
    story = sorted(c for c in free if st[str(c[1])]["phase"] == "story")
    side = sorted(c for c in free if st[str(c[1])]["phase"] in ("side", "parked (side): needs Claude"))
    conversations = sorted(c for c in free if st[str(c[1])]["phase"] == "conversations")
    followup = sorted([(count, i, "sidequests") for count, i in side]
                      + [(count, i, "conversations") for count, i in conversations])
    if mc.queued_minigames():
        for count, i in free:
            if st[str(i)].get("last_mode") == "games" and st[str(i)]["phase"] in (
                    "story", "side", "parked (side): needs Claude", "conversations"):
                continue
            followup = [candidate for candidate in followup if candidate[1] != i]
            followup.append((count, i, "games"))
        followup.sort()
    if followup:
        _, i, mode = followup[0]
        return mode, i
    if story:
        return "story", story[0][1]
    return None


def worker(st, window, engine, minutes, stop):
    while not stop.is_set():
        with LOCK:
            if not mc.queued_minigames() and not [s for s in st.values() if s["phase"] in ("story", "side", "conversations")]:
                # (2026-11-25: all eight parked and the loop quit for the night) parked is a pause, not an end: when
                # nothing else is left, every parked road gets another round (the model's lessons grow each time)
                parked = [s for s in st.values() if s["phase"].startswith("parked")]
                if not parked:
                    return
                for s in parked:
                    s["phase"] = "side" if "(side)" in s["phase"] else "story"
                    s["same"] = 0
                write_state(st)
            job = pick(st, window)
            if job:
                if job[0] == "sidequests":
                    st[str(job[1])]["phase"] = "side"
                st[str(job[1])]["busy"] = window
                st[str(job[1])]["active_mode"] = job[0]
                write_state(st)
        if not job:
            time.sleep(60)                                # (everything left is in the other window)
            continue
        mode, i = job
        try:
            result = run(mode, i, engine, minutes * 2 if mode == "sidequests" else minutes, window)
        except OSError as error:
            print("Unable to start Squirrel runner: %s" % error, file=sys.stderr, flush=True)
            result = 1
        with LOCK:
            s = st[str(i)]
            s["busy"] = ""
            if result:
                s.pop("active_mode", None)
                write_state(st)
                stop.set()
                print("Squirrel runner failed (exit %s); see %s" %
                      (result, os.path.join(OUT, "orchestrator_%s.txt" % window)),
                      file=sys.stderr, flush=True)
                return
            if mode == "games":
                s["cycles"] += 1
                s["games_runs"] = s.get("games_runs", 0) + 1
            else:
                judge(i, s)
            s["last_mode"] = mode
            s.pop("active_mode", None)
            write_state(st)


def main():
    validate_traveler()
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(mc.MINIGAME_QUEUE):
        mc.queue_minigames()
    a = sys.argv[1:]
    minutes = int(a[a.index("--minutes") + 1]) if "--minutes" in a else 60
    names = [p.lower() for p in mc.PATHS]
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    for i, n in enumerate(names):
        st.setdefault(str(i), {"name": n, "phase": "story", "cycles": 0, "last_goal": "", "same": 0, "broken": []})
    for s in st.values():
        if "--adopt" in a and s.get("busy"):
            if s.get("active_mode") == "games":
                s["cycles"] += 1
                s["games_runs"] = s.get("games_runs", 0) + 1
            else:
                judge(names.index(s["name"]), s)
        s["busy"] = ""
        if s["phase"] == "done":
            s["phase"] = "side"
    write_state(st)
    # (user 2026-11-24: "1 squirrel at a time since its just going to run and run") one window unless --windows 2
    nwin = int(a[a.index("--windows") + 1]) if "--windows" in a else 1
    stop = threading.Event()
    ws = [threading.Thread(target=worker, args=(st, "w1", "main", minutes, stop))]
    if nwin > 1:
        ws.append(threading.Thread(target=worker, args=(st, "w2", "-w2", minutes, stop)))
    for k, w in enumerate(ws):
        if k:
            time.sleep(15)                                # (the two engines don't start in the same second)
        w.start()
    for w in ws:
        w.join()
    if stop.is_set():
        raise SystemExit(1)
    print("squirrel loop: every road done")


if __name__ == "__main__":
    main()
