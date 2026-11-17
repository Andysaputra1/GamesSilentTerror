# Versi sama dengan engines.node di package.json dan Node di Vercel.
FROM node:24.11.1-alpine

WORKDIR /app

COPY package*.json ./
# npm ci memasang persis versi di package-lock.json, termasuk Angular CLI proyek.
RUN npm ci

COPY . .

EXPOSE 4200

CMD ["npx", "ng", "serve", "--host", "0.0.0.0", "--poll", "2000"]