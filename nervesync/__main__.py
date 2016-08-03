import argparse
from copy import deepcopy
from glob import glob
import json
import logging
import os
import re
import signal
import subprocess
import time
from urllib2 import urlopen

from definition_watchers import ZkDefinitionWatcher
from service_watchers import DockerServiceWatcher

logger = logging.getLogger('nervesync')

class NerveSync:
    def __init__(self, def_watcher, svc_watcher, sync_manager, def_cooldown=5, svc_cooldown=2, sync_cooldown=10):
        self.definition_watcher = def_watcher
        self.service_watcher = svc_watcher
        self.sync_manager = sync_manager

        self.definition_reload_cooldown = def_cooldown
        self.service_reload_cooldown = svc_cooldown
        self.nerve_reload_cooldown = sync_cooldown

        self.run = True

        self._prep_signals()

    def start(self):
        last_definition_reload = 0
        definition_state = []
        definition_state_stubs = set()  # hashable

        last_service_reload = 0
        service_state = []
        service_state_stubs = set()  # hashable

        juggle_nerve = False
        last_nerve_reload = 0

        while self.run:
            now = time.time()

            # --- poll definitions
            if now > last_definition_reload + self.definition_reload_cooldown:
                new_state = self.definition_watcher.poll()
                new_state_stubs = {k for k in new_state.iterkeys()}

                new = new_state_stubs - definition_state_stubs
                missing = definition_state_stubs - new_state_stubs

                if new or missing:
                    juggle_nerve = len(service_state_stubs) > 0  # TODO: only juggle if new or missing def affects services

                    for tup in new:
                        logger.info('new definition: "%s"', tup)

                    for tup in missing:
                        logger.info('missing definition: "%s"', tup)

                    definition_state = new_state
                    definition_state_stubs = new_state_stubs

                last_definition_reload = time.time()

            # --- poll services
            if now > last_service_reload + self.service_reload_cooldown:
                new_state = self.service_watcher.poll()
                new_state_stubs = {k for k in new_state.iterkeys()}

                new = new_state_stubs - service_state_stubs
                missing = service_state_stubs - new_state_stubs

                if new or missing:
                    juggle_nerve = True

                    for tup in new:
                        logger.info('new service: "%s"', tup)
                    for tup in missing:
                        logger.info('missing service: "%s"', tup)

                    service_state = new_state
                    service_state_stubs = new_state_stubs

                last_service_reload = time.time()

            # --- sync nerve
            if juggle_nerve and now > last_nerve_reload + self.nerve_reload_cooldown:
                self.sync_manager.sync(definition_state, service_state)

                juggle_nerve = False
                last_nerve_reload = time.time()

            # --- cooldown
            time.sleep(1)

        # exit in style :)
        print('')

    def _prep_signals(self):
        def _handle_sigint(sig_num, stack_frame):
            self.run = False

        signal.signal(signal.SIGINT, _handle_sigint)


class S6ServiceManager:
    def __init__(self, services_dir, service_name):
        self.service = os.path.join(services_dir, service_name)

    def status(self):
        text_status = subprocess.check_output(['s6-svstat', self.service])
        #TODO: this could be better and somehow get just the int of seconds out
        state, seconds = re.split(r'\s\(.*\)\s', text_status.strip().split(',')[0])

        return state, int(filter(str.isdigit, seconds))

    def start(self, wait_for_ready=False):
        ret = subprocess.call(['s6-svc', '-wU' if wait_for_ready else '-wu', '-T', '5000', '-u', self.service])

        if ret != 0:
            return False

        return True

    def stop(self, wait_for_ready=False):
        ret = subprocess.call(['s6-svc', '-wD' if wait_for_ready else '-wd', '-T', '5000', '-d', self.service])

        if ret != 0:
            return False

        return True

    def restart(self, wait_for_ready=False):
        ret = subprocess.call(['s6-svc', '-wR' if wait_for_ready else '-wr', '-T', '5000', '-t', self.service])

        if ret != 0:
            return False

        return True

    def reload(self):
        ret = subprocess.call(['s6-svc', '-h', self.service])

        if ret != 0:
            return False

        return True

    def __str__(self):
        return __name__ + ' (' + self.service + ')'


