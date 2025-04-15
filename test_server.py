import unittest
from server import search_vector_db
import chromadb

class TestSearchVectorDB(unittest.TestCase):
    def setUp(self):
        client = chromadb.PersistentClient(".")
        self.collection = client.get_collection("kubecon_-_cloudnativecon_europe_2025_-_london")

    def test_search_vector_db_returns_results(self):
        result = search_vector_db(self.collection, "Python programming")   
        print(result)

if __name__ == '__main__':
    unittest.main()
