FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema (pdfplumber precisa de libcairo, etc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código do app
COPY . .

# Expor porta
EXPOSE 8000

# Rodar app
CMD ["python", "app.py"]
