FROM python:2.7

ENV DMAKE_DIR /usr/local/lib/python2.7/site-packages/dmake
ENV DMAKE_CONFIG_DIR /etc/dmake

COPY dmake ${DMAKE_DIR}
COPY requirements.txt ${DMAKE_DIR}/
COPY install.sh       ${DMAKE_CONFIG_DIR}/

RUN pip install -r ${DMAKE_DIR}/requirements.txt
RUN ${DMAKE_CONFIG_DIR}/install.sh

ENV PATH ${DMAKE_DIR}:${DMAKE_DIR}/utils:${PATH}
