# SPDX-FileCopyrightText: 2026 Thiago S. R. Silva, Diego S. Porto
# SPDX-License-Identifier: MIT

# Use an official Python runtime
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements file if you have one
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files (including LICENSES and configs)
COPY . .

# Create ontology directory
RUN mkdir -p /app/ontologies

# Download ontologies
RUN curl -L -o /app/ontologies/pato.owl http://purl.obolibrary.org/obo/pato.owl && \
    curl -L -o /app/ontologies/hao.owl http://purl.obolibrary.org/obo/hao.owl && \
    curl -L -o /app/ontologies/uberon.owl http://purl.obolibrary.org/obo/uberon.owl
    
# Set environment variables for Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run the script by default
CMD ["python", "-m", "phylo_parser"]

