import json
import logging
from os.path import basename

import kazoo.client
import kazoo.exceptions

from kazoo.client import KazooClient
from kazoo.protocol.states import WatchedEvent
from kazoo.protocol.states import EventType
from kazoo.retry import KazooRetry

logger = logging.getLogger(__name__)

#TODO: MockDefinitionWatcher, ConfigDefinitionWatcher, DirDefinitionWatcher, ZkDefinitionWatcher

class MockDefinitionWatcher:
    """
    definition: {
        "name": 'fax',
        "check_interval": 5,
        "checks": [
            {
                "type": "http",
                "uri": "/meta/health",
                "timeout": 1,
                "rise": 1,
                "fall": 2
            }
        ],
        "zk_path": "/prod/yellow/services/Fax/services",
    }
    """

    def __init__(self, services):
        self.known_services = services

    def poll(self):
        definition_stubs = []
        definitions = []
        for s in self.known_services:
            definition_stubs.append(s)
            definitions.append({
                'name': s,
                'check_interval': 5,
                'checks': [
                    {
                        'type': 'http',
                        'uri': '/meta/health',
                        'timeout': 1,
                        'rise': 1,
                        'fall': 2
                    }
                ],
                'zk_path': ''
            })

        return definitions, definition_stubs


class ZkDefinitionWatcher2:
    def __init__(self, zk_hosts, env, path):
        self.zk = kazoo.client.KazooClient(','.join(zk_hosts), read_only=True)
        self.zk.start()

        self.service_def_node = '/%s%s' % (env, path)

        self.service_defs = {}


        # before: up
        self.watched_envs = []
        #self.watched_defs = []

        logger.info('start watch tree')
        if self.zk.exists('/env'):
            # watch each environment
            @self.zk.ChildrenWatch('/env')
            def watch_envs(env_nodes):
                #logger.info('watch_envs(' + str(env_nodes) + ')')
                for env_node in env_nodes:
                    path = '/env/' + env_node + '/sd'
                    logger.info('if ' + str(env_node) + ' not in ' + str(self.watched_envs) + ' and self.zk.exists(' + path + ') = ' + str(self.zk.exists(path)))
                    if env_node not in self.watched_envs and self.zk.exists(path):
                        logger.info('env path "%s" found' % (path))
                        # watch service definitions for each environment
                        @self.zk.ChildrenWatch(path)
                        def watch_defs(def_nodes):
                            logger.info('watch_defs(' + str(def_nodes) + ')')
                            for def_node in def_nodes:
                                path = '/env/' + env_node + '/sd/' + def_node
                                if env_node + '_' + def_node not in self.service_defs and self.zk.exists(path):
                                    logger.info('data node "%s" found' % (path))
                                    # watch each service def in service definintions for each environment
                                    @self.zk.DataWatch(path)
                                    def watch_def(data, stat, event):
                                        # if event was passed, check for deletion
                                        if event and event.type == 'DELETED':
                                            # we use event.path instead of name because if two nodes
                                            # are removed in one command like this in zk-shell
                                            # (rm foo bar), name will be 'foo' both times
                                            del self.service_defs[env_node + '_' + basename(event.path)]
                                            logger.info(self.service_defs)
                                            return False

                                        try:
                                            self.service_defs[env_node + '_' + def_node] = json.loads(data)
                                            logger.info(self.service_defs)
                                        except ValueError:
                                            logger.error('Service definition for ' + def_node +
                                                         'in environment ' + env_node + ' cannot be parsed as JSON')

                        self.watched_envs.append(env_node)
        else:
            raise Exception('Required zookeeper node "/env" does not exist')


        return
        # before: down
        if self.zk.exists(self.service_def_node):
            @self.zk.ChildrenWatch(self.service_def_node)
            def watch_children(children):
                for name in children:
                    if name not in self.service_defs:

                        @self.zk.DataWatch(self.service_def_node + '/' + name)
                        def watch_node(data, stat, event):
                            # if event was passed, check for deletion
                            if event and event.type == 'DELETED':
                                # we use event.path instead of name because if two nodes
                                # are removed in one command like this in zk-shell
                                # (rm foo bar), name will be 'foo' both times
                                del self.service_defs[basename(event.path)]
                                return False

                            try:
                                self.service_defs[name] = json.loads(data)
                            except ValueError:
                                logger.error('Service definition for ' + name + ' cannot be parsed as JSON')

        else:
            logger.critical('path "' + self.service_def_node + '" does not exist in zookeeper')
            exit(1)

    def poll(self):
        if not self.zk.connected:
            self.zk.start()

        # generate hashable definition stubs
        stubs = [k for k in self.service_defs.iterkeys()]

        return self.service_defs, stubs


