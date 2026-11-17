"""Valida o contrato entre workflows chamadores e reusable workflows.

Um `with:` com input inexistente no `workflow_call` do arquivo chamado não é
erro de YAML: o GitHub aceita o push e falha o run com `startup_failure`
 antes de criar qualquer job. Este teste pega esse tipo de erro localmente.
"""

import re
from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"
USO_LOCAL = re.compile(r"^\./\.github/workflows/(?P<arquivo>[\w.-]+\.yml)$")


def _carregar(caminho):
    with caminho.open(encoding="utf-8") as arquivo:
        return yaml.safe_load(arquivo)


def _inputs_declarados(documento):
    # PyYAML 1.1 interpreta a chave `on:` como o booleano True.
    gatilhos = documento.get("on") or documento.get(True) or {}
    chamada = gatilhos.get("workflow_call") or {}
    return set((chamada.get("inputs") or {}).keys())


def test_with_de_workflows_so_contem_inputs_declarados():
    erros = []

    for arquivo in sorted(WORKFLOWS_DIR.glob("*.yml")):
        documento = _carregar(arquivo)
        for nome_job, job in (documento.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue

            uso = USO_LOCAL.match(str(job.get("uses", "")).strip())
            if not uso:
                continue

            alvo = WORKFLOWS_DIR / uso.group("arquivo")
            if not alvo.exists():
                erros.append(
                    f"{arquivo.name}: job '{nome_job}' chama "
                    f"{alvo.name}, que nao existe"
                )
                continue

            declarados = _inputs_declarados(_carregar(alvo))
            passados = set((job.get("with") or {}).keys())
            for entrada in sorted(passados - declarados):
                erros.append(
                    f"{arquivo.name}: job '{nome_job}' passa "
                    f"'{entrada}' a {alvo.name}, que nao declara esse input"
                )

    assert not erros, "\n" + "\n".join(erros)
