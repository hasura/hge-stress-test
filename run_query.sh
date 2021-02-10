#!/usr/bin/env bash

jq -n -c --rawfile query mut_cities.graphql --argfile variables variables_cities.json --arg operationName InsertObjects '{"query":$query, "operationName": $operationName, "variables":$variables}' | curl -XPOST -d @- http://localhost:9080/v1/graphql

