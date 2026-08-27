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
        #(f"uv run {cidade}_coleta_alugueis_olx.py", "Scraper OLX"),
        #(f"uv run {cidade}_coleta_alugueis_chave_mao.py", "Scraper Chave na Mão"),
        #(f"uv run {cidade}_coleta_alugueis_zap.py", "Scraper Zap Imóveis"),
        #(f"uv run {cidade}_coleta_alugueis_vivareal.py", "Scraper Viva Real"),
        (f"uv run {cidade}_juncao_dados_aluguel.py", "Scraper Junção de Dados de Aluguel"),
        (f"uv run {cidade}_limpando_dados_alugueis.py", "Scraper Limpeza de Dados de Aluguel"),
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