class SyncManager:
    def __init__(self, nerve_manager, nerve_config_dir, nerve_settings):
        self.nerve = nerve_manager

        self.nerve_config_dir = nerve_config_dir

        # TODO: validate nerve_settings
        self.host_ip = nerve_settings['host_ip']
        self.zk_hosts = nerve_settings['zk_hosts']
        self.zk_path = nerve_settings['zk_path']

        self.syncing = False
        self.timeout = 5

    def sync(self, definition_state, service_state):
        # TODO: retry logic!
        if not self.syncing:
            self.syncing = True

            state, time = self.nerve.status()

            # TODO: to be used for retry logic in conjunction with self.timeout
            # now = time.time()

            # if up, reload
            if state == 'up':
                self._write_configs(definition_state, service_state, self.nerve_config_dir)
                logger.info('reloading nerve')
                self._try_op(self.nerve.reload)

                self.syncing = False
                return

            # if down, start
            elif state == 'down':
                self._write_configs(definition_state, service_state, self.nerve_config_dir)
                logger.info('starting nerve')
                self._try_op(self.nerve.start)

                self.syncing = False
                return

    def _try_op(self, op_func):
        success = op_func()

        if not success:
            logger.critical(op_func.__name__ + ' failed')
            exit(1)

    def _write_configs(self, definition_state, service_state, config_dir):
        # delete old config files
        old_config_files = glob(config_dir + '/*.json')

        for f in old_config_files:
            os.remove(f)

        # spool new config file data
        config_files = {}
        for env, name, port in service_state.iterkeys():
            if (env, name) in definition_state:
                definition = definition_state[(env, name)]
                config = deepcopy(definition['nerve'])

                config['host'] = self.host_ip
                config['port'] = port
                config['reporter_type'] = 'zookeeper'
                config['zk_hosts'] = self.zk_hosts
                config['zk_path'] = self.zk_path.format(env=env, name=name)

                config_files['%s/%s_%s_%s.json' % (config_dir, env, name, port)] = json.dumps(config)

        # write new config file data
        for filename, contents in config_files.iteritems():
            with open(filename, 'w') as f:
                f.write(contents)


if __name__ == '__main__':
    # Prep logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Prep args

    parser = argparse.ArgumentParser('nerve-sync')
    parser.add_argument('-z', '--zk-hosts', required=True, help='Comma-separated list of zk-hosts')
    parser.add_argument('-H', '--host-ip', required=False)

    s = vars(parser.parse_args())

    s['zk_hosts'] = (s['zk_hosts'] or '').split(',')
    # Why are we using an AWS-specific thing?  Because, from within a container, it is impossible(?) to get the host's
    # ip address (that it uses to communicate with the the outside world, not the docker network host ip) without
    # passing it via an environment variable.  ECS doesn't allow "computed" variables when setting env variables.
    # TODO: wrap urlopen with try/execpt
    s['host_ip'] = s['host_ip'] or urlopen('http://169.254.169.254/latest/meta-data/local-ipv4').read()

    logger.info('zk_hosts: %s' % s['zk_hosts'])
    logger.info('host_ip: %s' % s['host_ip'])

    # Prep watchers and managers

    def_watcher = ZkDefinitionWatcher(s['zk_hosts'], def_path='/env/?/sd/!')

    svc_watcher = DockerServiceWatcher(sock_file='/var/run/docker.sock', env_label='sd-env', name_label='sd-name')

    nerve = S6ServiceManager('/var/run/s6/services', 'nerve')

    nerve_settings = {
        'host_ip': s['host_ip'],
        'zk_hosts': s['zk_hosts'],
        'zk_path': '/env/{env}/sd/{name}/sd',  # must be in python string format with "env" & "name" named placeholders
    }
    sync_manager = SyncManager(nerve, '/opt/smartstack/nerve/conf.d', nerve_settings)

    # Start app

    app = NerveSync(def_watcher, svc_watcher, sync_manager, def_cooldown=5, svc_cooldown=10, sync_cooldown=20)
    app.start()
