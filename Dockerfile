# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python scripts into the container at /app
COPY ./ ./

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Run proxy.py when the container launches
CMD ["python", "proxy.py"]
