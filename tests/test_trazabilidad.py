"""Trazabilidad ISO 9001 del módulo ajuste: toda escritura de un registro deja quién, cuándo, qué había y qué quedó;
la bitácora no se puede modificar ni borrar, y una alteración por fuera de la app se detecta."""
import json
import sqlite3

import pytest

from nucleo import db
from modulos.ajuste import MODULO, datos, trazabilidad


@pytest.fixture()
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "prueba.db")
    db.inicializar([MODULO], con_ejemplos=False)
    yield tmp_path / "prueba.db"
    trazabilidad._actor.set(None)
    trazabilidad._motivo.set("")


def _registros(**filtros):
    return list(reversed(trazabilidad.consultar(**filtros)))


def test_la_base_nueva_arranca_con_un_registro_de_inicio(base):
    regs = _registros()
    assert [r["accion"] for r in regs] == ["inicio"]
    db.inicializar([MODULO], con_ejemplos=False)   # migrar es idempotente: no se repite
    assert len(_registros()) == 1


def test_alta_modificacion_y_baja_de_una_colada(base):
    trazabilidad.fijar_actor({"id": 7, "usuario": "jperez", "nombre": "Juan Pérez"}, {"name": "PC Lab"}, "10.0.0.5")
    datos.append_history({"colada": "123/26", "objetivo": "N1", "ajustes": [{"kg": {"FeSi": 1.0}}]})
    datos.update_adjustment(0, 0, {"kg": {"FeSi": 2.5}})
    trazabilidad.fijar_actor({"id": 7, "usuario": "jperez", "nombre": "Juan Pérez"}, None, "10.0.0.5",
                             motivo="Colada cargada dos veces")
    datos.delete_session(0)

    regs = _registros(colada=datos.normalize_colada_key("123/26"))
    assert [(r["entidad"], r["accion"]) for r in regs] == [("sesion", "alta"), ("sesion", "modificacion"),
                                                           ("sesion", "baja")]
    assert all(r["actor"] == "Juan Pérez (jperez)" and r["actor_tipo"] == "usuario" for r in regs)
    assert regs[0]["dispositivo"] == "PC Lab" and regs[0]["ip"] == "10.0.0.5"

    mod = trazabilidad.detalle(regs[1]["id"])
    assert mod["cambios"] == [{"campo": "ajustes[0].kg.FeSi", "antes": 1.0, "despues": 2.5}]

    baja = trazabilidad.detalle(regs[2]["id"])
    assert baja["motivo"] == "Colada cargada dos veces"
    assert baja["antes"]["ajustes"][0]["kg"]["FeSi"] == 2.5   # lo borrado se puede reconstruir


def test_sin_pedido_el_cambio_queda_como_sistema(base):
    datos.append_history({"colada": "9/26", "objetivo": "N1"})
    assert _registros(entidad="sesion")[0]["actor_tipo"] == "sistema"


def test_guardar_sin_cambios_no_genera_registro(base):
    datos.save_alloys([{"nombre": "FeSi", "tipo": "Ferroaleación", "rendimiento": 0.9}])
    datos.save_alloys([{"nombre": "FeSi", "tipo": "Ferroaleación", "rendimiento": 0.9}])
    assert len(_registros(entidad="material")) == 1


def test_catalogo_registra_solo_el_material_que_cambio(base):
    datos.save_alloys([{"nombre": "FeSi", "rendimiento": 0.9}, {"nombre": "FeMn", "rendimiento": 0.8}])
    datos.save_alloys([{"nombre": "FeMn", "rendimiento": 0.8}, {"nombre": "FeSi", "rendimiento": 0.85}])  # reordena
    regs = _registros(entidad="material")
    assert [(r["clave"], r["accion"]) for r in regs] == [("FeSi", "alta"), ("FeMn", "alta"), ("FeSi", "modificacion")]


def test_informes_de_calidad_se_registran_por_informe(base):
    datos.save_quality_reports([{"id": "a", "colada": "5/26", "traccion": 400}, {"id": "b", "colada": "6/26"}])
    datos.save_quality_reports([{"id": "a", "colada": "5/26", "traccion": 420}])
    regs = _registros(entidad="informe_calidad")
    assert [(r["clave"], r["accion"]) for r in regs] == [("a", "alta"), ("b", "alta"), ("a", "modificacion"),
                                                         ("b", "baja")]
    assert regs[2]["colada"] == datos.normalize_colada_key("5/26")


def test_la_bitacora_no_se_puede_modificar_ni_borrar(base):
    with pytest.raises(sqlite3.DatabaseError):
        with db.transaccion() as c:
            c.execute("UPDATE bitacora SET actor='otro'")
    with pytest.raises(sqlite3.DatabaseError):
        with db.transaccion() as c:
            c.execute("DELETE FROM bitacora")


def test_una_alteracion_por_fuera_se_detecta(base):
    datos.append_history({"colada": "77/26", "objetivo": "N1"})
    assert trazabilidad.verificar_cadena()["integra"]
    con = sqlite3.connect(base)
    con.execute("DROP TRIGGER bitacora_no_se_modifica")
    objetivo = con.execute("SELECT id FROM bitacora WHERE entidad='sesion'").fetchone()[0]
    con.execute("UPDATE bitacora SET actor='alguien más' WHERE id=?", (objetivo,))
    con.commit()
    con.close()
    r = trazabilidad.verificar_cadena()
    assert not r["integra"] and r["registro_id"] == objetivo


def test_cucharas_del_kiosco_quedan_registradas(base):
    trazabilidad.fijar_actor(None, {"id": "kiosco-horno-1", "name": "Raspberry horno"})
    estado = datos.load_ladles_state()
    estado["current"] = {"colada": "88/26", "material_objetivo": "N1", "counts": {"N1": 1},
                         "events": {"N1": ["2026-11-26T10:00:00"]}}
    datos.save_ladles_state(estado)
    reg = _registros(entidad="cucharas_en_curso")[0]
    assert reg["actor"] == "Raspberry horno" and reg["actor_tipo"] == "dispositivo"
    assert reg["colada"] == datos.normalize_colada_key("88/26")


def test_el_actor_llega_desde_las_rutas(base):
    """Las dependencias de acceso fijan el actor en una contextvar; tiene que llegarle a la ruta (sync) que escribe."""
    pytest.importorskip("httpx")
    from fastapi import FastAPI, Depends, Header
    from fastapi.testclient import TestClient
    from modulos.ajuste import dispositivos as D

    app = FastAPI()

    @app.post("/escribir")
    def escribir(_: dict = Depends(D.require_acceso_editor)):
        datos.save_settings({"auto_save_hours": 5, "debug_mode": False})
        return {"ok": True}

    def usuario(x_test: str = Header(default="")):
        return {"id": 1, "usuario": "ana", "nombre": "Ana"} if x_test else None

    app.dependency_overrides[D.usuario_opcional] = usuario
    c = TestClient(app)
    r = c.post("/escribir", headers={"X-Test": "1", "X-Pie-Device-Id": "equipo-de-prueba-1",
                                     "X-Motivo": "cambio%20de%20turno"})
    assert r.status_code == 200
    reg = _registros(entidad="configuracion")[-1]
    assert reg["actor"] == "Ana (ana)" and reg["motivo"] == "cambio de turno"
    assert json.loads(json.dumps(trazabilidad.detalle(reg["id"])["despues"] or {})) is not None
