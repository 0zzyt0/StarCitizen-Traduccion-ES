"""Vigilante de procesos: comprobar al abrir el launcher y al cerrar el juego."""
import threading

from conftest import make_cfg
from sctrad.state import StateStore
from sctrad.watcher import EV_GAME_CLOSED, EV_LAUNCHER, ProcessWatcher, run_watcher


class Seq:
    def __init__(self, frames):
        self.frames = list(frames)

    def __call__(self):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def test_detects_launcher_start_and_game_close():
    frames = Seq([set(), {"rsi launcher.exe"}, {"rsi launcher.exe", "starcitizen.exe"},
                  {"rsi launcher.exe", "starcitizen.exe"}, {"rsi launcher.exe"}, set()])
    events, t = [], [0.0]
    w = ProcessWatcher(["RSI Launcher.exe"], ["StarCitizen.exe"], events.append, frames, clock=lambda: t[0])
    for _ in range(6):
        w.step()
        t[0] += 5
    assert events == [EV_LAUNCHER, EV_GAME_CLOSED]


def test_launcher_already_open_counts_and_cooldown():
    events, t = [], [0.0]
    frames = Seq([{"rsi launcher.exe"}, {"rsi launcher.exe"}, set(), {"rsi launcher.exe"}])
    w = ProcessWatcher(["RSI Launcher.exe"], ["StarCitizen.exe"], events.append, frames, clock=lambda: t[0])
    for _ in range(4):
        w.step()
        t[0] += 10
    assert events == [EV_LAUNCHER]  # reabrirlo a los 30 s no repite la comprobación
    t[0] += 1000
    w.step()  # sigue abierto: no hay flanco nuevo
    assert events == [EV_LAUNCHER]


def test_game_already_running_at_start_is_not_an_event():
    events = []
    frames = Seq([{"starcitizen.exe"}, {"starcitizen.exe"}])
    w = ProcessWatcher(["RSI Launcher.exe"], ["StarCitizen.exe"], events.append, frames)
    w.step()
    assert events == []


def test_run_watcher_exits_when_disabled(tmp_path):
    cfg = make_cfg()
    store = StateStore(tmp_path)
    store.update_settings(auto_update=False)
    assert run_watcher(cfg, tmp_path, spawn=lambda o: None, list_names=lambda: set()) == 0


def test_run_watcher_spawns_and_stops(tmp_path):
    cfg = make_cfg()
    store = StateStore(tmp_path)
    store.update_settings(auto_update=True, task_registered=True)
    spawned, stop = [], threading.Event()
    frames = Seq([set(), {"rsi launcher.exe"}, {"rsi launcher.exe"}])

    def spawn(origin):
        spawned.append(origin)
        stop.set()
    th = threading.Thread(target=run_watcher, args=(cfg, tmp_path),
                          kwargs=dict(poll=0.01, stop=stop, spawn=spawn, list_names=frames))
    th.start()
    th.join(5)
    assert spawned == [EV_LAUNCHER] and not th.is_alive()
