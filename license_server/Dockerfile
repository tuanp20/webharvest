FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Expose port
EXPOSE 8443

# Run with uvicorn
CMD ["python", "-m", "uvicorn", "license_server.main:app", "--host", "0.0.0.0", "--port", "8443"]
