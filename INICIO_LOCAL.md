# Inicialización local

```bash
python -m venv venv
```

```bash
venv/Scripts/pip install -r requirements.txt
```

Copiar `.env.example` a `.env` (en Windows, guardarlo **sin BOM**) y generar la clave:

```bash
venv/Scripts/python -c "import secrets; print(secrets.token_hex(32))"
```

Sembrar la base de datos:

```bash
venv/Scripts/flask --app run.py init-db
```

Arrancar (http://127.0.0.1:5000):

```bash
venv/Scripts/python run.py
```
