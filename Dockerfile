FROM python:3.12-slim

COPY startrek /usr/local/bin/startrek
COPY data/startrek.db /usr/local/share/startrek/startrek.db

ENV STARTREK_DB=/usr/local/share/startrek/startrek.db

RUN chmod +x /usr/local/bin/startrek

ENTRYPOINT ["startrek"]
CMD []
