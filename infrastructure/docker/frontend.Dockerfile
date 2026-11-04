# Vite 개발 서버를 실행한다. 로컬 전용이며 배포 이미지가 아니다.
FROM node:22-slim
WORKDIR /app
# Vite가 실행 중 /app에 임시 설정 파일과 캐시를 쓴다.
RUN chown node:node /app
USER node

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src src

EXPOSE 5173
CMD ["node_modules/.bin/vite", "--host", "0.0.0.0"]
