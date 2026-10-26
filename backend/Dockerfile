FROM python:3.12-slim

WORKDIR /app

# fonts-noto-cjk: needed to draw Chinese/Japanese/Korean subtitle text when
# burning captions into exported video (see app/render.py _find_font()).
# libgl1 / libglib2.0-0: runtime libs for opencv, which mediapipe (app/avsync.py) imports.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
