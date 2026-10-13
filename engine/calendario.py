"""
engine/calendario.py — Calendário produtivo: feriados, férias coletivas e paradas programadas.
Lê config/calendario.yaml, mantém cache em memória e provê funções de cálculo de dias úteis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, List, Dict
import yaml

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DEFAULT_CALENDARIO_YAML = CONFIG_DIR / "calendario.yaml"


@dataclass
class Feriado:
    data: date
    descricao: str


@dataclass
class Parada:
    inicio: date
    fim: date
    descricao: str
    setores: str | list[str] = "TODOS"

    def aplica_ao_setor(self, setor: Optional[str] = None) -> bool:
        if not setor or self.setores == "TODOS":
            return True
        if isinstance(self.setores, list):
            s_norm = setor.strip().upper()
            return any(s.strip().upper() == s_norm for s in self.setores)
        return str(self.setores).strip().upper() == setor.strip().upper()


class CalendarioProdutivo:
    def __init__(
        self,
        feriados: Optional[Dict[date, str]] = None,
        paradas: Optional[List[Parada]] = None,
    ):
        self.feriados: Dict[date, str] = feriados or {}
        self.paradas: List[Parada] = paradas or []

    def eh_dia_util(self, d: date, setor: Optional[str] = None) -> bool:
        """Verifica se d é dia útil (segunda a sexta, sem feriado e fora de paradas aplicáveis)."""
        if d.weekday() >= 5:  # 5 = Sábado, 6 = Domingo
            return False
        if d in self.feriados:
            return False
        for p in self.paradas:
            if p.inicio <= d <= p.fim and p.aplica_ao_setor(setor):
                return False
        return True

    def avancar_dias_uteis(self, data_inicio: date, n_dias: int, setor: Optional[str] = None) -> date:
        """Avança N dias úteis a partir de data_inicio."""
        if n_dias <= 0:
            return data_inicio
        cur = data_inicio
        contados = 0
        while contados < n_dias:
            cur += timedelta(days=1)
            if self.eh_dia_util(cur, setor=setor):
                contados += 1
        return cur

    def recuar_dias_uteis(
        self,
        data_saida: date,
        n_dias: int,
        eh_ultima: bool = False,
        setor: Optional[str] = None,
    ) -> date:
        """
        Recua N dias úteis a partir de data_saida.
        Convenção Excia: a saída de uma fase é a entrada da seguinte.
        Se eh_ultima=True (Embalagem), o próprio dia da saída é o último dia trabalhado.
        """
        if n_dias <= 0:
            return data_saida
        cur = data_saida
        contados = 0
        if eh_ultima:
            if self.eh_dia_util(cur, setor=setor):
                contados = 1
                if n_dias == 1:
                    return cur
        while True:
            cur -= timedelta(days=1)
            if self.eh_dia_util(cur, setor=setor):
                contados += 1
                if contados >= n_dias:
                    return cur

    def contar_dias_uteis(self, data_inicio: date, data_fim: date, setor: Optional[str] = None) -> int:
        """Conta a quantidade de dias úteis entre data_inicio e data_fim (exclusivo inicio, inclusivo fim)."""
        if data_inicio >= data_fim:
            return 0
        cur = data_inicio
        dias = 0
        while cur < data_fim:
            cur += timedelta(days=1)
            if self.eh_dia_util(cur, setor=setor):
                dias += 1
        return dias

    def obter_paradas_no_intervalo(
        self,
        data_inicio: date,
        data_fim: date,
        setor: Optional[str] = None,
    ) -> list[Parada]:
        """Retorna as paradas que interceptam o intervalo [data_inicio, data_fim]."""
        d_min = min(data_inicio, data_fim)
        d_max = max(data_inicio, data_fim)
        resultado = []
        for p in self.paradas:
            if not (p.fim < d_min or p.inicio > d_max):
                if p.aplica_ao_setor(setor):
                    resultado.append(p)
        return resultado


_CALENDARIO_GLOBAL: Optional[CalendarioProdutivo] = None


def carregar_calendario(
    yaml_path: Optional[Path | str] = None,
    force_reload: bool = False,
) -> CalendarioProdutivo:
    """Carrega o calendário de YAML ou retorna o cache global."""
    global _CALENDARIO_GLOBAL
    caminho = Path(yaml_path) if yaml_path else DEFAULT_CALENDARIO_YAML

    if yaml_path is None and _CALENDARIO_GLOBAL is not None and not force_reload:
        return _CALENDARIO_GLOBAL

    if not caminho.exists():
        cal_vazio = CalendarioProdutivo()
        if yaml_path is None:
            _CALENDARIO_GLOBAL = cal_vazio
        return cal_vazio

    with open(caminho, encoding="utf-8") as f:
        dados = yaml.safe_load(f) or {}

    feriados_raw = dados.get("feriados", [])
    feriados: Dict[date, str] = {}
    for f in feriados_raw:
        try:
            d_str = str(f.get("data", "")).strip()
            desc = str(f.get("descricao", "Feriado")).strip()
            if d_str:
                d_obj = date.fromisoformat(d_str)
                feriados[d_obj] = desc
        except Exception:
            pass

    paradas_raw = dados.get("paradas", [])
    paradas: List[Parada] = []
    for p in paradas_raw:
        try:
            ini_str = str(p.get("inicio", "")).strip()
            fim_str = str(p.get("fim", "")).strip()
            desc = str(p.get("descricao", "Parada programada")).strip()
            setores = p.get("setores", "TODOS")
            if ini_str and fim_str:
                ini_obj = date.fromisoformat(ini_str)
                fim_obj = date.fromisoformat(fim_str)
                paradas.append(Parada(inicio=ini_obj, fim=fim_obj, descricao=desc, setores=setores))
        except Exception:
            pass

    cal = CalendarioProdutivo(feriados=feriados, paradas=paradas)
    if yaml_path is None:
        _CALENDARIO_GLOBAL = cal
    return cal


def salvar_calendario(dados_dict: dict, yaml_path: Optional[Path | str] = None) -> None:
    """Salva os dados do calendário em YAML e invalida o cache global."""
    global _CALENDARIO_GLOBAL
    caminho = Path(yaml_path) if yaml_path else DEFAULT_CALENDARIO_YAML
    caminho.parent.mkdir(parents=True, exist_ok=True)

    with open(caminho, "w", encoding="utf-8") as f:
        yaml.safe_dump(dados_dict, f, allow_unicode=True, sort_keys=False)

    if yaml_path is None:
        _CALENDARIO_GLOBAL = None
        carregar_calendario(force_reload=True)


# Funções convenientes a nível de módulo
def eh_dia_util(d: date, setor: Optional[str] = None) -> bool:
    return carregar_calendario().eh_dia_util(d, setor=setor)


def avancar_dias_uteis(d: date, n: int, setor: Optional[str] = None) -> date:
    return carregar_calendario().avancar_dias_uteis(d, n, setor=setor)


def recuar_dias_uteis(d: date, n: int, eh_ultima: bool = False, setor: Optional[str] = None) -> date:
    return carregar_calendario().recuar_dias_uteis(d, n, eh_ultima=eh_ultima, setor=setor)


def contar_dias_uteis(d_ini: date, d_fim: date, setor: Optional[str] = None) -> int:
    return carregar_calendario().contar_dias_uteis(d_ini, d_fim, setor=setor)


def obter_paradas_no_intervalo(d_ini: date, d_fim: date, setor: Optional[str] = None) -> list[Parada]:
    return carregar_calendario().obter_paradas_no_intervalo(d_ini, d_fim, setor=setor)