class ZkDefinitionWatcher:
    def __init__(self, zk_hosts, def_path='/env/?/sd/!'):
        c_retry = KazooRetry(-1, max_delay=60)
        self._zk = KazooClient(','.join(zk_hosts), read_only=True,
                               connection_retry=c_retry)
        self._zk.start(timeout=10)

        self._child_watchers = {}
        self._data_watchers = {}

        # Note about "stack": the stack is a ZK path of where to find service definitions. It solves the problem of a
        # tree watcher watching an entire tree. A node is only watched if it adhears to the stack pattern. A "?" means
        # "watch children of whatever is here" (this must be the environment). A "!" means "watch data of whatever is
        # here" (this must be the service defs). Anything else is a constant, so it will only watch the children of that
        # specific node if it exists.
        self._stack = tuple(def_path.strip('/').split('/'))

        we = WatchedEvent(None, None, '/' + self._stack[0])
        self._watch_children(we)

    def poll(self):
        env_index = self._stack.index('?')
        name_index = self._stack.index('!')

        ret = {}
        for path, data in self._data_watchers.iteritems():
            # Get env from path
            env = path.strip('/').split('/')[env_index]
            # Get name from path
            name = path.strip('/').split('/')[name_index]

            data['path'] = path

            ret[(env, name)] = data

        return ret

    def _watch_children(self, event):
        # Called when a child node is deleted
        if event.type == EventType.DELETED:
            # Remove child watcher from our records
            del self._child_watchers[event.path]
            # remove datawatchers?
            return

        # Get children and set a child watch for the next event of this path
        children = self._zk.retry(self._zk.get_children, event.path, watch=self._watch_children)
        # Update our records
        self._child_watchers[event.path] = children

        # If no children, there is nothing to do; no watchers to set
        if len(children) == 0:
            return

        # Find location in stack for children
        level = len(event.path.strip('/').split('/'))
        child_depth_marker = self._stack[level]

        for child in children:
            path = "{0}/{1}".format(event.path, child)

            if child_depth_marker == '?' or child == child_depth_marker:
                # Set child_watcher for each child
                if path not in self._child_watchers:
                    we = WatchedEvent(None, None, path)
                    self._watch_children(we)

            elif child_depth_marker == '!':
                # Set data_watcher for each child
                if path not in self._data_watchers:
                    we = WatchedEvent(None, None, path)
                    self._watch_data(we)

    def _watch_data(self, event):
        # Called when a child node is deleted
        if event.type == EventType.DELETED:
            # Remove child watcher from our records
            del self._data_watchers[event.path]
            return

        # Get data and set a data watch for the next event of this path
        data, _stat = self._zk.retry(self._zk.get, event.path, watch=self._watch_data)

        # Update our records
        try:
            # TODO: validate JSON?
            parsed_data = json.loads(data)
            self._data_watchers[event.path] = parsed_data
        except ValueError:
            logger.warning('Service definition "' + event.path + '" cannot be parsed as JSON')
            # If service def isn't in proper format, remove it from known service defs
            if event.path in self._data_watchers:
                del self._data_watchers[event.path]



























