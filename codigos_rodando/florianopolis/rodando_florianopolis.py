import subprocess
import os
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(BASE_DIR)

cidade = os.getenv("CIDADE_PASTA")

def rodar(comando, etapa):
    print(f"\n>> {datetime.now().strftime('%H:%M:%S')} - Executando: {etapa}")
    try:
        # Usamos o shell=True para comandos git e chamadas de python
        subprocess.run(comando, shell=True, check=True)
        return True
    except Exception as e:
        print(f"!! Erro na etapa {etapa}: {e}")
        return False

if __name__ == "__main__":
   
    fluxo = [
        #(f"uv run {cidade}_coleta_dados_zap_imoveis.py", "Scraper Zap Imóveis"),
        (f"uv run {cidade}_coleta_dados_viva_real.py", "Scraper Viva Real"),
        (f"uv run {cidade}_coleta_dados_chave_mao.py", "Scraper Chave na Mão"),
        #(f"uv run {cidade}_coleta_dados_olx.py", "Scraper OLX"),
        #(f"uv run {cidade}_limpando_dados_imoveis.py", "Processamento de Dados"),
        #(f"uv run {cidade}_criando_indice_localizacao.py", "Criação do Índice de Localização")
    ]

    for comando, nome in fluxo:
        sucesso = rodar(comando, nome)
        if not sucesso:
            print(f"Parando execução devido a erro em: {nome}")
            break
        
        # Pausa entre os scrapers (ajuste conforme necessário)
        if "Scraper" in nome:
            time.sleep(60) 

    print("\n--- Processo Finalizado ---")