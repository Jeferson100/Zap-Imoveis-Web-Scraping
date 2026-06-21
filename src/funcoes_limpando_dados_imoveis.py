
import unicodedata
from pathlib import Path
from datetime import datetime
import aiohttp
import asyncio
import re
import asyncio
import osmnx as ox
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
from concurrent.futures import ThreadPoolExecutor
import logging
import warnings
import time 
import requests
from tqdm import tqdm
import re
import unicodedata
from typing import Optional, Tuple
import unicodedata

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Função para pegar o arquivo mais recente

def arquivo_json_mais_recente(pasta_path, padrao_nome):
    pasta = Path(pasta_path)
    return max(pasta.glob(padrao_nome), key=lambda f: f.stem.split('_')[-1])
        
"""
class LimpaEndereco:
    def __init__(self, endereco):
        # Limpeza inicial: remove "Endereço Indisponível", quebras de linha e espaços extras
        self.raw_endereco = str(endereco)
        self.endereco = self._pre_limpeza(self.raw_endereco)

    def _pre_limpeza(self, texto: str) -> str:
        # Remove o aviso de indisponível e normaliza espaços/quebras de linha
        texto = re.sub(r'Endereço Indisponível', '', texto, flags=re.IGNORECASE)
        texto = texto.replace('\n', ' ').replace('\r', ' ')
        texto = re.sub(r'\s+', ' ', texto) # Transforma múltiplos espaços em um só
        return texto.strip().strip(',')

    def _normalizar(self, texto: str) -> str:
        if not texto: return ""
        return unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('utf-8').lower().strip()

    def explit_rua_bairro_numero(self):
        # Tenta identificar o padrão ZAP (muitos hifens) ou Chaves na Mão (muitas vírgulas)
        # Padronizamos para facilitar: trocamos " - " por ", " onde fizer sentido
        temp_end = self.endereco.replace(' - ', ', ')
        partes = [p.strip() for p in temp_end.split(',') if p.strip()]
        
        rua, numero, bairro = "", "s/n", ""

        if len(partes) >= 3:
            # Caso padrão: [Rua, Número, Bairro, Cidade/Estado]
            rua = partes[0]
            # Tenta verificar se a segunda parte é número
            if any(char.isdigit() for char in partes[1]):
                numero = partes[1]
                bairro = partes[2]
            else:
                # Se não for número, assume que é [Rua, Bairro, Cidade...]
                numero = "s/n"
                bairro = partes[1]
        
        elif len(partes) == 2:
            # Caso curto: [Bairro, Cidade/Estado] ou [Rua, Bairro]
            rua = ""
            bairro = partes[0]
        
        return rua, numero, bairro

    def limpar_rua(self) -> str:
        rua, _, _ = self.explit_rua_bairro_numero()
        if not rua: return "s/r"
        
        rua_lower = rua.lower()
        prefixos = ['rua ', 'avenida ', 'estrada ', 'travessa ', 'alameda ', 'av. ', 'r. ']
        for prefixo in prefixos:
            if rua_lower.startswith(prefixo):
                rua = rua_lower.replace(prefixo, '').strip()
                break
        else:
            rua = rua_lower
            
        return self._normalizar(rua)

    def limpar_bairro(self) -> str:
        _, _, bairro = self.explit_rua_bairro_numero()
        return self._normalizar(bairro) or "s/b"

    def extract_cidade_estado(self) -> tuple:
        # Pega a última parte do endereço original (sempre cidade/estado)
        # Ex: "São Paulo - SP" ou "Joinville/SC"
        partes = re.split(r'[,/-]', self.endereco)
        partes = [p.strip() for p in partes if p.strip()]
        
        if len(partes) >= 2:
            estado = partes[-1].upper()
            cidade = partes[-2]
        else:
            cidade = partes[0] if partes else "s/c"
            estado = "s/e"
            
        return self._normalizar(cidade), estado[:2] # Apenas a sigla do estado

    def endereco_completo(self) -> tuple:
        try:
            _, numero, _ = self.explit_rua_bairro_numero()
            rua_limpa = self.limpar_rua()
            bairro = self.limpar_bairro()
            cidade, estado = self.extract_cidade_estado()
            
            return (
                rua_limpa or "s/r", 
                numero or "s/n", 
                bairro or "s/b", 
                cidade or "s/c", 
                estado or "s/e"
            )
        except Exception:
            return ("error", "error", "error", "error", "error")

def limpa_endereco_apply(endereco):
    obj = LimpaEndereco(endereco)
    rua, numero, bairro, cidade, estado = obj.endereco_completo()
    return pd.Series({'rua': rua, 'numero': numero,  'bairro': bairro, 'cidade': cidade, 'estado': estado})"""
    

    
class LimpaEnderecoZap:
    def __init__(self, endereco, cidade=None, estado=None):
        self.raw_endereco = str(endereco)
        self.texto = re.sub(r'\s+', ' ', self.raw_endereco).strip()
        self.cidade = cidade
        self.estado = estado

    def _normalizar(self, texto: str) -> str:
        if not texto: return ""
        return unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('utf-8').lower().strip()

    def _limpar_prefixo_rua(self, nome_rua: str) -> str:
        """Remove 'Rua', 'Avenida', etc., para padronizar o nome."""
        if not nome_rua or nome_rua == "s/r":
            return "s/r"
        
        rua_lower = nome_rua.lower().strip()
        prefixos = ['rua ', 'avenida ', 'estrada ', 'travessa ', 'alameda ', 'av. ', 'r. ']
        
        for prefixo in prefixos:
            if rua_lower.startswith(prefixo):
                # Remove o prefixo e limpa espaços
                nome_rua = rua_lower.replace(prefixo, '', 1).strip()
                break
        else:
            nome_rua = rua_lower
            
        return self._normalizar(nome_rua)

    def extrair_dados(self):
        try:
            
            cidade = self.cidade or "s/c"
            estado = self.estado or "s/e"
            match_estado = re.search(r'-\s*([A-Z]{2})$', self.texto)
            if match_estado:
                estado = match_estado.group(1)
                temp_txt = self.texto[:match_estado.start()].strip().strip(',')
            else:
                temp_txt = self.texto

            partes_cidade = [p.strip() for p in temp_txt.split(',')]
            
            if len(partes_cidade) > 1:
                cidade = self._normalizar(partes_cidade[-1])
                resto = ",".join(partes_cidade[:-1])
            else:
                resto = partes_cidade[0]

            # 2. Rua, Número e Bairro
            rua_bruta, numero, bairro = "s/r", "s/n", "s/b"

            if ' - ' in resto:
                parte_rua_num, parte_bairro = resto.split(' - ', 1)
                bairro = self._normalizar(parte_bairro)
                
                if ',' in parte_rua_num:
                    r, n = parte_rua_num.split(',', 1)
                    rua_bruta = r.strip()
                    numero = n.strip()
                else:
                    rua_bruta = parte_rua_num.strip()
            else:
                # Se não tem hífen, assumimos que é o bairro (padrão Zap/OLX)
                bairro = self._normalizar(resto)

            # 3. Aplica a limpeza de prefixo na rua
            rua_limpa = self._limpar_prefixo_rua(rua_bruta)

            # 4. CEP
            match_cep = re.search(r'(\d{5}-?\d{3})', self.raw_endereco)
            cep = match_cep.group(1).replace('-', '') if match_cep else "s/cep"

            return {
                "rua": rua_limpa,
                "numero": numero,
                "bairro": bairro,
                "cidade": cidade,
                "estado": self._normalizar(estado),
                "cep": cep
            }

        except Exception:
            return {
                "rua": "error", "numero": "error", "bairro": "error", 
                "cidade": "error", "estado": "error", "cep": "error"
            }


