"""Avisos para los jugadores (AVISO.txt del repositorio)."""
import base64
import json

from conftest import FakeClient, FakeHttp, make_cfg
from sctrad.errors import NetworkError, NotFoundError
from sctrad.github import ReleaseClient
from sctrad.notice import MAX_LINES, NoticeLine, parse_notice
from sctrad.service import UpdateService

CH = ("LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW")


def test_parse_notice_channels_comments_and_limits():
    txt = ("﻿# comentario\n\n[PTU] Trabajando en la versión PTU 5.0\n[live]  CANAL LIVE NUEVA VERSION EN CAMINO...\n"
           "[XYZ] etiqueta desconocida\n<b>sin html</b>\x07\nquinta\nsexta\n").encode("utf-8")
    lines = parse_notice(txt, CH)
    assert lines[0] == NoticeLine("Trabajando en la versión PTU 5.0", "PTU")
    assert lines[1] == NoticeLine("CANAL LIVE NUEVA VERSION EN CAMINO...", "LIVE")
    assert lines[2] == NoticeLine("[XYZ] etiqueta desconocida", None)
    assert lines[3].text == "<b>sin html</b>"          # se pinta como texto plano
    assert len(lines) == MAX_LINES
    assert parse_notice(b"# solo comentarios\n", CH) == []
    assert parse_notice(b"\xff\xfe", CH) == []
    assert len(parse_notice(("x" * 500).encode(), CH)[0].text) == 161


class JsonHttp(FakeHttp):
    def __init__(self, payload=None, exc=None):
        super().__init__()
        self.payload, self.exc, self.etags = payload, exc, []

    def get_json(self, url, etag=None, max_bytes=0):
        self.etags.append(etag)
        if self.exc:
            raise self.exc
        if etag == "e1":
            return 304, None, "e1"
        return 200, self.payload, "e1"


def test_client_reads_contents_api_with_etag():
    cfg = make_cfg()
    body = "[PTU] Hola".encode()
    http = JsonHttp({"type": "file", "encoding": "base64", "size": len(body),
                     "content": base64.b64encode(body).decode()})
    c = ReleaseClient(cfg, http)
    assert c.notice() == body
    assert c.notice() == body                       # segunda vez: 304 desde la caché
    assert http.etags == [None, "e1"]
    assert ReleaseClient(cfg, JsonHttp(exc=NotFoundError("404"))).notice() == b""


def test_service_keeps_last_notice_offline(tmp_path, cfg):
    svc = UpdateService(cfg, data_dir=tmp_path / "d", http=FakeHttp(), client=FakeClient(notice=b"[LIVE] Parche"),
                        detector=lambda: [])
    assert svc.fetch_notice() == [NoticeLine("Parche", "LIVE")]
    off = UpdateService(cfg, data_dir=tmp_path / "d", http=FakeHttp(), client=FakeClient(error=NetworkError("x")),
                        detector=lambda: [])
    assert off.fetch_notice() == [NoticeLine("Parche", "LIVE")]
    empty = UpdateService(cfg, data_dir=tmp_path / "d", http=FakeHttp(), client=FakeClient(notice=b""),
                          detector=lambda: [])
    assert empty.fetch_notice() == []                # aviso borrado en GitHub -> desaparece
    assert json.loads((tmp_path / "d" / "state.json").read_text(encoding="utf-8"))["cache"]["notice_b64"] == ""
