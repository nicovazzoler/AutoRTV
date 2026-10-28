import hashlib

import pandas as pd
from sqlalchemy import create_engine, select

from app import db, pautas, semana

SIN = "Un recorrido por los clubes de jazz del país con grupos en vivo"


def test_campos_clave_segun_las_columnas_de_la_senal():
    epg = ["N", "Fecha", "Tit orig", "Tit princ", "Nro temp", "Nro cap", "Tit cap", "Tit ing", "Tit cap ing", "Genero"]
    assert semana.campos_clave(epg, "Tit orig") == ["Tit orig", "Tit princ", "Tit ing", "Nro temp", "Nro cap", "Tit cap",
                                                    "Tit cap ing"]
    assert semana.campos_clave(["Fecha", "Programa", "Capitulo", "Rating"], "Programa") == ["Programa", "Capitulo"]


def test_tit_orig_y_tit_princ_se_completan_entre_si():
    df = pd.DataFrame({"Tit orig": ["Memory Lane", None, "A"], "Tit princ": [None, "Koko Pop", "B"]})
    assert semana.completar_titulos(df, crear=False).values.tolist() == [
        ["Memory Lane", "Memory Lane"], ["Koko Pop", "Koko Pop"], ["A", "B"]]
    solo = pd.DataFrame({"Tit princ": ["Juke Box"]})
    assert semana.completar_titulos(solo, crear=False).columns.tolist() == ["Tit princ"]
    assert semana.completar_titulos(solo, crear=True).to_dict("records") == [{"Tit princ": "Juke Box", "Tit orig": "Juke Box"}]


def test_misma_sinopsis_en_dos_capitulos_es_argumento_de_programa():
    salida = pd.DataFrame({"Tit orig": ["Noches de Jazz", "Noches de Jazz", "Noches de Jazz", "Koko Pop"],
                           "Tit cap": ["Trío Sur", "Trío Sur", "Big Band", "Ep 1"],
                           "Sin larga": [SIN, SIN, "Otra sinopsis bien distinta de la anterior", SIN]})
    assert semana.sinopsis_repetidas(salida, [], "Tit orig", ["Tit cap"]) == {}  # el mismo capítulo dos veces

    base = [{"Tit orig": "Noches de Jazz", "Tit cap": "Cuarteto", "Sin larga": SIN.upper() + "!"}]
    motivos = semana.sinopsis_repetidas(salida, base, "Tit orig", ["Tit cap"])
    assert set(motivos) == {0, 1}  # Koko Pop es otro programa: no cuenta
    assert motivos[0].startswith("Sin larga: misma sinopsis que «Cuarteto»") and "argumento de programa" in motivos[0]


def test_hash_con_el_separador_nuevo_y_migracion_de_la_base(tmp_path):
    fila = {"t": "Memory Lane", "c": "OutKast"}
    assert pautas.hash_pauta(fila) == hashlib.sha1(b"memorylane///outkast").hexdigest()[:16]

    motor = create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    db.metadata.create_all(motor)
    import datetime as dt
    with motor.begin() as con:
        con.execute(db.pautas.insert().values(senal_id="canal", hash="viejo", crudo=fila, salida={"Programa": "Memory Lane"},
                                              estado="editada", usuario="ana", actualizado=dt.datetime(2026, 10, 1)))
    db.inicializar(motor)
    db.inicializar(motor)  # la segunda vez no hace nada
    with motor.connect() as con:
        (h,) = con.execute(select(db.pautas.c.hash)).scalars().all()
    assert h == pautas.hash_pauta(fila)
