FROM node:22.14.0-alpine3.21 AS source

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

FROM source AS tests
CMD ["sh", "-c", "npm test -- --run && npm run build"]

FROM source AS build
RUN npm run build

FROM nginx:1.27.4-alpine
ENV PORT=80
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
