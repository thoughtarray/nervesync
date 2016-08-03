import json
import logging
import os.path

import requests_unixsocket

logger = logging.getLogger(__name__)

# TODO: MockServiceWatcher, FileServiceWatcher, DirServiceWatcher, DockerServiceWatcher


class DockerServiceWatcher:
    def __init__(self, sock_file='/var/run/docker.sock', env_label='sd-env', name_label='sd-name'):
        self.sock_file = os.path.abspath(sock_file)
        self.socket_client = requests_unixsocket.Session()

        self.env_label = env_label
        self.name_label = name_label

    def poll(self):
        """
        Polls the Docker daemon for known services
        :param known_services: a list of known service names
        :returns list of tuples; each tuple contains 2 elements: service name (string), port (int)
            ex: [('fax', 56780), ('codes', 56781), ('fax', 56789)]
        """

        try:
            containers = json.loads(
                self.socket_client.get('http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/json').text)
        except Exception as e:
            logger.error(e.message)

        ret = {}
        for c in containers:
            if self.env_label in c['Labels'] and self.name_label in c['Labels'] and len(c['Ports']):
                env = c['Labels'][self.env_label]
                name = c['Labels'][self.name_label]
                port = c['Ports'][0]['PublicPort']

                ret[(env, name, port)] = c

        return ret

    def __str__(self):
        return __name__ + ' (' + self.sock_file + ')'





























