FROM redhat/ubi9:latest
LABEL maintainer=marcelo.vogel@cern.ch

# set up environment
ENV USR=flasky
ENV home_dir=/home/${USR}
ENV GID=208
ENV config_dir=/home/${USR}/config
ENV NG_CLI_ANALYTICS=FALSE

USER root
RUN groupadd -g $GID $USR \
    && useradd -g $GID -d /home/$USR $USR
RUN mkdir -p ${config_dir}

COPY ./requirements.txt ${home_dir}/
COPY ./entrypoint.sh ${home_dir}/
COPY src/ ${home_dir}/src
COPY auth/ ${home_dir}/auth

RUN dnf install -y wget git
RUN wget https://download.oracle.com/otn_software/linux/instantclient/219000/oracle-instantclient-basic-21.9.0.0.0-1.el8.x86_64.rpm && \
    dnf localinstall -y oracle-instantclient-basic-21.9.0.0.0-1.el8.x86_64.rpm

WORKDIR ${home_dir}

RUN dnf install -y python3-pip && \
    pip install --no-cache-dir --upgrade pip -r requirements.txt && \
    cd auth/ && pip install ./src

RUN dnf clean all

RUN chown -R ${USR}:${USR} ${home_dir}
USER ${USR}

EXPOSE 5000

ENTRYPOINT ["./entrypoint.sh", "gunicorn"]
