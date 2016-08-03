FROM justcontainers/base-alpine

# Install environment stuff

RUN apk --update-cache --no-cache add \
    python=2.7.11-r3 \
    ruby=2.2.4-r0 \
  && rm -rf /tmp/*


# Install Nerve

RUN apk --update-cache --no-cache add --virtual .build_deps \
    ruby-dev=2.2.4-r0 \
    alpine-sdk=0.4-r3 \
  && mkdir -p /opt/smartstack/nerve \
  && mkdir -p /tmp/nerve \
  && git clone -n https://github.com/airbnb/nerve.git /tmp/nerve \
  && cd /tmp/nerve \
  && git checkout 47a5872a5edc8ae69cd9a119d1eac56738cda165 \
  && gem build nerve.gemspec \
  && gem install nerve-0.7.0.gem --install-dir /opt/smartstack/nerve --no-document \
  && apk del --purge -r .build_deps \
  && rm -rf /tmp/*


# Install Nervesync

COPY requirements.txt setup.py /tmp/nervesync/
COPY nervesync/ /tmp/nervesync/nervesync/
COPY bin /tmp/nervesync/bin/

RUN apk --update-cache --no-cache add --virtual .build_deps \
    py-pip=7.1.2-r0 \
  && mkdir -p /opt/nervesync \
  && pip install /tmp/nervesync \
  && apk del --purge -r .build_deps \
  && rm -rf /tmp/*

# Final setup stuff

WORKDIR /root/

ENV GEM_HOME /opt/smartstack/nerve
ENV PATH /opt/smartstack/nerve/bin:$PATH

# Custom overlay
COPY docker_base /
