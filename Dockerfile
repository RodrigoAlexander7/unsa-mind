FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir .
ENV UNSA_DATA_DIR=/data
VOLUME /data
EXPOSE 8000
CMD ["unsa-mind", "serve"]