# Teste com seus dados
def limpa_endereco_apply_zap(endereco, cidade=None, estado=None):
    obj = LimpaEnderecoZap(endereco, cidade, estado)
    # Retorna o dicionário diretamente
    dados = obj.extrair_dados() 
    return pd.Series(dados)


class TratadorEnderecoChavesNaMao:
    
    def __init__(self, cidade='joinville', estado='sc'):
        self.cidade = cidade
        self.estado = estado

        
    INDISPONIVEL = "Endereço Indisponível"

    def tratar(self, endereco_raw: str) -> dict:
        if not endereco_raw:
            return self._vazio()

        # Limpeza inicial e normalização de espaços
        texto = (
            endereco_raw
            .replace('\xa0', ' ')
            .replace('\n', ', ')
            .strip()
        )

        # Remove prefixos de títulos (ex: "502 João Costa... - ")
        texto = re.sub(r'^[\d\w\s/]+\s*-\s*', '', texto).strip()

        if self.INDISPONIVEL in texto:
            return self._tratar_indisponivel(texto)
        else:
            return self._tratar_completo(texto)

    def _normalizar(self, texto: str) -> str:
        """Remove acentos, converte para minúsculas e remove espaços extras."""
        if not texto or texto.lower() in ["none", "nan"]: 
            return ""
        return unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('utf-8').lower().strip()

    def _limpar_prefixo_rua(self, nome_rua: str) -> str:
        """Remove prefixos e normaliza o nome da rua."""
        if not nome_rua or nome_rua.lower() in ["s/r", "none", ""]:
            return "s/r"
        
        padrao_prefixos = r'^(rua|avenida|av\.|r\.|estrada|alameda|travessa|rodovia|servidao)\s+'
        rua_limpa = re.sub(padrao_prefixos, '', nome_rua.strip(), flags=re.IGNORECASE)
        
        # Aqui aplicamos a normalização no nome da rua
        return self._normalizar(rua_limpa) or "s/r"

    def _tratar_indisponivel(self, texto: str) -> dict:
        texto_limpo = re.sub(r'Endereço Indisponível\s*,?\s*', '', texto).strip()
        partes = [p.strip() for p in texto_limpo.split(',') if p.strip()]

        bairro, cidade, estado = self._extrair_cidade_estado(partes)

        return {
            'rua':    's/r',
            'numero': 's/n',
            'bairro': self._normalizar(bairro) or 's/b',
            'cidade': self._normalizar(cidade) or self.cidade,
            'estado': self._normalizar(estado) or self.estado,
        }

    def _tratar_completo(self, texto: str) -> dict:
        partes = [p.strip() for p in texto.split(',')]

        # Extração de âncoras (de trás para frente)
        bairro_extraido, cidade, estado = self._extrair_cidade_estado(partes)
        
        idx_cidade = self._achar_idx_cidade(partes)
        restantes = partes[:idx_cidade]

        rua_raw = "s/r"
        numero  = "s/n"
        bairro  = bairro_extraido or "s/b"

        if restantes:
            rua_raw = restantes[0]
            if len(restantes) >= 2:
                # Captura KM, Lote, Numero, Apt e normaliza
                numero = self._normalizar(", ".join(restantes[1:]))

        # Limpeza de ruídos (anúncios de teste tipo XXXXX)
        if bairro and 'xxx' in bairro.lower():
            bairro = "s/b"
        if rua_raw and 'xxx' in rua_raw.lower():
            rua_raw = "s/r"

        return {
            'rua':    self._limpar_prefixo_rua(rua_raw),
            'numero': numero if numero else "s/n",
            'bairro': self._normalizar(bairro) or "s/b",
            'cidade': self._normalizar(cidade) or self.cidade,
            'estado': self._normalizar(estado) or self.estado,
        }

    def _extrair_cidade_estado(self, partes: list) -> tuple:
        cidade, estado, bairro = None, None, None

        for i, parte in enumerate(partes):
            match = re.search(r'(.+?)\s*/\s*([A-Z]{2})$', parte, re.IGNORECASE)
            if match:
                cidade = match.group(1).strip()
                estado = match.group(2).strip()
                if i > 0:
                    bairro = partes[i - 1].strip()
                break

        return bairro, cidade, estado

    def _achar_idx_cidade(self, partes: list) -> int:
        for i, parte in enumerate(partes):
            if re.search(r'.+/[A-Z]{2}$', parte, re.IGNORECASE):
                return max(0, i - 1)
        return len(partes)

    def _vazio(self) -> dict:
        return {
            'rua':    's/r',
            'numero': 's/n',
            'bairro': 's/b',
            'cidade': self.cidade,
            'estado': self.estado,
        }


def limpa_endereco_apply_chave_mao(endereco, cidade='joinville', estado='sc'):
    tratador = TratadorEnderecoChavesNaMao(cidade, estado)
    dados = tratador.tratar(endereco)
    return pd.Series(dados)


