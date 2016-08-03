#!/usr/bin/env sh

# Create environment nodes
docker exec zookeeper /opt/zookeeper/bin/zkCli.sh create /env ''
docker exec zookeeper /opt/zookeeper/bin/zkCli.sh create /env/dev ''
docker exec zookeeper /opt/zookeeper/bin/zkCli.sh create /env/dev/sd ''
docker exec zookeeper /opt/zookeeper/bin/zkCli.sh create /env/prod ''
docker exec zookeeper /opt/zookeeper/bin/zkCli.sh create /env/prod/sd ''

# Create service definitions
docker exec zookeeper /opt/zookeeper/bin/zkCli.sh create /env/dev/sd/test-app '{"nerve": {"reporter_type": "zookeeper", "check_interval" : 5, "checks": [{"type": "http", "uri": "/", "timeout": 0.2, "rise": 3, "fall": 2}]}}'
