# Use the official Python image
FROM python:3.11-slim

# Create a directory for your bot
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your bot's code
COPY . .

# Tell the container how to start the bot (change main.py if yours is named differently)
CMD ["python", "main.py"]
