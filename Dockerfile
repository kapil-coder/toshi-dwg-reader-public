FROM python:3.12-slim AS lr
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl xz-utils ca-certificates && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://github.com/LibreDWG/libredwg/releases/download/0.13.3/libredwg-0.13.3.tar.xz | tar xJ -C /tmp \
 && cd /tmp/libredwg-0.13.3 && ./configure --prefix=/opt/lr --disable-bindings --disable-python --disable-werror \
 && make -j"$(nproc)" && make install && rm -rf /tmp/libredwg-0.13.3

FROM python:3.12-slim
COPY --from=lr /opt/lr /opt/lr
ENV LD_LIBRARY_PATH=/opt/lr/lib LR_BIN=/opt/lr/bin MPLBACKEND=Agg PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py worker.py dwgread.py ./
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