class TratadorEnderecoOLX:
    def __init__(self, cidade=None, estado=None):
        self.cidade = self._normalizar(cidade)
        self.estado = self._normalizar(estado)

    def _normalizar(self, texto: str) -> str:
        if not texto or texto.lower() in ["none", "nan"]: 
            return ""
        return unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('utf-8').lower().strip()

    def _limpar_prefixo_rua(self, nome_rua: str) -> str:
        if not nome_rua or nome_rua.lower() in ["s/r", ""]:
            return "s/r"
        
        padrao_prefixos = r'^(rua|avenida|av\.|r\.|estrada|alameda|travessa|rodovia|servidao)\s+'
        rua_limpa = re.sub(padrao_prefixos, '', nome_rua.strip(), flags=re.IGNORECASE)
        
        return self._normalizar(rua_limpa) or "s/r"

    """def tratar(self, endereco_raw: str) -> dict:
        if not endereco_raw:
            return self._vazio()

        # Split por vírgula e limpeza de espaços
        partes = [p.strip() for p in endereco_raw.split(',') if p.strip()]
        
        rua = "s/r"
        bairro = "s/b"
        cep = "s/c"

        try:
            # 1. Extrair CEP (Sempre a última parte se tiver 8 dígitos)
            if partes and partes[-1].isdigit() and len(partes[-1]) == 8:
                cep = partes.pop(-1)

            # 2. Identificar Estado e Cidade (Penúltima e antepenúltima parte)
            # Formato: [..., Bairro, Cidade, Estado]
            if len(partes) >= 2:
                # Removemos Estado e Cidade da lista para sobrar Rua/Bairro
                partes.pop(-1) # Remove SC
                partes.pop(-1) # Remove Joinville

            # 3. O que sobrou?
            if len(partes) >= 2:
                # Ex: ['Rua Dona Cezarina', 'Santa Catarina'] ou ['Rua X', 'Pirabeiraba (Pirabeiraba)']
                rua = partes[0]
                # O bairro é a última parte que sobrou antes da cidade
                bairro = partes[-1]
                # Limpeza de parênteses extras comuns na OLX (ex: Pirabeiraba (Pirabeiraba))
                bairro = re.sub(r'\s*\(.*\)', '', bairro)
            elif len(partes) == 1:
                # Ex: ['Glória']
                bairro = partes[0]

            return {
                'rua':    self._limpar_prefixo_rua(rua),
                'numero': 's/n', # OLX raramente fornece número nesta string
                'bairro': self._normalizar(bairro) or "s/b",
                'cidade': self._normalizar(self.cidade) or "s/c",
                'estado': self._normalizar(self.estado) or "s/e",
                'cep':    cep
            }
            
            

        except Exception:
            return self._vazio()
    
        """
    
    def tratar(self, endereco_raw: str) -> dict:
        if not endereco_raw:
            return self._vazio()

        # Split por vírgula e limpeza de espaços
        partes = [p.strip() for p in endereco_raw.split(',') if p.strip()]
        
        rua = "s/r"
        bairro = "s/b"
        cidade = "s/c"
        estado = "s/e"
        cep = "s/c"

        try:
            # 1. Extrair CEP (sempre o último se tiver 8 dígitos)
            if partes and partes[-1].isdigit() and len(partes[-1]) == 8:
                cep = partes.pop(-1)

            # 2. Extrair Estado (agora é o último após tirar o CEP)
            if partes and len(partes[-1]) == 2: # Ex: SC, PR
                estado = partes.pop(-1)

            # 3. Extrair Cidade (o que sobrou por último agora)
            if partes:
                cidade = partes.pop(-1)

            # 4. O que sobrou na lista agora é [Rua, Bairro] ou apenas [Bairro]
            if len(partes) >= 2:
                # Caso: ['Rua 904', 'Centro']
                rua = partes[0]
                bairro = partes[-1]
            elif len(partes) == 1:
                # Caso: ['Centro']
                bairro = partes[0]
                rua = "s/r"

            # Limpeza de parênteses extras no bairro (comum na OLX)
            bairro = re.sub(r'\s*\(.*\)', '', bairro)

            return {
                'rua':    self._limpar_prefixo_rua(rua),
                'numero': 's/n',
                'bairro': self._normalizar(bairro) or "s/b",
                'cidade': self._normalizar(cidade) or "s/c",
                'estado': self._normalizar(estado) or "s/e",
                'cep':    cep
            }
        except Exception as e:
            logger.error(f"Erro ao tratar endereço '{endereco_raw}': {e}")
            return self._vazio()

    def _vazio(self) -> dict:
        return {
            'rua':    's/r',
            'numero': 's/n',
            'bairro': 's/b',
            'cidade': self._normalizar(self.cidade) or "s/c",
            'estado': self._normalizar(self.estado) or "s/e",
            'cep':    's/c'
        }
def limpa_endereco_apply_olx(endereco, cidade='joinville', estado='sc'):
    tratador = TratadorEnderecoOLX(cidade, estado)
    dados = tratador.tratar(endereco)
    return pd.Series(dados)


def pirabeiraba_dona_francisca(bairro):
    if 'pirabeiraba' in bairro.lower() or 'dona francisca' in bairro.lower():
        return 'pirabeiraba'
    return bairro

"""def limpar_metragem(dados) -> float:
    try:
        if not dados or not isinstance(dados, str):
            return 0.0
    
        valor = dados.replace('m²', '').strip()
    
        if valor == '':
            return 0.0
        
        return float(valor)    
    except Exception as e:
        logger.warning("Erro ao limpar metragem: %s, dados no formato %s", e,dados)
        return 0.0"""


def limpar_metragem(dados) -> float:
    try:
        if not dados:
            return 0.0
            
        # Garante que seja string e remove 'm²', espaços e unidades extras
        valor = str(dados).lower().replace('m²', '').replace('m2', '').strip()

        if valor == '' or valor == 'None':
            return 0.0

        # Lógica para o padrão brasileiro/europeu:
        # 1. Se tiver vírgula, o ponto é milhar (1.000,50)
        if ',' in valor:
            valor = valor.replace('.', '')    # Remove milhar
            valor = valor.replace(',', '.')    # Transforma decimal em ponto
        else:
            # 2. Se tiver apenas pontos (10.000.000), remove todos 
            # para o Python entender como um número inteiro/float limpo
            valor = valor.replace('.', '')

        # Remove qualquer caractere que não seja número ou o ponto decimal final
        valor = re.sub(r'[^\d.]', '', valor)

        return float(valor) if valor else 0.0
        
    except Exception as e:
        logger.warning("Erro ao limpar metragem: %s, dados originais: %s", e, dados)
        return 0.0

"""def limpar_valor_venda(valor_venda) -> float:
    try:
        valor_venda_limpo = valor_venda.replace('R$', '').replace('.', '').strip()
    except Exception as e:
        logger.warning("Erro ao limpar valor venda: %s, dados no formato %s", e,valor_venda)
        return np.nan
    return float(valor_venda_limpo)"""
    
"""def limpar_valor_venda(valor_venda):
    try:
        valor_venda_limpo = str(valor_venda)
        
        # Remove letras, $, \xa0 e espaços — deixa só números, ponto e vírgula
        valor_venda_limpo = re.sub(r'[a-zA-ZÀ-ú\$\s\xa0]+', '', valor_venda_limpo)
        
        # Converte formato brasileiro: 1.380.000 → 1380000
        valor_venda_limpo = valor_venda_limpo.replace('.', '').replace(',', '.').strip()

        if valor_venda_limpo in ('', 'nan', 'None'):
            return np.nan

        return float(valor_venda_limpo)

    except Exception as e:
        logger.warning("Erro ao limpar valor venda: %s, dados no formato %s", e, valor_venda)
        return np.nan"""

