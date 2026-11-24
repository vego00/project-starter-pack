# 운영용 프런트 이미지. Node로 정적 파일을 빌드하고 Nginx가 제공하며 /api·/health는 백엔드로 전달한다.
FROM node:22-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src src
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28.2-alpine
COPY infrastructure/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# 개발 서버와 같은 포트를 써서 compose.yaml의 포트 연결을 그대로 쓴다.
EXPOSE 5173
