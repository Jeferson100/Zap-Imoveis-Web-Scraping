import json
import glob
import os
from pathlib import Path
import time
import os
from dotenv import load_dotenv
import pandas as pd

load_dotenv()

def consolidar_jsons(fonte, cidade, PASTA_DADOS, bairro = None):
    
    now = time.strftime("%Y-%m")
    
    if bairro is not None:
        padrao_busca = str(PASTA_DADOS / f'{cidade}_{bairro}_{fonte}_*.json')
    
    else:
    
        padrao_busca = str(PASTA_DADOS / f'{cidade}_{fonte}_*.json')
    
    arquivos_json = glob.glob(padrao_busca)
    
    if not arquivos_json:
        print("Nenhum arquivo encontrado com o padrão especificado.")
        return

    dados_consolidados = []
    total_arquivos = len(arquivos_json)

    print(f"Iniciando a união de {total_arquivos} arquivos...")

    for i, caminho in enumerate(arquivos_json, 1):
        nome_base = os.path.basename(caminho)
        with open(caminho, 'r', encoding='utf-8') as f:
            try:
                conteudo = json.load(f)
                # Verifica se o conteúdo é uma lista (padrão do seu scraper)
                if isinstance(conteudo, list):
                    dados_consolidados.extend(conteudo)
                else:
                    dados_consolidados.append(conteudo)
                
                print(f"[{i}/{total_arquivos}] Adicionado: {nome_base} ({len(conteudo)} itens)")
            except Exception as e:
                print(f"Erro ao ler {nome_base}: {e}")

    if bairro is not None:
        nome_final = f'{cidade}_{bairro}_{fonte}_{now}.json'
    else:
        nome_final = f'{cidade}_{fonte}_{now}.json'
    
    caminho_final = PASTA_DADOS / nome_final

    try:
        with open(caminho_final, 'w', encoding='utf-8') as f_out:
            json.dump(dados_consolidados, f_out, indent=4, ensure_ascii=False)
        
        # --- VALIDAÇÃO DE SEGURANÇA ---
        tamanho_final = os.path.getsize(caminho_final)
        
        if tamanho_final > 0 and len(dados_consolidados) > 0:
            print(f"✅ Consolidação concluída: {len(dados_consolidados)} registros.")
            print(f"📦 Arquivo gerado: {nome_final} ({tamanho_final / 1024 / 1024:.2f} MB)")
            
            # 4. Deleta os arquivos anteriores apenas se o final estiver OK
           
            print("🗑️ Removendo arquivos temporários (fatias)...")
            for arquivo_velho in arquivos_json:
                try:
                    os.remove(arquivo_velho)
                    print(f"   Excluído: {os.path.basename(arquivo_velho)}")
                except Exception as e:
                    print(f"   Erro ao excluir {arquivo_velho}: {e}")
        
            with open(caminho_final, 'w', encoding='utf-8') as f_out:
                json.dump(dados_consolidados, f_out, indent=4, ensure_ascii=False)
            
            print("✨ Limpeza concluída com sucesso!")
        else:
            print("⚠️ Erro crítico: O arquivo final parece estar vazio. Abortando exclusão.")

    except Exception as e:
        print(f"❌ Erro ao salvar arquivo consolidado: {e}")
        


def consolidar_parquet(fonte, cidade, PASTA_DADOS, bairro = None):
    now = time.strftime("%Y-%m")
    
    if bairro is not None:
        padrao_busca = str(PASTA_DADOS / f'{cidade}_{bairro}_{fonte}_*.parquet')
    else:
        padrao_busca = str(PASTA_DADOS / f'{cidade}_{fonte}_*.parquet')
    
    arquivos_parquet = glob.glob(padrao_busca)
    
    if not arquivos_parquet:
        print(f"⚠️ Nenhum arquivo encontrado para {fonte} em {cidade}.")
        return

    lista_dfs = []
    total_arquivos = len(arquivos_parquet)

    print(f"Iniciando a união de {total_arquivos} arquivos Parquet...")

    for i, caminho in enumerate(arquivos_parquet, 1):
        nome_base = os.path.basename(caminho)
        try:
            # Lendo o parquet diretamente com pandas
            df_temp = pd.read_parquet(caminho)

                
            lista_dfs.append(df_temp)
            print(f"[{i}/{total_arquivos}] Adicionado: {nome_base} ({len(df_temp)} itens)")
            
        except Exception as e:
            print(f"❌ Erro ao ler {nome_base}: {e}")

    if not lista_dfs:
        print("⚠️ Nenhum dado válido encontrado nos arquivos.")
        return

    try:
        # 2. Une todos os DataFrames em um só
        df_consolidado = pd.concat(lista_dfs, ignore_index=True)

        if bairro is not None:
            nome_final = f'{cidade}_{bairro}_{fonte}_{now}.parquet'
        else:
            nome_final = f'{cidade}_{fonte}_{now}.parquet'
            
        caminho_final = PASTA_DADOS / nome_final

        # Salva usando compressão snappy (muito mais leve)
        df_consolidado.to_parquet(caminho_final, index=False, compression='snappy')
        
        # --- VALIDAÇÃO DE SEGURANÇA ---
        tamanho_final = os.path.getsize(caminho_final)
        
        if tamanho_final > 0:
            print(f"✅ Consolidação concluída: {len(df_consolidado)} registros.")
            print(f"📦 Arquivo gerado: {nome_final} ({tamanho_final / 1024 / 1024:.2f} MB)")
            
            # 4. Deleta os arquivos temporários (fatias)
            print("🗑️ Removendo arquivos temporários (fatias)...")
            for arquivo_velho in arquivos_parquet:
                # Evita deletar o próprio arquivo final caso ele tenha entrado no glob
                if os.path.abspath(arquivo_velho) != os.path.abspath(caminho_final):
                    try:
                        os.remove(arquivo_velho)
                        print(f"   Excluído: {os.path.basename(arquivo_velho)}")
                    except Exception as e:
                        print(f"   Erro ao excluir {arquivo_velho}: {e}")
            
            print("✨ Limpeza concluída com sucesso!")
            
            df_consolidado.to_parquet(caminho_final, index=False, compression='snappy')
        
        else:
            print("⚠️ Erro crítico: O arquivo final parece estar vazio. Abortando exclusão.")
        

    except Exception as e:
        print(f"❌ Erro na união ou salvamento: {e}")