def limpar_valor_venda(valor_venda):
    if pd.isna(valor_venda) or valor_venda == '':
        return np.nan
        
    try:
        # 1. Converte para string e limpa sujeira básica
        v = str(valor_venda).strip()
        v = re.sub(r'[a-zA-ZÀ-ú\$\s\xa0]+', '', v)

        # 2. Se houver vírgula e ponto (ex: 1.250,00), remove o ponto e troca a vírgula
        if ',' in v and '.' in v:
            v = v.replace('.', '').replace(',', '.')
        # 3. Se houver apenas vírgula (ex: 250,00), troca por ponto
        elif ',' in v:
            v = v.replace(',', '.')
        # 4. CASO OLX: Se houver apenas um ponto e ele estiver na posição de milhar
        # Ex: 249.000 -> queremos 249000, não 249.0
        elif '.' in v:
            partes = v.split('.')
            # Se a última parte tem 3 dígitos, o ponto era de milhar
            if len(partes[-1]) == 3:
                v = v.replace('.', '')
        
        if v in ('', 'nan', 'None'):
            return np.nan

        return float(v)

    except Exception as e:
        logger.warning("Erro ao limpar valor venda: %s", valor_venda)
        return np.nan
    

def limpar_banheiros(valor):
    valor = str(valor).strip()
    if valor in ('--', '', 'nan', 'None'):
        return 0
    if '-' in valor:
        partes = [p.strip() for p in valor.split('-') if p.strip().isdigit()]
        if partes:
            return int(min(partes, key=int))
        return 0
    try:
        return int(float(valor))
    except:
        return 0

def limpar_vagas(valor):
    valor = str(valor).strip()
    if valor in ('--', '', 'nan', 'None'):
        return 0
    if '-' in valor:
        partes = [p.strip() for p in valor.split('-') if p.strip().isdigit()]
        if partes:
            return int(min(partes, key=int))
        return 0
    try:
        return int(float(valor))
    except:
        return 0

"""def limpar_valor_condominio(valor_condominio) -> float:
    if not valor_condominio or not isinstance(valor_condominio, str):
        return None
    valor_lower = valor_condominio.lower().strip()
    if valor_condominio == "N/A" or valor_lower == "isento":
        return 0.0
    if valor_lower == "não informado":
        return np.nan
    valor_limpo = valor_condominio.replace('R$', '').replace('.', '').strip()
    if "/mês" in valor_limpo:
        valor_limpo = valor_limpo.replace('/mês', '').strip()
    try:
        return float(valor_limpo)
    except ValueError:
        return np.nan"""

def limpar_valor_condominio(valor_condominio) -> float:
    if not valor_condominio or not isinstance(valor_condominio, str):
        return None
    
    valor_lower = valor_condominio.lower().strip()
    
    # Tratamentos de texto fixo
    if valor_lower in ["n/a", "isento", "r$ 0", "0"]:
        return 0.0
    if "nao informado" in valor_lower or "não informado" in valor_lower:
        return np.nan

    try:
        # 1. Remove pontos de milhar para não confundir o float (ex: 2.176 -> 2176)
        valor_limpo = valor_lower.replace('.', '')
        
        # 2. Regex "Sniper": Busca apenas a parte numérica que faz parte do valor.
        # Explicação: busca números, seguidos ou não de vírgula (centavos)
        # Ignora o que vem depois de "/ mês", "mês1", etc.
        match = re.search(r'r\$\s?([\d,]+)', valor_limpo)
        
        if match:
            # Pega o grupo capturado (ex: "2176" ou "750")
            num_str = match.group(1).replace(',', '.') # Troca vírgula decimal por ponto se houver
            return float(num_str)
        
        # Fallback caso não tenha R$: tenta pegar qualquer número sequencial no início
        match_fallback = re.search(r'^(\d+)', valor_limpo)
        if match_fallback:
            return float(match_fallback.group(1))

    except (ValueError, AttributeError):
        return np.nan
        
    return np.nan

def limpar_valor_iptu(valor_iptu) -> float:
    if not valor_iptu or not isinstance(valor_iptu, str):
        return np.nan
    if valor_iptu.lower().strip() == "não informado":
        return np.nan
    elif valor_iptu.lower().strip() == "isento":
        return 0.0
    valor_iptu_limpo = valor_iptu.replace('R$', '').replace('.', '').strip()
    if "/mês" in valor_iptu_limpo:
        valor_iptu_limpo = valor_iptu_limpo.replace('/mês', '').strip()
    try:
        return float(valor_iptu_limpo)
    except ValueError:
        return np.nan

# Funções para data de publicação
MESES = {
    'janeiro': '01', 'fevereiro': '02', 'marco': '03',
    'abril': '04', 'maio': '05', 'junho': '06',
    'julho': '07', 'agosto': '08', 'setembro': '09',
    'outubro': '10', 'novembro': '11', 'dezembro': '12'
}

def limpar_data_publicacao(data_publicacao) -> str:
    try:
        data_publicacao_limpa = data_publicacao.split(',')[0].strip().split('Anúncio criado em')[1].strip()
    except Exception as e: # ✅ 
        logger.warning("Erro de nome %s", e)
        return ''
    return unicodedata.normalize('NFD', data_publicacao_limpa).encode('ascii', 'ignore').decode('utf-8')

def converter_para_data(data_publicacao) -> str:
    try:
        data_limpa = limpar_data_publicacao(data_publicacao)
        partes = data_limpa.split(' de ')
        dia = partes[0].strip().zfill(2)
        mes = MESES[partes[1].strip()]
        ano = partes[2].strip()
        return f"{dia}/{mes}/{ano}"
    except (KeyError, IndexError, AttributeError):
        return None
"""
MESES = {
    'janeiro': '01', 'fevereiro': '02', 'marco': '03',
    'abril': '04', 'maio': '05', 'junho': '06',
    'julho': '07', 'agosto': '08', 'setembro': '09',
    'outubro': '10', 'novembro': '11', 'dezembro': '12'
}

def limpar_data_publicacao(data_publicacao) -> str:
    if not data_publicacao:
        return ''
    try:
        # Se contiver "Anúncio criado em", extraímos o que vem depois
        if 'Anúncio criado em' in data_publicacao:
            data_limpa = data_publicacao.split(',')[0].strip().split('Anúncio criado em')[1].strip()
        else:
            # Caso contrário, pegamos a string bruta (como no novo formato)
            data_limpa = data_publicacao.strip()
            
        return unicodedata.normalize('NFD', data_limpa).encode('ascii', 'ignore').decode('utf-8').lower()
    except Exception as e:
        return ''

def converter_para_data(data_publicacao) -> str:
    try:
        data_limpa = limpar_data_publicacao(data_publicacao)
        if not data_limpa:
            return ''

        # --- NOVO FORMATO: 25/03 às 23:09 ---
        if '/' in data_limpa and 'as' in data_limpa:
            # Pega apenas o início (DD/MM)
            match = re.search(r'(\d{2}/\d{2})', data_limpa)
            if match:
                dd_mm = match.group(1)
                ano_atual = datetime.now().year
                return f"{dd_mm}/{ano_atual}"

        # --- FORMATO ANTIGO: 10 de janeiro de 2024 ---
        partes = data_limpa.split(' de ')
        if len(partes) >= 3:
            dia = partes[0].strip().zfill(2)
            mes = MESES.get(partes[1].strip(), '01')
            ano = partes[2].strip()
            return f"{dia}/{mes}/{ano}"
            
        return ''
    except (KeyError, IndexError, AttributeError):
        return ''
"""
"""def limpar_quartos(valor):
    try:
        if isinstance(valor, str):
            if valor == '--':
                return 0
            return int(valor)
        elif pd.isna(valor):
            return np.nan
        else:
            return int(valor)
    except Exception as e:
        logger.warning("Erro ao limpar banheiros %s", e)
        return np.nan"""

