ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache nginx jq python3 bash

COPY run.sh /run.sh
COPY app.py /app.py

RUN chmod a+x /run.sh \
    && mkdir -p /run/nginx /usr/share/nginx/html

LABEL \
  io.hass.version="2.1.2" \
  io.hass.type="addon" \
  io.hass.arch="amd64|aarch64"

CMD [ "/run.sh" ]
