FROM node:22-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV API_ORIGIN=http://api:8000

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web/ ./

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
