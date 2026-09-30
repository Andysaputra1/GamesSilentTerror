FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential

COPY requirements.txt .
# PyTorch versi CPU untuk IndoBERT (jauh lebih kecil daripada wheel CUDA bawaan PyPI). Versinya sama dengan
# requirements.txt agar langkah berikutnya tidak mengganti torch CPU dengan wheel dari PyPI.
RUN pip install --no-cache-dir torch==2.14.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:asgi_app", "--host", "0.0.0.0", "--port", "8000"]
