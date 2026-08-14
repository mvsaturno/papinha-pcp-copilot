import os
import time
import requests
from requests.exceptions import HTTPError, RequestException
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env
load_dotenv()

EXCIA_BASE_URL = os.getenv("EXCIA_BASE_URL")
EXCIA_TOKEN = os.getenv("EXCIA_TOKEN")

class ExciaAPIClient:
    def __init__(self):
        if not EXCIA_BASE_URL or not EXCIA_TOKEN:
            raise ValueError("EXCIA_BASE_URL ou EXCIA_TOKEN não definidos no .env")
        
        self.base_url = EXCIA_BASE_URL.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Token": EXCIA_TOKEN
        })

    def get(self, endpoint, params=None, max_retries=3):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=15)
                
                # Se for 429 Too Many Requests, respeitamos o Rate Limit
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        # Retry-After normalmente vem em milissegundos conforme a doc (embora RFC HTTP seja segundos)
                        # A documentação da Excia diz: "Tempo de espera necessário para tentar novamente, em milissegundos"
                        wait_seconds = int(retry_after) / 1000.0
                    else:
                        wait_seconds = 1.0  # fallback

                    print(f"[Rate Limit] Aguardando {wait_seconds}s...")
                    time.sleep(wait_seconds)
                    continue

                response.raise_for_status()
                
                # A API retorna sempre array JSON pelo que consta na doc
                return response.json()

            except HTTPError as e:
                # Se for 400 e a mensagem indicar que não há registros,
                # retornamos lista vazia em vez de falhar. (Protege paginação infinita)
                if response.status_code == 400 and "Nenhum registro encontrado" in response.text:
                    return []
                
                # Vamos logar e levantar exceção se não for 429 ou se acabarem os retries
                if response.status_code != 429 or attempt == max_retries - 1:
                    print(f"Erro ao chamar {url}: {response.text}")
                    raise e
            except RequestException as e:
                if attempt == max_retries - 1:
                    print(f"Erro de rede ao chamar {url}: {str(e)}")
                    raise e
                time.sleep(1.0) # Espera simples por erro de rede genérico

        return None
