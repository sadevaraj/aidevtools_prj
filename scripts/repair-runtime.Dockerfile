# Built only from the authorized healthy tooling revision, never the candidate.
FROM node:22.14.0-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global @github/copilot@1.0.103
ENV HOME=/tmp/home XDG_CONFIG_HOME=/tmp/home/.config
WORKDIR /workspace
ENTRYPOINT ["copilot"]
