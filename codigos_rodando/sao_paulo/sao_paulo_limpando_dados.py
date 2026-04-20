from pathlib import Path
import logging
import warnings
import sys

import os
from dotenv import load_dotenv

load_dotenv()

sys.path.append(str(Path(__file__).parent.parent))

from limpando_dados import limpando_dados

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")

cidade_limpeza      =  os.getenv("CIDADE_LIMPEZA")

cidade_localizacao  =  os.getenv("CIDADE_LOCALIZACAO")

estado_limpeza      =  os.getenv("ESTADO_LIMPEZA")

estado_localizacao  =  os.getenv("ESTADO_LOCALIZACAO")

PASTA_DADOS  = Path(__file__).parent.parent.parent / 'dados'/ cidade

BATCH        =  os.getenv("BATCH_LIMPEZA")

BATCH = int(BATCH) if BATCH and BATCH.isdigit() else 100

logger.info(f"Iniciando limpeza de dados de imóveis de {cidade_limpeza}...")

logger.info(f"Pasta de dados: {PASTA_DADOS}")

logger.info(f"Os parametros de limpeza são: cidade_limpeza={cidade_limpeza}, cidade_localizacao={cidade_localizacao}, estado_limpeza={estado_limpeza}, estado_localizacao={estado_localizacao}, BATCH={BATCH}")

PASTA_DADOS.mkdir(parents=True, exist_ok=True)


