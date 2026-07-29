import requests
import json

url = "http://localhost:8077/v1/qdrant/collections/jurisprudencia/query/vector"
payload = {
    "query_vector": "teste",
    "limit": 5,
    "filter": {}
}

response = requests.post(url, json=payload)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")

url_search = "http://localhost:8077/v1/qdrant/collections/jurisprudencia/search"
payload_search = {
    "collection_name": "jurisprudencia",
    "query_text": "teste",
    "limit": 5,
    "filter": {}
}

response_search = requests.post(url_search, json=payload_search)
print(f"Search Status Code: {response_search.status_code}")
print(f"Search Response: {response_search.text}")
