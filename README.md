# Nervesync
The purpose of this is to detect watch definitions (only Zookeeper at the moment) and services (only Docker at the moment) to reload Nerve in such a way that covered services are still available for service discovery through the SmartStack system.

I am aware that airbnb/nerve has just merged a pull request for dynamic reloads.  A new Nerve release hasn't been created as of writing.  See the nerve-reload branch for experiments with the new, reloadable Nerve.

## About
### Disclaimer
This project is _not_ production ready and is _not_ tested throughly...yet.

### Why
In 2013, AirBnB's [SmartStack: Service Discovery in the Cloud](http://nerds.airbnb.com/smartstack-service-discovery-cloud/) announced the open source projects "Nerve" and "Synapse".  In the article, the authors claimed that they were "considering adding dynamic service registration for Nerve."  It is now 2016 and Nerve does not have any dynamic capabilities.  Each service must be listed in Nerve's config file.  What's worse, Nerve does not have reload capabilities.  Also, restarting the process isn't an option being that it would wipe out all of the ephemeral znodes in Zookeeper (zk hosts).

We considered using Nerve as a sidekick processes to each app, but it seemed wasteful to have so many instances of nerve running.  Also, having an image with Nerve (Ruby environment) in addition to an environment conducive to whatever app we are actually wanting to run would be very fat.  We considered using Nerve as a sidekick container, but that solution has all of the same pitfalls as the sidekick process solution as well as the added complexity of having two containers communicate.

### Architecture
Nervesync is a daemon that does 3 things: loads service definitions dynamically, detects changing docker containers marked as apps to be registered, and manages two instances of Nerve.  I know, it does a lot and is highly specific, but it solves a problem—for me at least.

This image uses [S6](http://skarnet.org/software/s6/) (specifically [s6-overlay](https://github.com/just-containers/s6-overlay)) as its supervisor.

Nervesync uses [kazoo](https://kazoo.readthedocs.io/en/latest/) to interface with Zookeeper.  I have done my absolute best to make it play nice, but it still crashes when certain manipulations are done to the watched node tree in ZK.

## How to use
### Required settings
The main two settings to customize is the host's IP address and the Zookeeper host(s) environment variables `HOST_IP` and `ZK_HOSTS`.

For service definitions detection to work, your zk host(s) must have definition nodes in JSON format that are named as the app here: `/env/{env}/sd/{app}` ("`{env}`" is where all your environments like "dev" and "prod" live; "`{app}`" is where your service definitions live).  The definition node must have a top-level-property of "nerve" that contains a nerve config partial.  That paritial will look something like this:
```json
{
  "nerve": {
    "reporter_type": "zookeeper",
    "check_interval" : 5,
    "checks": [
      {
      "type": "http",
        "uri": "/health",
        "timeout": 0.2,
        "rise": 3,
        "fall": 2
      },
      ...
    ]
  },
  ...
}
```
Note that the "host", "port", "zk_hosts", and "zk_path" attributes are missing.  Those attributes will be generated by Nervesync.  For more information about Nerve configuration see the [Nerve project](https://github.com/airbnb/nerve#configuration).

For docker container detection to work, Nervesync needs access to the Docker sock file and needs service containers to have two labels: `sd-name` (should match that of the definition node name) and `sd-env` (should match that of the definitions containing environment node).  For a service called MyService on the prod environment to be picked up, it will need to have it's definition at `/env/prod/sd/MyService` and the container will need the labels of `sd-name=MyService` and `sd-env=prod`.

### Example
```sh
docker run --name nervesync \
  -e "HOST_IP=<host ip>" \
  -e "ZK_HOSTS=<host:port,host:port,...>" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  nervesync
```

## Testing
```sh
cd /path/to/this/repo

# Start test Zookeeper instance
docker run -d --name zookeeper -p 2181:2181 jplock/zookeeper

# Build ZK tree on test Zookeeper
./example/populate_zk.sh

# Start Nervesync
docker run --name nervesync \
  --link zookeeper \
  -e "HOST_IP=<host ip>" \
  -e "ZK_HOSTS=zookeeper:2181" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  nervesync

# Start test app
docker run --name test-app -d -p 5000:5000 \
  -l "sd-name=test-app" \
  -l "sd-env=dev" \
  alpine sh \
  -c "(echo 'Hello, world' > /tmp/index.html) && httpd -v -f -p 5000 -h /tmp/"

# Check for the test-app's ephemeral node
docker exec -ti zookeeper /opt/zookeeper/bin/zkCli.sh
> ls /env/dev/sd/test-app/sd

# Teardown
docker kill test-app nervesync zookeeper \
  && docker rm test-app nervesync zookeeper
```

## Known issues
* Deleting nodes in the watched tree or with `rmr` will sometimes crash connected Nervesync clients (thanks Kazoo!)
* This project is a pile of crap