MAPA_BAIRROS = {
    'ipiranga': ['Ipiranga', 'ipiranga', 'vila firmiano pinto', 'vila gumercindo', 'vila independencia', 'vila monumento', 'vila nair'],
    'liberdade': ['aclimacao', 'liberdade'],
    'barra funda': ['agua branca', 'barra funda', 'jardim das perdizes', 'parque industrial tomas edson'],
    'santana': ['agua fria', 'jardim sao paulo', 'santa teresinha', 'santa terezinha', 'santana', 'vila aurora', 'vila dom pedro ii', 'vila pauliceia', 'vila paulistania'],
    'agua rasa': ['agua rasa', 'vila invernada'],
    'aricanduva': ['aricanduva', 'jardim aricanduva', 'jardim arize', 'jardim bibi', 'jardim imperador zona leste', 'jardim modelo', 'parque maria luiza', 'vila antonieta', 'vila aricanduva', 'vila nova york'],
    'artur alvim': ['artur alvim', 'jardim nordeste', 'jardim sao nicolau', 'parque das paineiras'],
    'bela vista': ['bela vista'],
    'belem': ['belem', 'belenzinho'],
    'bom retiro': ['bom retiro'],
    'bras': ['bras'],
    'brasilandia': ['brasilandia', 'jardim guarani', 'jardim maristela', 'jardim paulistano zona norte'],
    'itaim bibi': ['brooklin', 'chacara itaim', 'cidade moncoes', 'itaim bibi', 'jardim das acacias', 'vila cordeiro', 'vila olimpia'],
    'butanta': ['butanta', 'jardim bonfiglioli', 'jardim olympia', 'jardim pinheiros', 'jardim universidade pinheiros', 'parque reboucas', 'vila butanta', 'vila gomes'],
    'cambuci': ['cambuci'],
    'campo belo': ['campo belo', 'jardim aeroporto', 'jardim petropolis', 'vila congonhas'],
    'campo grande': ['campo grande', 'jardim belgica', 'jardim do golf', 'jardim marajoara', 'jardim sabara', 'jardim umuarama', 'jardim vitoria regia zona sul', 'vila anhanguera', 'vila gea', 'vila isa', 'vila libanesa'],
    'santa cecilia': ['campos eliseos', 'santa cecilia'],
    'cangaiba': ['cangaiba', 'jardim danfer', 'jardim penha', 'jardim piratininga'],
    'casa verde': ['casa verde', 'jardim das laranjeiras zona norte', 'jardim sao bento', 'parque peruche', 'vila bela vista zona norte', 'vila celeste', 'vila ester zona norte'],
    'se': ['centro', 'se'],
    'tatuape': ['chacara california', 'cidade mae do ceu', 'parque sao jorge', 'vila gomes cardim', 'vila moreira', 'vila santo estevao'],
    'santo amaro': ['chacara flora', 'chacara monte alegre', 'chacara santo antonio', 'jardim caravelas', 'jardim dom bosco', 'jardim dos estados', 'jardim duprat', 'jardim santa josefina', 'santo amaro', 'vila cruzeiro'],
    'vila mariana': ['chacara klabin', 'jardim da gloria', 'jardim paraiso', 'jardim vila mariana', 'vila clementino', 'vila mariana'],
    'carrao': ['chacara santo antonio zona leste', 'vila carrao'],
    'vila matilde': ['chacara seis de outubro', 'cidade patriarca', 'jardim eliane', 'jardim maringa', 'vila dalila', 'vila euthalia', 'vila guilhermina', 'vila nova savoia', 'vila matilde'],
    'itaguera': ['cidade a e carvalho'],
    'cidade ademar': ['cidade ademar', 'jardim consorcio', 'jardim lallo', 'jardim melo', 'jardim miriam', 'jardim prudencia', 'vila castelo', 'vila marari', 'vila mira'],
    'cidade dutra': ['cidade dutra', 'interlagos'],
    'morumbi': ['cidade jardim', 'fazenda morumbi', 'jardim guedala', 'jardim leonor', 'jardim morumbi', 'jardim panorama zona oeste', 'morumbi', 'vila inah'],
    'cidade lider': ['cidade lider', 'jardim fernandes', 'jardim santa maria'],
    'rio pequeno': ['cidade sao francisco', 'jardim arpoador', 'jardim claudia', 'jardim esmeralda zona oeste', 'jardim ester', 'jardim ester yolanda', 'jardim ivana', 'jardim periperi', 'jardim sonia', 'parque dos principes', 'parque esmeralda', 'rio pequeno', 'vila adalgisa', 'vila bauab'],
    'jabaquara': ['cidade vargas', 'jabaquara', 'jardim oriental', 'parque jabaquara', 'vila do encontro', 'vila fachini', 'vila marina', 'vila olinda', 'vila parque jabaquara', 'vila paulista'],
    'consolacao': ['consolacao', 'higienopolis'],
    'cursino': ['cursino', 'jardim celeste', 'vila brasilina'],
    'ermelino matarazzo': ['ermelino matarazzo', 'vila paranagua', 'vila santa ines'],
    'vila sonia': ['ferreira', 'jardim das vertentes', 'jardim jussara', 'jardim londrina', 'jardim monte kemel', 'jardim taboao'],
    'freguesia do o': ['freguesia do o', 'itaberaba', 'parque itaberaba', 'vila carbone', 'vila itaberaba', 'vila palmeiras'],
    'guaianases': ['guaianases'],
    'penha': ['guaiauna', 'penha', 'penha de franca', 'vila ernesto', 'vila esperanca', 'vila granada', 'vila lais', 'vila marieta'],
    'itaim paulista': ['itaim paulista', 'jardim dinorah', 'jardim iracema', 'jardim leme', 'jardim marilu', 'jardim miragaia'],
    'itaquera': ['itaquera', 'vila carmosina'],
    'jacana': ['jacana'],
    'jaguare': ['jaguare', 'parque continental'],
    'jaragua': ['jaragua', 'jardim jaragua', 'jardim marisa', 'jardim rincao'],
    'vila prudente': ['jardim independencia', 'jardim avelino', 'jardim guairaca', 'jardim ibitirama', 'vila alpina', 'vila bela', 'vila california zona leste', 'vila ema', 'vila graciosa', 'vila industrial', 'vila ivone', 'vila lucia', 'vila macedopolis', 'vila monte santo'],
    'cid ademar': ['jardim adhemar de barros'],
    'grajau': ['jardim alvina', 'jardim myrna'],
    'vila andrade': ['jardim ampliacao', 'jardim das palmas', 'jardim fonte do morumbi', 'jardim sul', 'vila andrade', 'vila das belezas', 'vila morse', 'vila nova das belezas'],
    'vila formosa': ['jardim analia franco', 'jardim textil', 'vila formosa'],
    'raposo tavares': ['jardim boa vista zona oeste', 'raposo tavares'],
    'vila medeiros': ['jardim brasil', 'jardim brasil zona norte', 'parque edu chaves', 'vila constanca', 'vila ede', 'vila medeiros'],
    'tremembe': ['jardim cabore', 'jardim floresta', 'jardim leonor mendes de barros', 'jardim pedra branca', 'jardim tango', 'jardim virginia bianca', 'parque casa de pedra', 'tremembe', 'vila irmaos arnoni'],
    'lajeado': ['jardim castelo', 'lajeado'],
    'jardim sao luis': ['jardim centenario', 'jardim cidalia', 'jardim sao luis'],
    'pirituba': ['jardim cidade pirituba', 'jardim felicidade zona norte', 'jardim iris', 'jardim itatinga', 'jardim libano', 'jardim mangalot', 'jardim picolo', 'jardim regina', 'piqueri', 'pirituba', 'vila barreto', 'vila bonilha', 'vila caju', 'vila clarice', 'vila feliz', 'vila fiat lux', 'vila iorio', 'vila mangalot', 'vila mirante', 'vila pereira barreto', 'vila pereira cerca'],
    'saude': ['jardim da saude', 'sao judas', 'saude', 'vila monte alegre'],
    'pinheiros': ['jardim das bandeiras', 'jardim europa', 'jardim paulistano', 'pinheiros', 'vila beatriz zona oeste', 'vila madalena'],
    'nossa senhora do o': ['jardim das gracas', 'jardim vila rica'],
    'campo limpo': ['jardim bandeirantes zona sul', 'jardim leonidas moreira i', 'jardim umarizal', 'parque ipe'],
    'sapopemba': ['jardim itapema', 'sapopemba', 'vila arruda', 'vila darli'],
    'moema': ['jardim luzitania', 'moema', 'vila nova conceicao'],
    'sacoma': ['jardim maria estela', 'jardim patente', 'jardim santa cruz zona sul', 'jardim santa emilia', 'jardim sao saverio', 'jardim vergueiro (sacoma)', 'parque fongaro', 'sacoma', 'vila caraguata', 'vila das merces', 'vila liviero', 'vila moinho velho', 'vila moraes'],
    'perus': ['jardim mirante', 'perus'],
    'parque do carmo': ['jardim nossa senhora do carmo', 'jardim santa terezinha', 'jardim sao cristovao'],
    'jardim paulista': ['jardim paulista'],
    'limao': ['jardim pereira leite', 'limao', 'vila carolina zona norte', 'vila joao batista', 'vila nova carolina'],
    'vila nova cachoeirinha': ['jardim peri'],
    'ponte rasa': ['jardim popular', 'jardim tres marias', 'parque boturussu', 'ponte rasa'],
    'sao mateus': ['jardim sao francisco zona leste', 'jardim tiete', 'parque colonial'],
    'perdizes': ['jardim vera cruz', 'perdizes', 'sumare', 'vila anglo brasileira'],
    'lapa': ['lapa', 'vila anastacio', 'vila hamburguesa', 'vila ipojuca'],
    'mandaqui': ['mandaqui', 'parque mandaqui'],
    'mooca': ['mooca', 'parque da mooca', 'vila bertioga'],
    'parelheiros': ['parelheiros'],
    'pari': ['pari', 'vila carlos de campos'],
    'capao redondo': ['parque fernanda'],
    'sao domingos': ['parque maria domitila', 'parque sao domingos', 'sao domingos'],
    'vila maria': ['parque novo mundo', 'vila maria', 'vila maria alta', 'vila marte'],
    'cidade tiradentes': ['prestes maia'],
    'republica': ['republica', 'vila buarque'],
    'sao miguel': ['sao miguel paulista'],
    'socorro': ['socorro'],
    'cachoeirinha': ['vila amalia zona norte', 'vila basileia', 'vila dionisia', 'vila nova cachoeirinha'],
    'alto de pinheiros': ['vila brasilio machado'],
    'jaguara': ['vila dos remedios', 'vila jaguara'],
    'vila guilherme': ['vila guilherme', 'vila isolina mazzei', 'vila leonor'],
    'vila leopoldina': ['vila leopoldina'],
    'vila curuca': ['vila nova curuca'],
    'tucuruvi': ['jardim franca', 'jardim guapira', 'parada inglesa', 'tucuruvi', 'vila gustavo', 'vila mazzei', 'vila nivi', 'vila nova mazzei']
}
limpando_dados(name_arquivo_zap = f'{cidade}_zap_*.json', 
               name_arquivo_vivareal = f'{cidade}_vivareal_*.json', 
               name_arquivo_chave_mao = f'{cidade}_chave_mao_*.json',
               name_arquivo_olx = f'{cidade}_olx_*.json',
               name_arquivo_saida = f'{cidade}_imoveis_limpo', 
               pasta_dados = PASTA_DADOS, 
               tipo_async = True,
               batch = BATCH, 
               cidade_limpeza=cidade_limpeza,
               cidade_localizacao=cidade_localizacao,
               estado_limpeza=estado_limpeza,
               estado_localizacao=estado_localizacao, 
               MAPA_BAIRROS=MAPA_BAIRROS,
               )