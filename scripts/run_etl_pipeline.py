"""Executa o pipeline completo: extract -> transform -> load -> query"""
from extract_petr4 import extract
from load_petr4 import load
from query_petr4 import query
from transform_petr4 import transform

if __name__ == "__main__":
    extract()
    transform()
    load()
    query()
