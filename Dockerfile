FROM node:22-slim

# better-sqlite3 is a native addon and needs these at compile time
RUN apt-get update && apt-get install -y python3 make g++ && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install ALL deps (including devDependencies such as @tailwindcss/postcss,
# tailwindcss, etc.) so that `next build` can run PostCSS transforms.
COPY anton-rx-chat/package*.json ./
RUN npm ci

# Copy source and build
COPY anton-rx-chat .

RUN npm run build

# Prune devDependencies after the build so the final image stays lean
RUN npm prune --production

ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "start"]
