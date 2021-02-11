```
$ pip install -r requirements.txt
$ docker run --rm --name hge2 -e "POSTGRES_PASSWORD=password" -p 7432:5432 -d postgres -c "log_statement=all"
$ PGPASSWORD=password psql -h 172.17.0.1 -U postgres -d postgres -p 7432 --single-transaction -f insert_mem.sql

# start hge, for 1.3.2 (repro version):
$ docker run --rm -p 9080:8080 hasura/graphql-engine:v1.3.2 graphql-engine --database-url='postgresql://postgres:password@172.17.0.1:7432/postgres' serve --enable-telemetry false --enable-console --query-plan-cache-size 0 --use-prepared-statements 'false'

# import the metadata in the console

$ ./stress.py $(pidof graphql-engine)
```
