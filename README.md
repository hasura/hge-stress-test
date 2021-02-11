# stress test for the hasura graphql engine

this script allows you to configure and run workloads against a running graphql-engine instance, and produces an animated visualisation of memory usage. both bursty and sustained workloads are possible, and workloads can be configured to get heavier or lighter over time.

## workload structure

test workloads are of the following form:

* we run `loop_count` _loops_
  * each loop consists of `bursts_per_loop` _bursts_
    * each burst consists of `requests_per_burst` _requests_
    * after each request, we wait for `request_delay` seconds
    * once all requests are sent, the burst is complete
    * if `wait_for_bursts_to_complete`, we wait for graphql-engine to respond to all requests made as part of the burst here
    * then we wait for `burst_delay` seconds
* then we wait for `loop_delay` before starting a new loop

`requests_per_burst` and `bursts_per_loop` are configured in a way that lets them linearly ramp up (or down) over time to simulate increasingly heavy workloads, with `_min` and `_incr` options in the config file. Setting the `_incr` option to zero allows for workloads of constant intensity.

## visualisation format

![img](img/6-20000-7-500.png)

* the red bars correspond to the period in which a burst is being sent
* each grey marker is a response received from hge
* each green line corresponds to a burst which has been _fully_ serviced by hge.

## workload quality

bursty workloads can be simulated with fewer, larger bursts and a large burst delay. for sustained load tests, burst delay can be made equal to request delay.

to avoid overloading the server with too many pending requests, set `wait_for_bursts_to_complete` to true.

## setup instructions

`stress.py` expects a `graphql-engine` pid to monitor for memory usage, and a configuration file that defines the parameters for the test.

```
# install python deps
$ pip install -r requirements.txt

# set up the postgres db
$ docker run --rm --name hge2 -e "POSTGRES_PASSWORD=password" -p 7432:5432 -d postgres -c "log_statement=all"
$ PGPASSWORD=password psql -h 172.17.0.1 -U postgres -d postgres -p 7432 --single-transaction -f dump.sql

# start hge, e.g. for 1.3.2 (repro version):
$ docker run --rm -p 9080:8080 hasura/graphql-engine:v1.3.2 graphql-engine \
  --database-url='postgresql://postgres:password@172.17.0.1:7432/postgres' serve \
  --enable-telemetry false --enable-console --query-plan-cache-size 0 --use-prepared-statements 'false'

# import the metadata in the console

# run the tests
$ ./stress.py config/bursty.toml $(pidof graphql-engine)
```