def limpar_quartos(valor):
    """
    Recebe valores como '5 Ou Mais', '2', '--', '10+' e devolve inteiro ou np.nan.
    """
    try:
        # 1. Trata nulos logo de cara
        if pd.isna(valor) or valor == '--' or str(valor).strip() == '':
            return 0  # Ou np.nan, dependendo da sua preferência para Ciência de Dados

        # 2. Converte para string e limpa espaços
        valor_str = str(valor).strip()

        # 3. Usa Regex para encontrar o primeiro número na string
        # Ex: "5 Ou Mais" -> "5" | "2 quartos" -> "2" | "10+" -> "10"
        match = re.search(r'\d+', valor_str)
        
        if match:
            return int(match.group())
        
        return 0 # Se não achou nenhum número na string

    except Exception as e:
        logger.warning("Erro ao limpar quartos/banheiros: %s (Valor: %s)", e, valor)
        return np.nan


def transformar_banheiros(valor):
    return int(valor) if valor != '--' else 0

def transformar_quartos(valor):
    return int(valor) if valor != '--' else 0

def transformar_vagas(valor):
    return int(valor) if valor != '--' else 0

# Função para classificar tipo de imóvel
"""def classificar_tipo_imovel(descricao) -> str:
    if not isinstance(descricao, str):
        return 'outros'
    descricao_lower = descricao.lower()
    TIPOS = {
        'apartamento': ['apartamento', 'cobertura', 'flat', 'kitnet', 'studio'],
        'casa':        ['casa com', 'casa de condomínio', 'casa comercial', 'sobrado', 'casa'],
        'terreno':     ['terreno', 'lote'],
        'comercial':   ['conjunto comercial', 'sala comercial', 'loja', 'ponto comercial', 'casa comercial', 'prédio comercial', 'salas comercial'],
        'galpao':      ['galpão', 'depósito', 'armazém'],
        'rural':       ['fazenda', 'sítio', 'chácara'],
        'predio_inteiro': ['hotel', 'motel', 'pousada','prédio inteiro'],
    }
    for tipo, palavras in TIPOS.items():
        if any(palavra in descricao_lower for palavra in palavras):
            return tipo
    return 'outros'"""

def classificar_tipo_imovel(descricao) -> str:
    if not isinstance(descricao, str):
        return 'outros'
    
    descricao_lower = descricao.lower()
    
    # Ordem importa: tipos mais específicos primeiro
    TIPOS = {
        'apartamento': [
            'apartamento', 'apto', 'ap ', 'ap.', 'apartarmento', 'aparamento',
            'cobertura', 'flat', 'kitnet', 'studio', 'penthouse', 'loft',
            'residenz', 'residence', 'tower', 'apartments', 'edifício', 'ed.',
            'mansões suspensas', 'soft' # Comum em 'Apto Soft'
        ],
        'casa': [
            'casa', 'sobrado', 'geminado', 'germinado', 'triplex', 'duplex', 
            'residência', 'villa', 'mansion', 'mansão', 'casa de condomínio',
            'casa comercial', 'casa de vila', 'residencia'
        ],
        'terreno': [
            'terreno', 'lote', 'loteamento', 'área urbana', 'propriedade exclusiva'
        ],
        'comercial': [
            'sala comercial', 'loja', 'ponto comercial', 'prédio comercial', 
            'conjunto comercial', 'escritório', 'consultório', 'comercial/residencial'
        ],
        'galpao': [
            'galpão', 'depósito', 'armazém', 'pavilhão', 'barracão'
        ],
        'rural': [
            'fazenda', 'sítio', 'chácara', 'área rural', 'haras'
        ],
        'predio_inteiro': [
            'hotel', 'motel', 'pousada', 'prédio inteiro', 'edifício inteiro'
        ],
    }

    # 1. Busca direta pelas palavras-chave
    for tipo, palavras in TIPOS.items():
        if any(palavra in descricao_lower for palavra in palavras):
            return tipo

    # 2. Heurística extra para títulos genéricos (Ex: "Imóvel para venda possui 91m² com 2 quartos")
    # Geralmente, se tem quartos e metragem baixa em títulos genéricos, é 'casa' ou 'apartamento'.
    # Como padrão de segurança para o seu modelo, se contiver 'quartos' ou 'suítes' e não foi pego antes:
    if any(p in descricao_lower for p in ['quarto', 'suíte', 'dormitório']):
        return 'apartamento' # Ou 'casa', mas apartamento é estatisticamente mais comum em anúncios genéricos

    return 'outros'

def reclassificar_outros(descricao) -> str:
    try:
        i_split = descricao.split(',')[0].strip().lower()
        resultado = classificar_tipo_imovel(i_split)
        return resultado
    except:
        return 'outros'

