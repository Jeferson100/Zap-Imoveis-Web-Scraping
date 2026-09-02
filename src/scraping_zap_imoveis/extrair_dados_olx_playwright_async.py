import asyncio
import datetime
import html as html_mod
import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Optional, List

from playwright.async_api import async_playwright, BrowserContext, Page

try:
    from playwright_stealth import Stealth
    _STEALTH_OK = True
except Exception:
    _STEALTH_OK = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@dataclass
class DadosImovel:
    "Estrutura de dados de um imóvel da OLX."
    url: str
    titulo: Optional[str] = None
    valor_imovel: Optional[int] = 0
    metragem: Optional[int] = 0
    quartos: Optional[int] = 0
    banheiros: Optional[int] = 0
    vagas: Optional[int] = 0
    condominio: Optional[int] = 0
    iptu: Optional[int] = 0
    endereco: Optional[str] = None
    descricao: Optional[str] = None
    data_criacao: Optional[str] = None
    fotos: List[str] = field(default_factory=list)
    caracteristicas: List[str] = field(default_factory=list)
    caracteristicas_privativa: List[str] = field(default_factory=list)
    caracteristicas_comum: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__

class OLXScraperAsync:
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # segundos
    def __init__(self,headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._pw_cm = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        # O navegador só é iniciado sob demanda (_ensure_browser) no fallback Playwright.
        self._pw_cm = None
        self._playwright = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._page = None
        return self

    async def _ensure_browser(self):
        """Inicia o navegador Playwright apenas quando necessário (fallback)."""
        if self._browser is not None:
            return
        try:
            pw = async_playwright()
            if _STEALTH_OK:
                self._pw_cm = Stealth().use_async(pw)
            else:
                self._pw_cm = pw
            self._playwright = await self._pw_cm.__aenter__()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            self._page = await self._context.new_page()
        except Exception as e:
            logger.error("Erro ao inicializar navegador: %s", e)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
            
    async def _get_text(self, seletor: str, timeout: int = 2500) -> Optional[str]:
        try:
            element = self._page.locator(seletor).first
            
            # 1. Mudamos de "attached" para "visible"
            # Isso garante que o elemento não está apenas no código, mas renderizado na tela
            await element.wait_for(state="visible", timeout=timeout)
            
            # 2. Loop de verificação de conteúdo (Retry interno)
            # Às vezes o elemento aparece, mas o texto demora 200ms para ser injetado
            for _ in range(2): 
                texto = (await element.inner_text()).strip()
                if texto and len(texto) > 0:
                    return texto
                await asyncio.sleep(0.15) # Pequena espera se o texto vier vazio
            return None
        except Exception:
            return None
        
    async def _get_metragem_principal(self) -> Optional[str]:
        try:
            seletor = 'span:has-text("Área útil"), span:has-text("Área construída"), span:has-text("Tamanho")'
            element = self._page.locator(seletor).locator('xpath=../span[2]')
            await element.wait_for(state="attached", timeout=2500)
            metragem = await element.inner_text()
            return metragem
        except Exception:
            return None
    
    """async def _get_metragem_secundaria(self) -> Optional[str]:
        try:
            # 1. TENTATIVA POR REGEX (A mais estável para dados numéricos)
            # Buscamos qualquer texto dentro do container de detalhes que tenha "número + m²"
            # Isso ignora se o rótulo é "Área útil", "Tamanho" ou "Área construída"
            container = self._page.locator("#details")
            
            # Aguarda o container existir, não um span específico
            await container.wait_for(state="attached", timeout=2000)
            
            # Pegamos todos os textos de spans dentro do container de uma vez (mais rápido)
            todos_textos = await container.locator("span").all_inner_texts()
            
            for texto in todos_textos:
                # Procura o padrão: um ou mais números seguidos opcionalmente de espaço e m²
                match = re.search(r'(\d+)\s?m²', texto)
                if match:
                    return match.group(1) # Retorna apenas o número (ex: 59)

            # 2. TENTATIVA POR RÓTULO (Caso o m² esteja em outro elemento)
            # Se não achamos o "m²" grudado no número, buscamos o valor ao lado dos rótulos conhecidos
            rotulos = ["Área útil", "Área construída", "Tamanho total", "Tamanho"]
            for rotulo in rotulos:
                # Busca o container que contém o rótulo e extrai o texto dele
                # O .jhmjmi é a classe padrão dos blocos de detalhes da OLX
                locator_rotulo = container.locator(f'.jhmjmi:has-text("{rotulo}")')
                if await locator_rotulo.count() > 0:
                    texto_bloco = await locator_rotulo.first.inner_text()
                    # Remove o nome do rótulo e limpa o que sobrar (espera-se o número)
                    valor = texto_bloco.replace(rotulo, "").replace("m²", "").strip()
                    if valor.isdigit():
                        return valor

            return None
        except Exception as e:
            # Se você tiver um logger, use-o para entender o erro real (ex: Timeout)
            return None"""

    async def _get_metragem_secundaria(self) -> Optional[str]:
        try:
            container = self._page.locator("#details")
            await container.wait_for(state="attached", timeout=3000)
            
            # Pega TUDO de uma vez para processar em memória (Python é mais rápido que o Browser)
            textos = await container.locator("span").all_inner_texts()
            texto_completo_bloco = " ".join(textos)

            # A: Tenta o Regex direto no bloco todo (Ex: "Área útil 59m²")
            match = re.search(r'(\d+)\s?m²', texto_completo_bloco)
            if match:
                return match.group(1)

            # B: Se não achou "m²", tenta buscar o número isolado perto das palavras-chave
            # Isso ajuda se a OLX separar o "59" do "m²" em spans diferentes
            rotulos = ["Área útil", "Área construída", "Tamanho total", "Tamanho"]
            for rotulo in rotulos:
                for i, txt in enumerate(textos):
                    if rotulo in txt:
                        # Tenta ver se o próximo span é o número
                        if i + 1 < len(textos):
                            proximo = textos[i+1].strip()
                            # Extrai apenas os números caso venha "59 m2" ou "59"
                            num = re.sub(r'\D', '', proximo)
                            if num: return num
            return None
        except:
            return None
    
    async def _get_metragem(self) -> Optional[str]:
        # 1. Tenta o método principal (XPath)
        metragem = await self._get_metragem_principal()
        
        # Valida se o que voltou faz sentido (tem números)
        if metragem and re.search(r'\d+', metragem):
            return metragem.replace("m²", "").strip()
        
        # 2. Se falhar ou vier vazio, vai para o secundário
        return await self._get_metragem_secundaria()
        

    async def _get_quartos(self) -> Optional[str]:
        try:
            seletor = 'div:has(> span:has-text("Quartos"))'
            element = self._page.locator(seletor).locator('span, a').last
            await element.wait_for(state="attached", timeout=2500)
            quartos = await element.inner_text()
            return quartos
        except Exception:
            return None
    

    async def _get_valor_imovel(self) -> Optional[int]:
        try:
            # 1. Localiza o Badge de "Venda" como âncora principal
            badge_venda = self._page.locator('span[data-ds-component="DS-Badge"]:has-text("Venda")').first
            
            # Garante que o elemento "Venda" carregou na tela
            await badge_venda.wait_for(state="visible", timeout=3000)

            # 2. Estratégia XPath: 
            # "A partir do badge Venda, suba até o pai e procure o primeiro elemento que tenha R$"
            # Isso separa o Preço do Imóvel dos preços de Condomínio/IPTU que vêm depois
            container_pai = self._page.locator('div.ad__sc-q5xder-1').first
            
            # Buscamos especificamente o span com a classe typo-title-large que está dentro desse bloco
            preco_elemento = container_pai.locator('span.typo-title-large').first
            
            texto_preco = await preco_elemento.inner_text()
            
            if texto_preco:
                # Limpeza: "R$ 360.000" -> 360000
                valor_limpo = "".join(filter(str.isdigit, texto_preco))
                return int(valor_limpo) if valor_limpo else None

            return None

        except Exception as e:
            # Plano B: Se o seletor de classe falhar, tentamos pegar o primeiro "R$" do container
            try:
                texto_fallback = await self._page.locator('div.ad__sc-q5xder-1 span:has-text("R$")').first.inner_text()
                valor_limpo = "".join(filter(str.isdigit, texto_fallback))
                return int(valor_limpo)
            except:
                return None
    
    async def _get_endereco(self) -> Optional[str]:
        
        try:
            container_localizacao = self._page.locator("#location")

                # O Bairro é o primeiro span com a classe typo-body-medium
            bairro = await self._get_text("#location span.typo-body-medium")

                # A Cidade/Estado/CEP é o span logo abaixo com a classe typo-body-small
            cidade_raw = await self._get_text("#location span.typo-body-small.text-neutral-110")

            # Se falhar, tentamos um seletor genérico dentro do bloco de localização
            if not bairro:
                bairro = await self._get_text("#location div.flex.flex-col span:first-child")
            if not cidade_raw:
                cidade_raw = await self._get_text("#location div.flex.flex-col span:last-child")
            if bairro and cidade_raw:
                return f"{bairro}, {cidade_raw}"
            else:
                return None
        except Exception:
            return None
            

    async def _extrair_caracteristicas(self) -> tuple[List[str], List[str]]:
        priv, comum = [], []
        try:
            html = await self._page.content()
            m_priv = re.search(r'"name"\s*:\s*"re_features".*?"values"\s*:\s*\[(.*?)\]', html, re.S)
            if m_priv:
                priv = re.findall(r'"label"\s*:\s*"([^"]+)"', m_priv.group(1))
            m_com = re.search(r'"name"\s*:\s*"re_complex_features".*?"values"\s*:\s*\[(.*?)\]', html, re.S)
            if m_com:
                comum = re.findall(r'"label"\s*:\s*"([^"]+)"', m_com.group(1))
            if priv or comum:
                return [html_mod.unescape(p).strip() for p in priv if p.strip()], [html_mod.unescape(c).strip() for c in comum if c.strip()]
        except Exception:
            pass
        try:
            priv = await self._page.locator('div.advc-optional-subsection:has-text("Características do imóvel") span.typo-body-small').all_inner_texts()
            comum = await self._page.locator('div.advc-optional-subsection:has-text("Características do condomínio") span.typo-body-small').all_inner_texts()
            return [p.strip() for p in priv if p.strip()], [c.strip() for c in comum if c.strip()]
        except Exception:
            return [], []

    async def _extrair_dados_da_pagina(self, url: str) -> DadosImovel:
        (
            metragem_raw,
            quartos_raw,
            banheiros_raw,
            vagas_raw,
            condo_raw,
            iptu_raw,
            endereco,
            titulo,
            descricao,
            data_criacao,
            fotos,
        ) = await asyncio.gather(
            self._get_metragem(),
            self._get_quartos(),
            self._get_text("span:has-text('Banheiros') + span"),
            self._get_text("span:has-text('Vagas na garagem') + span"),
            self._get_text("xpath=//span[normalize-space(text())='Condomínio']/following-sibling::div//span[last()]"),
            self._get_text("xpath=//span[normalize-space(text())='IPTU']/following-sibling::div//span[last()]"),
            self._get_endereco(),
            self._get_text('span[data-side-margin="false"]'),
            self._get_text('span.typo-body-medium[style*="word-break: break-word"]'),
            self._get_text('span.typo-caption.text-neutral-100.font-semibold'),
            self._page.locator("#item-gallery-image picture img").evaluate_all(
                "elements => elements.map(el => el.src)"
            ),
        )
        
        valor_imovel = await self._get_valor_imovel()
        priv, comum = await self._extrair_caracteristicas()

        return DadosImovel(
            url=url,
            titulo=titulo,
            valor_imovel=valor_imovel,
            metragem=metragem_raw,
            quartos=quartos_raw,
            banheiros=banheiros_raw,
            vagas=vagas_raw,
            condominio=condo_raw,
            iptu=iptu_raw,
            endereco=endereco,
            descricao=descricao,
            data_criacao=data_criacao,
            fotos=fotos,
            caracteristicas=[],
            caracteristicas_privativa=priv,
            caracteristicas_comum=comum,
        )

    async def extrair_anuncio(self, url: str) -> dict:
        dados = await self._extrair_anuncio_curl(url)
        if dados is not None:
            logger.info("Anúncio extraído via curl_cffi: %s", url)
            return dados

        logger.warning("curl_cffi falhou para %s. Caindo para Playwright.", url)
        return await self._extrair_anuncio_playwright(url)

    # ---------------------------------------------------------------
    # Modo primário: curl_cffi (parse do HTML/JSON server-rendered)
    # ---------------------------------------------------------------
    async def _extrair_anuncio_curl(self, url: str) -> Optional[dict]:
        return await asyncio.to_thread(self._extrair_anuncio_curl_sync, url)

    def _extrair_anuncio_curl_sync(self, url: str) -> Optional[dict]:
        try:
            from curl_cffi import requests as cr
        except ImportError:
            logger.error("curl_cffi não está instalado. Usando fallback.")
            return None

        try:
            resp = cr.get(url, impersonate="chrome", timeout=35000)
            if resp.status_code != 200:
                logger.warning("curl_cffi retornou status %s para %s", resp.status_code, url)
                return None
            return self._parse_html_anuncio(url, resp.text)
        except Exception as e:
            logger.warning("Erro curl_cffi em %s: %s", url, e)
            return None

    def _parse_html_anuncio(self, url: str, html_text: str) -> dict:
        """Extrai os dados do anúncio a partir do HTML server-rendered da OLX."""
        # O HTML server-rendered escapa as aspas dos JSON embutidos (&quot;). 
        # Decodificar antes facilita os regex abaixo.
        html_text = html_mod.unescape(html_text)

        def attr_value(name: str) -> Optional[str]:
            # Ex.: {"name":"size","label":"Área útil","value":"62m²"}
            m = re.search(r'"name"\s*:\s*"' + re.escape(name) + r'"[^}]*?"value"\s*:\s*"([^"]+)"', html_text)
            return m.group(1) if m else None

        def limpar_numero(texto: Optional[str]) -> Optional[int]:
            if not texto:
                return None
            digitos = re.sub(r"\D", "", texto)
            return int(digitos) if digitos else None

        def limpar_numero_quebrado(texto: Optional[str]) -> Optional[int]:
            if not texto:
                return None
            digitos = re.sub(r"[^0-9.,]", "", texto)
            digitos = digitos.replace(".", "").replace(",", ".")
            try:
                return int(float(digitos))
            except ValueError:
                return None

        # ---- Valor do imóvel (JSON-LD / dataLayer): "price":"360000"
        valor_imovel = None
        m = re.search(r'"price"\s*:\s*"([\d.]+)"', html_text)
        if m:
            valor_imovel = int(m.group(1).replace(".", ""))
        else:
            m = re.search(r'"price"\s*:\s*(\d+)', html_text)
            if m:
                valor_imovel = int(m.group(1))

        # ---- Atributos estruturados
        metragem_raw = attr_value("size") or attr_value("area")
        quartos_raw = attr_value("rooms")
        banheiros_raw = attr_value("bathrooms")
        vagas_raw = attr_value("garage_spaces")
        condo_raw = attr_value("condominio")
        iptu_raw = attr_value("iptu")

        # ---- Título
        titulo = None
        m = re.search(r'property="og:title" content="([^"]+)"', html_text)
        if m:
            titulo = html_mod.unescape(m.group(1)).strip()
        else:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.S)
            if m:
                titulo = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()

        # ---- Descrição
        descricao = None
        m = re.search(r'property="og:description" content="([^"]*)"', html_text)
        if m:
            descricao = re.sub(r"<[^>]+>", " ", html_mod.unescape(m.group(1)))
            descricao = re.sub(r"\s+", " ", descricao).strip()
        else:
            m = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', html_text)
            if m:
                try:
                    descricao = json.loads('"' + m.group(1) + '"')
                    descricao = re.sub(r"<[^>]+>", " ", descricao)
                    descricao = html_mod.unescape(descricao)
                    descricao = re.sub(r"\s+", " ", descricao).strip()
                except Exception:
                    descricao = None

        # ---- Data de criação (epoch "adDate" no dataLayer)
        data_criacao = None
        m = re.search(r'"adDate"\s*:\s*(\d+)', html_text)
        if m:
            try:
                ts = int(m.group(1))
                dt = datetime.datetime.utcfromtimestamp(ts)
                data_criacao = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                data_criacao = None

        # ---- Fotos
        fotos = list(dict.fromkeys(re.findall(r'https://img\.olx\.com\.br/images/[^"\s\\]+', html_text)))

        # ---- Endereço (bairro/município via JSON de propriedades)
        endereco = None
        bairro = None
        municipio = None
        uf = None
        m = re.search(r'"label"\s*:\s*"Bairro"\s*,\s*"value"\s*:\s*"([^"]+)"', html_text)
        if m:
            bairro = html_mod.unescape(m.group(1))
        m = re.search(r'"label"\s*:\s*"Munic[uí]pio"\s*,\s*"value"\s*:\s*"([^"]+)"', html_text)
        if m:
            municipio = html_mod.unescape(m.group(1))
        m = re.search(r'"addressRegion"\s*:\s*"([^"]+)"', html_text)
        if m:
            uf = m.group(1)

        partes_endereco = []
        if bairro:
            partes_endereco.append(bairro)
        if municipio:
            partes_endereco.append(municipio)
        if uf:
            partes_endereco.append(uf)
        if partes_endereco:
            endereco = ", ".join(partes_endereco)

        def extract_features(name: str) -> List[str]:
            m = re.search(r'"name"\s*:\s*"' + re.escape(name) + r'".*?"values"\s*:\s*\[(.*?)\]', html_text, re.S)
            if m and m.group(1).strip():
                labs = re.findall(r'"label"\s*:\s*"([^"]+)"', m.group(1))
                if labs:
                    return [html_mod.unescape(l).strip() for l in labs if l.strip()]
            v = attr_value(name)
            if v:
                return [html_mod.unescape(s).strip() for s in v.split(",") if s.strip()]
            return []

        priv = extract_features("re_features")
        comum = extract_features("re_complex_features")

        dados = DadosImovel(
            url=url,
            titulo=titulo,
            valor_imovel=valor_imovel,
            metragem=limpar_numero_quebrado(metragem_raw),
            quartos=limpar_numero(quartos_raw),
            banheiros=limpar_numero(banheiros_raw),
            vagas=limpar_numero(vagas_raw),
            condominio=limpar_numero_quebrado(condo_raw),
            iptu=limpar_numero_quebrado(iptu_raw),
            endereco=endereco,
            descricao=descricao,
            data_criacao=data_criacao,
            fotos=fotos,
            caracteristicas=[],
            caracteristicas_privativa=priv,
            caracteristicas_comum=comum,
        )

        # Só considera sucesso se ao menos valor ou título vieram (página de anúncio real)
        if dados.valor_imovel is None and not dados.titulo:
            return None
        return dados.to_dict()

    # ---------------------------------------------------------------
    # Fallback: Playwright (implementação original)
    # ---------------------------------------------------------------
    async def _extrair_anuncio_playwright(self, url: str) -> dict:
        await self._ensure_browser()
        for tentativa in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(f"Processando {tentativa}/{self.MAX_RETRIES}: {url}")
                
                # Navegação agressiva focada no DOM
                await self._page.goto(url, wait_until="domcontentloaded", timeout=35000)
                
                # Delay mínimo para estabilização sem penalizar throughput
                await asyncio.sleep(random.uniform(0.1, 0.5)) 
                
                dados = await self._extrair_dados_da_pagina(url)
                logger.info(f"Sucesso: {dados.titulo[:30]}...")
                return dados.to_dict()

            except Exception as e:
                logger.warning(f"Erro na tentativa {tentativa} para {url}: {e}")
                if tentativa < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY * tentativa)
                else:
                    logger.error(f"Falha definitiva em {url}")
                    return DadosImovel(url=url).to_dict()

if __name__ == "__main__":
    async def main():
        #link_joinville = "https://sc.olx.com.br/norte-de-santa-catarina/imoveis/casa-com-2-dormitorios-sendo-2-suites-e-2-vagas-de-garagem-em-joinville-sc-1481632088?lis=listing_1001"
        
        #link_joinville = "https://sc.olx.com.br/norte-de-santa-catarina/imoveis/casa-a-venda-vila-nova-joinville-sc-1488411498?lis=listing_1001"
        
        link_joinville = "https://sp.olx.com.br/sao-paulo-e-regiao/imoveis/sao-paulo-padrao-bela-vista-994788219"
        
        async with OLXScraperAsync(headless=True) as scraper:
            resultado = await scraper.extrair_anuncio(link_joinville)
            print("resultado:", resultado)
            
    asyncio.run(main())
    
