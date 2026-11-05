import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
// When NEXT_PUBLIC_API_URL is set (e.g. frontend on Vercel, backend on Render) the browser calls the
// backend directly, so no /api proxy is needed. Direct calls also avoid proxy timeouts on long
// streaming answers.
const directApi = Boolean(process.env.NEXT_PUBLIC_API_URL);

const config: NextConfig = {
  async rewrites() {
    return directApi ? [] : [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  // Streaming SSE responses must not be buffered/compressed by the proxy.
  compress: false,
  output: "standalone",
};

export default config;
