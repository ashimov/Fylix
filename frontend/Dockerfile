# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG VITE_SENTRY_DSN=""
ENV VITE_SENTRY_DSN=${VITE_SENTRY_DSN}
RUN npm run build

FROM nginx:1.29-alpine AS runtime
# Pull in apk security fixes newer than the base image build
# (alpine patches openssl/libexpat/libxml2 faster than nginx rebuilds).
RUN apk upgrade --no-cache
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx-spa.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
