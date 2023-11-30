#!/bin/bash

mkdir -p lib/static/json
curl -o lib/static/json/fields.json https://issues.redhat.com/rest/api/2/field/
