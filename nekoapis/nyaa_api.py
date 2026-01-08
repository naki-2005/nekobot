import requests

class Nyaa_search:
    def nyaafun(self, query):
        url = "https://nakiapi-nyaa.onrender.com/fun"
        params = {"q": query}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except:
            return []

    def nyaafap(self, query):
        url = "https://nakiapi-nyaa.onrender.com/fap"
        params = {"q": query}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except:
            return []