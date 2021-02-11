#!/usr/bin/env bash

jq -n -c --rawfile query $1 --argfile variables payload/variables.json --arg operationName InsertObjects '{"query":$query, "operationName": $operationName, "variables":$variables}' | curl -XPOST -d @- http://localhost:9080/v1/graphql

