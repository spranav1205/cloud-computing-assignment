# Build the official sources because anonymous pulls of upstream MinIO images fail.
FROM golang:1.24.9-bookworm AS server-build
WORKDIR /src
RUN git init && git remote add origin https://github.com/minio/minio.git \
    && git fetch --depth 1 origin 7aac2a2c5b7c882e68c1ce017d8256be2feea27f \
    && git checkout FETCH_HEAD
RUN CGO_ENABLED=0 GOMAXPROCS=2 go build -p 2 -trimpath -o /out/minio .

FROM golang:1.24.9-bookworm AS client-build
WORKDIR /src
RUN git init && git remote add origin https://github.com/minio/mc.git \
    && git fetch --depth 1 origin 77f82e18b5401a65958f1619df6ebb994634bd88 \
    && git checkout FETCH_HEAD
RUN CGO_ENABLED=0 GOMAXPROCS=2 go build -p 2 -trimpath -o /out/mc .

FROM debian:bookworm-slim AS server
COPY --from=server-build /out/minio /usr/bin/minio
COPY --from=server-build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
ENTRYPOINT ["minio"]
CMD ["server", "/data"]

FROM debian:bookworm-slim AS client
COPY --from=client-build /out/mc /usr/bin/mc
COPY --from=client-build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
ENTRYPOINT ["mc"]
