#!/bin/sh
set -eu

if [ "$#" -gt 1 ]; then
  echo "Usage: sh scripts/build-images.sh [optional-extra-tag]" >&2
  exit 2
fi

source_sha=$(git rev-parse --verify HEAD)
extra_tag=${1-}
if [ -n "$extra_tag" ] && ! printf '%s' "$extra_tag" | grep -Eq '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$'; then
  echo "Extra tag must be a valid Docker tag." >&2
  exit 2
fi

registry=ghcr.io/sadevaraj
backend_image="$registry/simple-sudoku-backend"
frontend_image="$registry/simple-sudoku-frontend"
backend_sha="$backend_image:$source_sha"
frontend_sha="$frontend_image:$source_sha"

if [ -n "$(git status --porcelain)" ]; then
  echo "Warning: working tree is dirty; these SHA tags identify HEAD, not the uncommitted image contents." >&2
  echo "Do not push these images. Build and push only from the reviewed, exact commit." >&2
fi

docker build --file backend/Dockerfile --target production --tag "$backend_sha" .
docker build --file frontend/Dockerfile --tag "$frontend_sha" frontend

if [ -n "$extra_tag" ]; then
  docker tag "$backend_sha" "$backend_image:$extra_tag"
  docker tag "$frontend_sha" "$frontend_image:$extra_tag"
fi

printf 'Backend image: %s\n' "$backend_sha"
printf 'Backend image ID: %s\n' "$(docker image inspect --format '{{.Id}}' "$backend_sha")"
printf 'Frontend image: %s\n' "$frontend_sha"
printf 'Frontend image ID: %s\n' "$(docker image inspect --format '{{.Id}}' "$frontend_sha")"
if [ -n "$extra_tag" ]; then
  printf 'Backend extra-tag image: %s:%s\n' "$backend_image" "$extra_tag"
  printf 'Frontend extra-tag image: %s:%s\n' "$frontend_image" "$extra_tag"
fi
printf '\nManual owner push commands (not executed):\n'
printf 'docker push %s\n' "$backend_sha"
printf 'docker push %s\n' "$frontend_sha"
if [ -n "$extra_tag" ]; then
  printf 'docker push %s:%s\n' "$backend_image" "$extra_tag"
  printf 'docker push %s:%s\n' "$frontend_image" "$extra_tag"
fi
