#!/usr/bin/env bash

jq -n -c --rawfile query $1 --arg operationName QueryObjects '{"query":$query, "operationName": $operationName}' | curl -XPOST -d @- http://localhost:9080/v1/graphql

