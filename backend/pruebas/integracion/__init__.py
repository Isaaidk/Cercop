"""Pruebas de integración: necesitan una base real, la API levantada y archivos de verdad.

Este archivo existe por el mismo motivo que el de `unidad/`: sin él, pytest importa cada prueba por
su nombre de archivo y los dos `test_plantilla_excel.py` —el de aquí y el de al lado— chocan con
«import file mismatch» al recoger la segunda, de modo que `pytest` sin argumentos falla antes de
ejecutar nada.
"""
