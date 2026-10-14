FROM node:20-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV API_ORIGIN=http://api:8000

COPY apps/web/package.json ./
RUN npm install

COPY apps/web/ ./

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