async def extrair_coords_url(link_maps: str) -> tuple:
    """Tenta extrair lat/lng direto da URL do Maps."""
    if not link_maps or not isinstance(link_maps, str):
        return None, None
    try:
        url = str(link_maps).replace('%2C', ',').replace('%2c', ',')

        # 1. @lat,lng (mais comum): .../@-26.1234,-48.5678,17z/
        match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if match:
            return float(match.group(1)), float(match.group(2))

        # 2. q=lat,lng: ...?q=-26.1234,-48.5678
        match = re.search(r'[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if match:
            return float(match.group(1)), float(match.group(2))

        # 3. !3d!4d: ...!3d-26.1234!4d-48.5678
        m3 = re.search(r'!3d(-?\d+\.\d+)', url)
        m4 = re.search(r'!4d(-?\d+\.\d+)', url)
        if m3 and m4:
            return float(m3.group(1)), float(m4.group(1))
    except Exception:
        pass
    return None, None
    

class TokenBucket:
    """Garante no máximo 1 request a cada `intervalo` segundos."""
    def __init__(self, intervalo=1.0):
        self.intervalo = intervalo
        self._ultimo = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            agora = time.monotonic()
            espera = self.intervalo - (agora - self._ultimo)
            if espera > 0:
                await asyncio.sleep(espera)
            self._ultimo = time.monotonic()


_NOMINATIM_BUCKET = TokenBucket(1.0)
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {
    'User-Agent': 'analise_imoveis_v1_jeferson (jefer-silva2018@hotmail.com)'
}


async def _geocode_nominatim(session, query):
    params = {'q': query, 'format': 'json', 'limit': 1}
    await _NOMINATIM_BUCKET.acquire()
    for tentativa in range(4):
        try:
            async with session.get(_NOMINATIM_URL, params=params,
                                   headers=_NOMINATIM_HEADERS) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        return float(data[0]['lat']), float(data[0]['lon'])
                    return None, None
                if resp.status in (429, 503):
                    wait = 2 ** tentativa * 2
                    logger.warning("⏳ Nominatim %s — aguardando %ds (tentativa %d/4)",
                                   resp.status, wait, tentativa + 1)
                    await asyncio.sleep(wait)
                    continue
                logger.error("❌ Nominatim HTTP %s", resp.status)
                return None, None
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            logger.warning("⏱️ Nominatim erro: %s", e)
            await asyncio.sleep(2 ** tentativa)
            continue
    return None, None


async def geocodificar_endereco(session, row, cidade='Joinville', estado='SC', pais='Brasil'):
    """Geocodifica via Nominatim com token bucket (1 req/s).
    Retorna (lat, lon, nivel) onde nivel ∈ {'address', 'bairro', 'city'}.
    city-level nunca é retornado como coordenada — quem chama decide o fallback."""
    cep = str(row.get('cep', '')).strip()
    rua = str(row.get('rua', '')).strip()
    bairro = str(row.get('bairro', '')).strip()
    numero = str(row.get('numero', '')).strip()

    rua = '' if rua.lower() in ('s/r', '', 'nan') else rua
    bairro = '' if bairro.lower() in ('', 'nan', 'none') else bairro
    numero = '' if numero.lower() in ('s/n', '', 'nan') else numero

    queries_nivel = []
    if rua and numero:
        queries_nivel.append((f"{numero} {rua}, {bairro}, {cidade}, {estado}, {pais}", 'address'))
    if rua:
        queries_nivel.append((f"{rua}, {bairro}, {cidade}, {estado}, {pais}", 'address'))
    cep_clean = ''.join(filter(str.isdigit, cep))
    if len(cep_clean) == 8:
        queries_nivel.append((f"{cep_clean[:5]}-{cep_clean[5:]}, {pais}", 'address'))
    if bairro:
        queries_nivel.append((f"{bairro}, {cidade}, {estado}, {pais}", 'bairro'))

    # Se nao tem endereco nem bairro, retorna city-level para quem chama decidir
    if not queries_nivel:
        return None, None, 'city'

    for q, nivel in queries_nivel:
        lat, lon = await _geocode_nominatim(session, q)
        if lat:
            logger.info("✅ Nominatim (%s): %s", nivel, q[:60])
            return lat, lon, nivel
        #await asyncio.sleep(2.5)

    return None, None, 'city'

_CACHE_DIR = Path(__file__).parent.parent / 'codigos_rodando' / 'cache' / 'geocode_cache'


def _carregar_cache_geocode(cidade, estado, cache_path=None):
    if cache_path:
        path = Path(cache_path)
    else:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _CACHE_DIR / f"{cidade.lower()}_{estado.lower()}_geocode.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        cache = {}
        for _, r in df.iterrows():
            level = r.get('level', 'address')
            cache[r['chave']] = (r['lat'], r['lng'], level)
        return cache
    return {}


def _salvar_cache_geocode(cache, cidade, estado, cache_path=None):
    if cache_path:
        path = Path(cache_path)
    else:
        path = _CACHE_DIR / f"{cidade.lower()}_{estado.lower()}_geocode.parquet"
    df = pd.DataFrame([(k, v[0], v[1], v[2]) for k, v in cache.items()],
                      columns=['chave', 'lat', 'lng', 'level'])
    df.to_parquet(path, index=False)


async def preencher_coordenadas(session: aiohttp.ClientSession, row: pd.Series, semaforo: asyncio.Semaphore = None,
                                cidade: str = 'Joinville', estado: str = 'SC', pais: str = 'Brasil',
                                cache: dict = None, cache_atualizado: list = None,
                                bairro_centroides: dict = None) -> dict:
    if semaforo:
        async with semaforo:
            return await _preencher_coordenadas_inner(session, row, cidade, estado, pais,
                                                       cache, cache_atualizado, bairro_centroides)
    return await _preencher_coordenadas_inner(session, row, cidade, estado, pais,
                                               cache, cache_atualizado, bairro_centroides)


async def _preencher_coordenadas_inner(session, row, cidade, estado, pais,
                                        cache, cache_atualizado, bairro_centroides):
    idx = row.name

    if pd.notna(row['lat']) and pd.notna(row['lng']):
        return {'idx': idx, 'lat': row['lat'], 'lng': row['lng']}

    def _norm(val):
        v = str(val).strip().lower()
        return '' if v in ('', 'nan', 'none', 's/r', 's/n', 'null') else str(val).strip()

    rua = _norm(row.get('rua', ''))
    bairro = _norm(row.get('bairro', ''))
    chave = f"{rua}|{bairro}|{cidade}|{estado}"

    if cache and chave in cache:
        lat, lng, level = cache[chave]
        if level != 'city':
            return {'idx': idx, 'lat': lat, 'lng': lng}

    try:
        lat, lng = await extrair_coords_url(row['link_maps'])
        if lat and lng:
            return {'idx': idx, 'lat': lat, 'lng': lng}
    except Exception:
        pass

    lat, lng, level = await geocodificar_endereco(session, row, cidade, estado, pais)

    if bairro_centroides and (lat is None or level == 'city'):
        if bairro in bairro_centroides:
            c = bairro_centroides[bairro]
            lat, lng = c['lat'], c['lng']
            level = 'bairro'
            logger.info("📍 Centroid bairro %s: (%.4f, %.4f)", bairro, lat, lng)

    if lat is not None and level == 'city':
        return {'idx': idx, 'lat': None, 'lng': None}

    if lat is not None and cache is not None:
        cache[chave] = (lat, lng, level)
        if cache_atualizado:
            cache_atualizado[0] = True

    return {'idx': idx, 'lat': lat, 'lng': lng}

def _calcular_centroides(df):
    """Calcula centroides de bairro a partir de coordenadas já existentes."""
    existentes = df.dropna(subset=['lat', 'lng'])
    if existentes.empty:
        return {}
    return existentes.groupby('bairro')[['lat', 'lng']].mean().to_dict('index')


def _atualizar_centroides(centroides, novos_resultados):
    """Atualiza centroides com novas coordenadas descobertas (media movel)."""
    for r in novos_resultados:
        lat, lng = r.get('lat'), r.get('lng')
        bairro = r.get('bairro', '')
        if lat is not None and lng is not None and bairro:
            if bairro not in centroides:
                centroides[bairro] = {'lat': lat, 'lng': lng, '_count': 1}
            else:
                c = centroides[bairro]
                count = c.get('_count', 1)
                c['lat'] = (c['lat'] * count + lat) / (count + 1)
                c['lng'] = (c['lng'] * count + lng) / (count + 1)
                c['_count'] = count + 1


async def preencher_todas_coordenadas(df: pd.DataFrame, batch_size: int = None, cidade: str = 'Joinville', estado: str = 'SC', pais: str = 'Brasil', cache_path: str = None, req_por_segundo: float = None) -> Tuple[pd.DataFrame, bool]:
    import os
    if req_por_segundo is None:
        req_por_segundo = 1.0 if os.getenv("CI") else 100
    _NOMINATIM_BUCKET.intervalo = 1.0 / max(req_por_segundo, 0.1)
    if batch_size is None:
        batch_size = 1 if os.getenv("CI") else 2
    tipo_async = os.getenv("TIPO_ASYNC", "False").strip().lower() in ("true", "1", "yes")
    if 'lat' not in df.columns:
        df['lat'] = np.nan
    if 'lng' not in df.columns:
        df['lng'] = np.nan

    mask = df['lat'].isna() | df['lng'].isna()
    linhas_nan = df[mask]
    logger.info("Linhas com NaN: %d", len(linhas_nan))
    if len(linhas_nan) == 0:
        return df, False

    cache = _carregar_cache_geocode(cidade, estado, cache_path)
    cache_atualizado = [False]
    logger.info("Cache geocode carregado: %d entradas", len(cache))

    bairro_centroides = _calcular_centroides(df)
    logger.info("Centroides de bairro calculados: %d bairros", len(bairro_centroides))

    resultados = []
    timeout_geo = int(os.getenv("TIMEOUT_GEOCODE", "21600"))
    fim = time.monotonic() + timeout_geo
    timeout_ocorrido = False

    async with aiohttp.ClientSession() as session:
        if tipo_async:
            logger.info("Modo async: semaphoro (concorrente, batch_size=%d)", batch_size)
            semaforo = asyncio.Semaphore(batch_size)
            tasks = [
                preencher_coordenadas(session, row, semaforo, cidade, estado, pais,
                                      cache, cache_atualizado, bairro_centroides)
                for _, row in linhas_nan.iterrows()
            ]
            for i, future in tqdm(enumerate(asyncio.as_completed(tasks))):
                if time.monotonic() >= fim:
                    timeout_ocorrido = True
                    logger.warning("⏱️ Timeout — interrompendo (%d/%d)", len(resultados), len(tasks))
                    break
                resultado = await future
                resultados.append(resultado)
                if i % 10 == 0 and i > 0:
                    _atualizar_centroides(bairro_centroides, resultados[-10:])
                if i % 50 == 0 and i > 0:
                    logger.info("Progresso: %d/%d", i, len(tasks))
        else:
            logger.info("Modo sync: um_por_um (sequencial, 1 req/s)")
            for i, (_, row) in tqdm(enumerate(linhas_nan.iterrows()), total=len(linhas_nan)):
                if time.monotonic() >= fim:
                    timeout_ocorrido = True
                    logger.warning("⏱️ Timeout — interrompendo (%d/%d)", len(resultados), len(linhas_nan))
                    break
                resultado = await preencher_coordenadas(
                    session, row, None, cidade, estado, pais,
                    cache, cache_atualizado, bairro_centroides,
                )
                resultados.append(resultado)
                if i % 10 == 0 and i > 0:
                    _atualizar_centroides(bairro_centroides, resultados[-10:])
                if i % 50 == 0 and i > 0:
                    logger.info("Progresso: %d/%d", i + 1, len(linhas_nan))

    df_resultados = pd.DataFrame(resultados).set_index('idx')
    df.loc[df_resultados.index, 'lat'] = df_resultados['lat']
    df.loc[df_resultados.index, 'lng'] = df_resultados['lng']

    if cache_atualizado[0]:
        _salvar_cache_geocode(cache, cidade, estado, cache_path)
        logger.info("Cache geocode salvo: %d entradas", len(cache))

    logger.info("Ainda com NaN: %d", df['lat'].isna().sum())
    return df, timeout_ocorrido

def geocodificar_dataframe(data, cidade="Balneário Piçarras", estado="SC", pais="Brasil"):
    """
    Geocodifica endereços com retry exponencial para 429/503.
    """
    url = "https://nominatim.openstreetmap.org/search"
    
    headers = {'User-Agent': 'analise_imoveis_v1_jeferson'}
    
    df = data.copy()
    
    if 'lat' not in df.columns:
        df['lat'] = None
    if 'lng' not in df.columns:
        df['lng'] = None
        
    for idx in tqdm(df.index):
        if pd.notna(df.at[idx, 'lat']):
            continue

        rua = str(df.at[idx, 'rua'])
        bairro = str(df.at[idx, 'bairro'])
        numero = str(df.at[idx, 'numero'])
                
        partes = [p for p in [rua, numero, bairro, cidade, estado, pais] if p]
        query = ", ".join(partes)
        
        params = {
            'q': query,
            'format': 'json',
            'addressdetails': 1,
            'limit': 1
        }

        for tentativa in range(4):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    res_data = response.json()
                    if res_data:
                        df.at[idx, 'lat'] = float(res_data[0]['lat'])
                        df.at[idx, 'lng'] = float(res_data[0]['lon'])
                        logger.info(f"✅  Encontrado: {query}")
                    else:
                        logger.info(f"❌ Não encontrado {query}")
                    break

                elif response.status_code in (429, 503):
                    wait = 2 ** tentativa * 2
                    print(f"⚠️ HTTP {response.status_code} — aguardando {wait}s (tentativa {tentativa+1}/4)")
                    time.sleep(wait)
                    continue
                    
                else:
                    logger.error(f"❌ Erro HTTP {response.status_code} para: {query}")
                    break
                    
            except requests.exceptions.Timeout:
                print(f"⏱️ Timeout em {idx} (tentativa {tentativa+1}/4)")
                continue
            except Exception as e:
                print(f"🔥 Erro no índice {idx}: {e}")
                break
        
        time.sleep(1.2)
    
    return df


thread_executor = ThreadPoolExecutor(max_workers=4)

async def fetch_osm_data_async(lat, lng, radius=1000):
    """
    Busca dados do OpenStreetMap de forma assíncrona.
    """
    tags = {
        'amenity': True,
        'shop': True,
        'leisure': True,
        'highway': 'bus_stop',
        'railway': ['station', 'subway_entrance']
    }
    
    loop = asyncio.get_running_loop()
    try:
        # ox.features_from_point é síncrona e faz I/O, então rodamos no executor
        gdf = await loop.run_in_executor(
            thread_executor, 
            lambda: ox.features_from_point((lat, lng), tags=tags, dist=radius)
        )
        return gdf
    except Exception as e:
        logger.error(f"Erro ao buscar dados OSM: {e}")
        return None

async def calculate_surroundings_index_v3_async(
    gdf,
    lat,
    lng,
    radius=1000,
    category_weights=None,
    importance_weights=None,
    decay_strength=3
):
    """
    Versão assíncrona do Índice de Entorno 3.0.
    Embora o cálculo em si seja CPU-bound, a estrutura assíncrona permite
    integrar facilmente com fluxos de dados assíncronos.
    """
    if gdf is None or gdf.empty:
        return 0.0, {}

    if category_weights is None:
        category_weights = {
            'amenity': 0.4,
            'shop': 0.25,
            'leisure': 0.2,
            'public_transport': 0.15,
        }

    if importance_weights is None:
        importance_weights = {
            'hospital': 1.5, 'university': 1.4, 'supermarket': 1.3,
            'school': 1.2, 'pharmacy': 1.1, 'bus_stop': 1.2,
            'subway_entrance': 1.5, 'train_station': 1.5,
            'restaurant': 1.1, 'park': 1.2, 'gym': 1.1
        }

    gdf_proj = ox.projection.project_gdf(gdf)
    
    origin_gdf = gpd.GeoDataFrame(geometry=[Point(lng, lat)], crs="EPSG:4326")
    
    origin_proj = ox.projection.project_gdf(origin_gdf).geometry.iloc[0]
    
    gdf_proj['distance'] = gdf_proj.geometry.distance(origin_proj)
    
    decay_factor = radius / decay_strength
    
    gdf_proj['distance_score'] = 100 * np.exp(-gdf_proj['distance'] / decay_factor)

    category_results = {}

    for cat in category_weights.keys():
        if cat == 'public_transport':
            highway = gdf_proj['highway'] if 'highway' in gdf_proj.columns else pd.Series(index=gdf_proj.index, dtype=str)
            railway = gdf_proj['railway'] if 'railway' in gdf_proj.columns else pd.Series(index=gdf_proj.index, dtype=str)
            amenity = gdf_proj['amenity'] if 'amenity' in gdf_proj.columns else pd.Series(index=gdf_proj.index, dtype=str)
            
            mask = (highway == 'bus_stop') | (railway.isin(['station', 'subway_entrance'])) | (amenity == 'bus_station')
            cat_df = gdf_proj[mask].copy()
            tag_col = 'public_transport_type'
            if not cat_df.empty:
                h_vals = cat_df['highway'] if 'highway' in cat_df.columns else pd.Series(index=cat_df.index, dtype=str)
                r_vals = cat_df['railway'] if 'railway' in cat_df.columns else pd.Series(index=cat_df.index, dtype=str)
                cat_df[tag_col] = h_vals.fillna(r_vals).fillna('other_transport')
        else:
            if cat not in gdf_proj.columns: continue
            cat_df = gdf_proj[gdf_proj[cat].notna()].copy()
            tag_col = cat

        if cat_df.empty: continue

        cat_df['importance'] = cat_df[tag_col].map(importance_weights).fillna(1.0)
        
        cat_df['weighted_score'] = cat_df['distance_score'] * cat_df['importance']

        proximity_score = cat_df['weighted_score'].max()
        density_score = cat_df['weighted_score'].sum() / 10
        diversity_score = len(cat_df[tag_col].unique()) * 5

        raw_score = (0.6 * proximity_score + 0.3 * density_score + 0.1 * diversity_score)
        normalized_score = 100 * (1 - np.exp(-raw_score / 200))
        category_results[cat] = normalized_score

    final_index = sum(category_results.get(cat, 0) * weight for cat, weight in category_weights.items())
    
    return round(final_index, 2), category_results

async def main_example(locations, max_concurrent=5):
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def process_location(loc):
        async with semaphore:  # ✅ Controla acesso
            try:
                logger.info(f"[{loc['name']}] Buscando dados...")
                gdf = await fetch_osm_data_async(loc['lat'], loc['lng'])
                score, breakdown = await calculate_surroundings_index_v3_async(
                    gdf, loc['lat'], loc['lng']
                )
                logger.info(f"[{loc['name']}] ✅ Concluído - Score: {score}")
                return {
                    "name": loc['name'], 
                    "score": score, 
                    "breakdown": breakdown
                }
            except Exception as e:
                logger.error(f"[{loc['name']}] ❌ Erro: {e}")
                return {
                    "name": loc['name'], 
                    "score": 0, 
                    "breakdown": {},
                    "error": str(e)
                }

    # Executa todas as buscas em paralelo (respeitando o semáforo)
    tasks = [process_location(loc) for loc in locations]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filtra resultados com erro
    successful = [r for r in results if not isinstance(r, Exception) and 'error' not in r]
    
    failed = len(results) - len(successful)
    
    return results


async def fetch_osm_data_async_2(lat, lng, radius=1000, timeout=30):
    tags = {
        'amenity': True,
        'shop': True,
        'leisure': True,
        'highway': 'bus_stop',
        'railway': ['station', 'subway_entrance']
    }
    
    loop = asyncio.get_running_loop()
    try:
        # ✅ Timeout forçado — mata a requisição se demorar mais que 30s
        gdf = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: ox.features_from_point((lat, lng), tags=tags, dist=radius)
            ),
            timeout=timeout
        )
        return gdf
    except asyncio.TimeoutError:
        logger.info(f"⏱️ Timeout em ({lat}, {lng}) — pulando")
        return None
    except Exception as e:
        logger.error(f"❌ Erro OSM ({lat}, {lng}): {e}")
        return None

