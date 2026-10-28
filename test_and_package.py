# -*- coding: utf-8 -*-
"""
Script de testes automatizados e empacotamento (.zip) do plugin GeoTrabalho.
"""

import os
import shutil
import sys
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from geotrabalho_qgis.core.municipality_mapper import MunicipalityMapper
from geotrabalho_qgis.core.ibge_api import IbgeMalhasClient
from geotrabalho_qgis.core.dardoweb_client import DardoWebClient, get_cube_config


def test_mapper():
    mapper = MunicipalityMapper.instance()
    # Florianópolis (Nome ou 6 dígitos)
    code, uf, nome = mapper.resolve(None, "SC", "FLORIANOPOLIS")
    assert code == "4205407" and uf == "SC", f"Erro Florianópolis: {code}, {uf}"

    # Formato misto do DardoWeb: 'SC-IRANI'
    code, uf, nome = mapper.resolve(None, None, "SC-IRANI")
    assert code == "4207809" and uf == "SC", f"Erro SC-IRANI: {code}, {uf}"

    # Código de 6 dígitos: '355030' (São Paulo) -> '3550308'
    code, uf, nome = mapper.resolve("355030")
    assert code == "3550308", f"Erro SP 6 dígitos: {code}"

    # Casos com hífen, apóstrofo e novas emancipações
    c_grao, _, _ = mapper.resolve(None, None, "SC-GRAO PARA")
    assert c_grao == "4206108", f"Erro Grão-Pará: {c_grao}"

    c_herval, _, _ = mapper.resolve(None, None, "SC-HERVAL D OESTE")
    assert c_herval == "4206702", f"Erro Herval d'Oeste: {c_herval}"

    c_santiago, _, _ = mapper.resolve(None, None, "SC-SANTIAGO DO SUL")
    assert c_santiago == "4215695", f"Erro Santiago do Sul: {c_santiago}"

    c_pescaria, _, _ = mapper.resolve(None, None, "SC-PESCARIA BRAVA")
    assert c_pescaria == "4212650", f"Erro Pescaria Brava: {c_pescaria}"

    print("[OK] MunicipalityMapper validado com sucesso (incluindo Grão-Pará, Herval d'Oeste e Santiago do Sul)!")


def test_year_cube_routing():
    # 2025 e 2024 devem apontar para o cubo corrente
    cfg_2025 = get_cube_config("rais_vinculos", "2025")
    assert "caged_rais_vinculo_id/" in cfg_2025["base_path"]

    cfg_2022 = get_cube_config("rais_vinculos", "2022")
    assert "caged_rais_vinculo_id/" in cfg_2022["base_path"]

    # 2021 e anos anteriores devem apontar para caged_rais_vinculo_id_2021
    cfg_2021 = get_cube_config("rais_vinculos", "2021")
    assert "caged_rais_vinculo_id_2021/" in cfg_2021["base_path"]

    cfg_2015 = get_cube_config("rais_vinculos", "2015")
    assert "caged_rais_vinculo_id_2021/" in cfg_2015["base_path"]

    print("[OK] Roteamento de cubos por ano (2025 corrente a séries históricas) validado com sucesso!")


def test_dardo_parser():
    client = DardoWebClient()
    sample_path = os.path.join(
        r"C:\Users\Luís Eduardo\.gemini\antigravity\brain\ae59d91f-31f2-496e-a739-a7b062cdd604\scratch",
        "result_sc_municipios.html"
    )
    if os.path.exists(sample_path):
        res = client.parse_local_file(sample_path)
        # Todos os 295 municípios de SC devem casar 100%
        assert len(res.records) >= 295, f"Esperado >= 295 municípios em SC, obtido {len(res.records)}"
        assert "SC" in res.detected_ufs
        abdon = next((r for r in res.records if r["CD_MUN_IBGE"] == "4200051"), None)
        assert abdon is not None, "Abdon Batista não encontrado"
        assert abdon["TOTAL_GERAL"] > 0
        assert abdon["PREDOMINANTE"] != ""
        print(f"[OK] DardoWeb Parser validado com {len(res.records)} municípios de SC (100% dos 295 polígonos)!")

        # Teste com filtro de atividade específica
        res_filtrado = client.parse_local_file(sample_path, filtro_atividade="pecuária, indústria")
        assert len(res_filtrado.records) >= 295
        assert res_filtrado.filter_applied != ""
        field_names = [f[0] for f in res_filtrado.field_specs]
        assert "VINC_FILTR" in field_names
        assert "PCT_FILTR" in field_names
        print(f"[OK] Filtragem por atividade validada! Campos gerados: {field_names[:8]}")
    else:
        print("[AVISO] Arquivo de amostra não encontrado para teste de parsing.")


def test_ibge_api():
    client = IbgeMalhasClient()
    path = client.fetch_geojson_for_ufs(["SC"], qualidade="minima")
    assert os.path.exists(path) and os.path.getsize(path) > 1000
    print(f"[OK] IbgeMalhasClient validado! Cache: {path}")


def package_and_sync():
    plugin_folder = os.path.join(PROJECT_ROOT, "geotrabalho_qgis")
    out_zip = os.path.join(PROJECT_ROOT, "geotrabalho_qgis.zip")

    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(plugin_folder):
            dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")]
            for file in files:
                if file.endswith((".pyc", ".pyo")) or file.startswith("."):
                    continue
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
                zf.write(abs_path, rel_path)

    print(f"[OK] Pacote ZIP gerado: {out_zip} ({os.path.getsize(out_zip):,} bytes)")

    # Sincroniza na pasta do QGIS 4 ativo
    qgis4_dir = os.path.expandvars(r"%APPDATA%\QGIS\QGIS4\profiles\default\python\plugins\geotrabalho_qgis")
    if os.path.exists(os.path.dirname(qgis4_dir)):
        if os.path.exists(qgis4_dir):
            shutil.rmtree(qgis4_dir)
        shutil.copytree(plugin_folder, qgis4_dir)
        print(f"[OK] Plugin sincronizado na pasta ativa do QGIS 4: {qgis4_dir}")

    from upload_to_qgis_hub import validate_qgis_zip
    ok, msgs = validate_qgis_zip(out_zip)
    for m in msgs:
        print(m)
    assert ok, "Falha na validação oficial do repositório de complementos do QGIS!"


if __name__ == "__main__":
    test_mapper()
    test_year_cube_routing()
    test_dardo_parser()
    test_ibge_api()
    package_and_sync()
