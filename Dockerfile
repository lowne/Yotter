FROM python:alpine AS base

################################################### get app
FROM base AS stage
RUN apk --no-cache add git
RUN git clone --depth=1 --shallow-submodules https://github.com/lowne/yotter \
 && cd yotter \
 && git submodule update --init --depth 1

FROM base AS app
ARG YT_USER=yotter
ARG YT_UID=1000
ARG YT_GID=1000

RUN addgroup -g ${YT_GID} yotter \
 && adduser -h /yotter -G yotter -D -u ${YT_UID} ${YT_USER}
COPY --from=stage --chown=${YT_UID}:${YT_GID} /yotter /yotter

################################################### get requirements
FROM base AS build
COPY --from=stage /yotter/requirements.txt /yotter/
COPY --from=stage /yotter/youtube-local/requirements.txt /yotter/ytl-requirements.txt

#gevent needs gcc, Brotli needs g++
RUN apk --no-cache add gcc musl-dev libffi-dev file make g++ \
 && python -m pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r /yotter/requirements.txt \
 && pip install --no-cache-dir --prefix=/install -r /yotter/ytl-requirements.txt


################################################### final image
FROM app AS instance

COPY --from=build /install /usr/local

ENV YOTTER_CONFIG_FILE=/config/yotter-config.yaml
ENV YOTTER_SQLITE_DB_FILE=/config/yotter.db
ENV YOTTER_TEMP_DIR=/tmp
ENV YOTTER_CACHE_DIR=/tmp/yotter-cache

WORKDIR /yotter
ARG YT_UID=1000
ARG YT_GID=1000
USER ${YT_UID}:${YT_GID}

CMD cd /yotter \
 && flask db upgrade \
 && gunicorn -b 0.0.0.0:5000 -w 4 yotter:app

EXPOSE 5000
