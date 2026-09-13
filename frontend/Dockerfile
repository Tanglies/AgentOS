FROM node:24-alpine AS builder

ARG VITE_DEMO_MODE=true
ARG VITE_API_BASE_URL=/api/v1
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN VITE_DEMO_MODE="${VITE_DEMO_MODE}" VITE_API_BASE_URL="${VITE_API_BASE_URL}" npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
