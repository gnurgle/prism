# Use a lightweight official Python runtime

FROM python:3.10-slim



# Set working directory inside the container

WORKDIR /app



# Install system dependencies required for OpenCV (cv2) and SQLite

RUN apt-get update && apt-get install -y --no-install-recommends \

    libgl1 \

    libglib2.0-0 \

    sqlite3 \

    && rm -rf /var/lib/apt/lists/*



# Copy and install python requirements

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt



# Copy the rest of the application code into the container

COPY . .



# Ensure upload/storage directories exist inside the container

RUN mkdir -p static/images/templates static/images/svg static/images/glass static/uploads static/svgs



# Expose the port your app runs on

EXPOSE 7665



# Set environment variables for production

ENV FLASK_SECRET_KEY="change-this-to-a-secure-random-key-in-production"

ENV PYTHONUNBUFFERED=1



# Run Gunicorn with 4 workers binding to port 7665

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:7665", "app:app"]
