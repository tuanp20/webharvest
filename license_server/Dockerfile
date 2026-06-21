FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY license_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY license_server/ license_server/

# Expose port
EXPOSE 8443

# Run with uvicorn
CMD ["python", "-m", "uvicorn", "license_server.main:app", "--host", "0.0.0.0", "--port", "8443"]
