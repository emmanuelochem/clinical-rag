import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const config: NextConfig = {
  // Proxy API calls to FastAPI so the browser talks to a single origin.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  // Streaming SSE responses must not be buffered/compressed by the dev proxy.
  compress: false,
  output: "standalone",
};

export default config;
