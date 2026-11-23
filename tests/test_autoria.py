import json
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import sellar_autoria  # noqa: E402
import verificar_autoria  # noqa: E402


def _ini(tmp_path, lines, name="global.ini"):
    p = tmp_path / name
    p.write_bytes(b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return p


REGISTRO = {"lineas": [
    {"clave": "A_desc", "ahora": "El cometa verde cruza el cielo cada martes.",
     "fragmentos": "el cometa verde cruza el cielo"},
    {"clave": "B_desc", "ahora": "Refugio de nutrias y pelicanos.", "fragmentos": "algo que no aparece / refugio de nutrias"},
    {"clave": "C_desc", "ahora": "Brilla como una perla.", "fragmentos": "brilla como una perla (nota)"},
]}


def test_registro_identicas_parciales_y_ausentes(tmp_path):
    p = _ini(tmp_path, ["A_desc=El cometa verde cruza el cielo cada martes.",
                        "B_desc=Un refugio de nutrias, nada mas.",
                        "C_desc=Reluce bien."])
    res = {r["clave"]: r["estado"] for r in verificar_autoria.comparar_registro(verificar_autoria.leer_ini(p), REGISTRO)}
    assert res == {"A_desc": "identica", "B_desc": "parcial", "C_desc": "ausente"}


def test_registro_detecta_fragmento_movido_a_otra_clave(tmp_path):
    p = _ini(tmp_path, ["OTRA=Y brilla como una perla, claro."])
    res = {r["clave"]: r["estado"] for r in verificar_autoria.comparar_registro(verificar_autoria.leer_ini(p), REGISTRO)}
    assert res["C_desc"] == "parcial"


def test_cli_registro_codigo_salida(tmp_path):
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps(REGISTRO), encoding="utf-8")
    con = _ini(tmp_path, ["A_desc=El cometa verde cruza el cielo cada martes."], "con.ini")
    sin = _ini(tmp_path, ["A_desc=Otra cosa."], "sin.ini")
    assert verificar_autoria.main(["registro", str(con), "--registro", str(reg)]) == 0
    assert verificar_autoria.main(["registro", str(sin), "--registro", str(reg)]) == 1


def test_huella_encuentra_publicacion_sellada(tmp_path):
    p = _ini(tmp_path, ["K=V"])
    h = verificar_autoria.sha256_archivo(p)
    d = tmp_path / "sellos" / "traduccion-v2026.1.1.1"
    d.mkdir(parents=True)
    (d / "SHA256SUMS.txt").write_text(f"{'0' * 64}  manifest.json\n{h}  global_LIVE.ini\n", encoding="utf-8")
    assert verificar_autoria.buscar_huella(h, tmp_path / "sellos") == [("traduccion-v2026.1.1.1", "global_LIVE.ini")]
    assert verificar_autoria.main(["huella", str(p), "--sellos", str(tmp_path / "sellos")]) == 0
    assert verificar_autoria.main(["huella", str(d / "SHA256SUMS.txt"), "--sellos", str(tmp_path / "sellos")]) == 1


def test_etiquetas_pendientes(tmp_path):
    sellos = tmp_path / "sellos"
    (sellos / "traduccion-v1").mkdir(parents=True)
    (sellos / "traduccion-v1" / "SHA256SUMS.txt.ots").write_bytes(b"x")
    sums = [{"name": "SHA256SUMS.txt"}]
    releases = [
        {"tag_name": "traduccion-v1", "assets": sums},            # ya sellada
        {"tag_name": "traduccion-v2", "assets": sums},            # pendiente
        {"tag_name": "traduccion-v3", "assets": sums, "draft": True},
        {"tag_name": "traduccion-v4", "assets": []},              # sin SHA256SUMS
        {"tag_name": "v2.1.1", "assets": sums},                   # instalador
    ]
    assert sellar_autoria.etiquetas_pendientes(releases, sellos) == ["traduccion-v2"]


def test_registros_sin_sello(tmp_path):
    reg = tmp_path / "registro"
    reg.mkdir()
    (reg / "a.txt").write_text("x")
    (reg / "b.txt").write_text("y")
    (reg / "b.txt.ots").write_bytes(b"z")
    assert [p.name for p in sellar_autoria.registros_sin_sello(reg)] == ["a.txt"]
