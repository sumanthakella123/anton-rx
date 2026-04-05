import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Prevent Turbopack/webpack from bundling the native better-sqlite3 addon;
  // it is loaded at runtime by Node.js directly.
  serverExternalPackages: ["better-sqlite3"],

  // Exclude the SQLite database file from the Next.js output file trace so
  // Turbopack doesn't flag the dynamic path.join as an unexpected traced file.
  outputFileTracingExcludes: {
    "*": ["**/*.db", "**/*.db-shm", "**/*.db-wal"],
  },
};

export default nextConfig;
