"""Pruebas de unidad: no tocan la base ni la red, todo es doble.

Este archivo existe por un motivo concreto y no por costumbre: sin él, pytest importa cada prueba
por su **nombre de archivo**, y `unidad/test_plantilla_excel.py` e
`integracion/test_plantilla_excel.py` son el mismo módulo para el importador. La segunda que se
recoge falla con «import file mismatch» y `pytest` sin argumentos —que es lo que corre la
integración continua— no llega a recoger nada. Con el paquete declarado, las dos se llaman
`unidad.…` e `integracion.…` y dejan de chocar.
"""
