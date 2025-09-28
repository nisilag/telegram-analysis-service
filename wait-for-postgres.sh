#!/bin/bash
# Wait for PostgreSQL to be ready for connections

set -e

host="$1"
port="$2"
user="$3"
database="$4"

until PGPASSWORD="$POSTGRES_PASSWORD" psql -h "$host" -p "$port" -U "$user" -d "$database" -c '\q'; do
  >&2 echo "PostgreSQL is unavailable - sleeping"
  sleep 1
done

>&2 echo "PostgreSQL is up - executing command"
exec "${@:5}"
