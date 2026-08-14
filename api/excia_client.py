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

    def get(self, endpoint, params=None, max_retries=2, timeout=60):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                
                # Se for 429 Too Many Requests, respeitamos o Rate Limit
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        wait_seconds = int(retry_after) / 1000.0
                    else:
                        wait_seconds = 1.5
                    time.sleep(wait_seconds)
                    continue
                
                response.raise_for_status()
                return response.json()
                
            except HTTPError as e:
                # Tratamento de códigos de erro
                if response.status_code == 400:
                    try:
                        err_json = response.json()
                        err_msg = err_json[0].get("method-error-400") if isinstance(err_json, list) and err_json else ""
                        if "Token inválido" in err_msg:
                            raise ValueError("Token da API Excia inválido ou não autorizado.")
                    except (ValueError, IndexError):
                        pass
                if attempt == max_retries - 1:
                    raise e
                time.sleep(1.0)
                
            except RequestException as e:
                if attempt == max_retries - 1:
                    print(f"Erro de rede ao chamar {url}: {e}")
                    raise e
                time.sleep(1.5)
 # Espera simples por erro de rede genérico

        return None
