FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY public ./public
COPY src ./src
COPY views ./views

ENV NODE_ENV=production \
    PORT=8080

EXPOSE 8080

CMD ["node", "src/server.js"]