async def processar_todos_scores_localizacao(data):
    lista = []
    
    # tqdm agora percorre o tamanho total do seu dataframe
    # Usamos data.iterrows() para pegar o índice real e a linha com segurança
    for idx, row in tqdm(data.iterrows(), total=len(data)):
        
        # Pular se lat ou lng forem nulos (evita erro na API)
        if pd.isna(row['lat']) or pd.isna(row['lng']):
            logger.warning(f"[{idx}] ⚠️ Lat/Lng ausente. Pulando...")
            lista.append({'index': idx, 'score': 0.0, 'breakdown': {}})
            continue

        logger.info(f"[{idx}] Processando ({row['lat']}, {row['lng']})")
        
        lat = row['lat']
        lng = row['lng']
        
        try:
            # Busca os dados no OSM (Escolas, Hospitais, etc.)
            gdf = await fetch_osm_data_async_2(lat, lng, radius=1000, timeout=30)
            
            if gdf is None or gdf.empty:
                logger.info(f"  ⚠️ Sem dados OSM para este local")
                lista.append({'index': idx, 'score': 0.0, 'breakdown': {}})
            else:
                # Calcula o índice de infraestrutura
                score, breakdown = await calculate_surroundings_index_v3_async(gdf, lat, lng)
                lista.append({'index': idx, 'score': score, 'breakdown': breakdown})
                logger.info(f"  ✅ Score: {score}")
                
        except Exception as e:
            logger.error(f"  🔥 Erro no índice {idx}: {e}")
            lista.append({'index': idx, 'score': 0.0, 'breakdown': {}})
        
        # Respeita o limite de taxa do Overpass API (importante!)
        await asyncio.sleep(1.5)
        
        # Pausa maior a cada 20 requisições para evitar banimento de IP
        # Usamos uma contagem auxiliar ou o enumerate
        if (len(lista)) % 20 == 0:
            logger.info(f"⏸️ Pausa de 15s para evitar bloqueio (Overpass API)...")
            await asyncio.sleep(15)
    
    return lista