import requests
import json
import time

BASE_URL = "https://nakiapi-h.onrender.com"

class NakiBotAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def snh(self, search_term, page=1):
        url = f"{BASE_URL}/snh/"
        params = {"q": search_term, "p": page}
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code != 200:
                    time.sleep(retry_delay)
                    continue
                
                content_type = response.headers.get('Content-Type', '')
                if 'application/json' not in content_type and 'text/html' in content_type:
                    time.sleep(retry_delay)
                    continue
                
                data = response.json()
                return data
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                return {"error": "Timeout o error de conexión después de múltiples intentos"}
            except json.JSONDecodeError:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return {"error": "No es JSON después de múltiples intentos", "raw_response": response.text[:200]}
            except Exception as e:
                return {"error": f"Error: {str(e)}"}
        
        return {"error": "Falló después de múltiples intentos"}

    def s3h(self, search_term, page=1):
        url = f"{BASE_URL}/s3h/"
        params = {"q": search_term, "p": page}
        response = self.session.get(url, params=params, timeout=30)
        
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"error": "No es JSON", "raw_response": response.text[:200]}
        except Exception as e:
            return {"error": str(e)}

    def vnh(self, code):
        url = f"{BASE_URL}/vnh/"
        params = {"code": code}
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code != 200:
                    time.sleep(retry_delay)
                    continue
                
                data = response.json()
                if data.get("title") == "":
                    data["success"] = False
                    data["error"] = "Datos vacíos del servidor"
                else:
                    data["success"] = True
                return data
                
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                return {"error": "Timeout o error de conexión después de múltiples intentos"}
            except json.JSONDecodeError:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return {"error": "No es JSON después de múltiples intentos", "raw_response": response.text[:200]}
            except Exception as e:
                return {"error": f"Error: {str(e)}"}
        
        return {"error": "Falló después de múltiples intentos"}

    def v3h(self, code):
        url = f"{BASE_URL}/v3h/"
        params = {"code": code}
        response = self.session.get(url, params=params, timeout=30)
        
        try:
            data = response.json()
            if data.get("title") == "":
                data["success"] = False
                data["error"] = "Datos vacíos del servidor"
            else:
                data["success"] = True
            return data
        except json.JSONDecodeError:
            return {"error": "No es JSON", "raw_response": response.text[:200]}
        except Exception as e:
            return {"error": str(e)}

    def hito(self, g, p=1):
        url = f"{BASE_URL}/hito/"
        params = {"g": g, "p": p}
        response = self.session.get(url, params=params)
        
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"error": "No es JSON", "raw_response": response.text[:200]}
        except Exception as e:
            return {"error": str(e)}

