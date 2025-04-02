# Use Python Base Image
FROM python:3.9

# Set Working Directory
WORKDIR /app

# Copy Files
COPY app.py requirements.txt ./

# Install Dependencies
RUN pip install -r requirements.txt

# Expose Port
EXPOSE 8000

# Run FastAPI Server
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
