FROM node:22-slim

# better-sqlite3 is a native addon and needs these at compile time
RUN apt-get update && apt-get install -y python3 make g++ && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production
WORKDIR /app

# Install deps first (layer-cached unless package.json changes)
COPY anton-rx-chat/package*.json ./
RUN npm ci

# Copy source and build
COPY anton-rx-chat .

RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
