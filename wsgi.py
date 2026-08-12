#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Point d'entrée WSGI pour PythonAnywhere (hébergement permanent)."""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from app import app as application, init_db

# Crée la base / tables au démarrage (idempotent)
init_db()
